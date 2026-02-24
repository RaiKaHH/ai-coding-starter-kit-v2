"""
API routes for PROJ-5: Smart Inbox Triage.

Endpoints:
  GET  /triage/             -- triage UI page
  POST /triage/analyse      -- analyse inbox and return match suggestions
  POST /triage/execute      -- move confirmed files (BackgroundTask)
  POST /triage/feedback     -- store user correction to improve folder_profiles
  GET  /triage/folders      -- list known folders for dropdown
  GET  /triage/batch/{id}/status -- poll async move progress
"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.triage import (
    analyse_inbox,
    apply_feedback,
    execute_triage,
    get_all_folder_paths,
    get_triage_status_store,
)
from models.triage import (
    FeedbackRequest,
    TriageExecuteRequest,
    TriageExecuteResult,
    TriageRequest,
    TriageResponse,
)
from utils.rate_limit import check_triage_rate_limit

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# --------------------------------------------------------------------------- #
# UI page                                                                      #
# --------------------------------------------------------------------------- #

@router.get("/", response_class=HTMLResponse)
async def triage_page(request: Request):
    """Render the Smart Inbox Triage UI."""
    return templates.TemplateResponse("triage.html", {
        "request": request,
        "page_title": "Smart Inbox Triage",
    })


# --------------------------------------------------------------------------- #
# Analyse inbox                                                                #
# --------------------------------------------------------------------------- #

@router.post("/analyse", dependencies=[Depends(check_triage_rate_limit)])
async def analyse_inbox_endpoint(body: TriageRequest) -> TriageResponse:
    """
    Analyse all files in the given inbox folder.

    Two-stage matching:
    1. Strict match against structure_rules.yaml -> 100% confidence
    2. Fuzzy match against folder_profiles -> 0-99% confidence
    """
    inbox_path = body.inbox_path if isinstance(body.inbox_path, Path) else Path(body.inbox_path)

    try:
        return await analyse_inbox(
            inbox_path=inbox_path,
            confidence_threshold=body.confidence_threshold,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except NotADirectoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --------------------------------------------------------------------------- #
# Execute confirmed moves                                                      #
# --------------------------------------------------------------------------- #

@router.post("/execute", dependencies=[Depends(check_triage_rate_limit)])
async def execute_triage_endpoint(
    body: TriageExecuteRequest, background_tasks: BackgroundTasks
) -> TriageExecuteResult:
    """
    Move confirmed files as a background task.
    Delegates to core/mover.py for actual file I/O.
    """
    if not body.confirmed_items:
        raise HTTPException(
            status_code=422,
            detail="Keine Dateien zum Verschieben ausgewaehlt.",
        )

    # Validate that confirmed folders exist as directories
    for item in body.confirmed_items:
        folder = Path(item.confirmed_folder) if not isinstance(item.confirmed_folder, Path) else item.confirmed_folder
        if not folder.exists():
            # Create the target directory (common UX: target may not exist yet)
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                raise HTTPException(
                    status_code=403,
                    detail=f"Kann Zielordner nicht anlegen: {folder}",
                )
        elif not folder.is_dir():
            raise HTTPException(
                status_code=422,
                detail=f"Zielpfad ist kein Ordner: {folder}",
            )

    # BUG-1 FIX: Validate confirmed items against original batch (before background task)
    from core.triage import get_triage_cache
    cached_items = get_triage_cache().get(body.batch_id)
    if cached_items is None:
        raise HTTPException(
            status_code=404,
            detail=f"Triage-Batch nicht gefunden: {body.batch_id}",
        )
    allowed_sources = {item.source_path for item in cached_items}
    for item in body.confirmed_items:
        source_str = str(item.source_path) if isinstance(item.source_path, Path) else item.source_path
        if source_str not in allowed_sources:
            raise HTTPException(
                status_code=422,
                detail=f"Datei '{item.file_name}' gehoert nicht zum Analyse-Batch. Verschiebung abgelehnt.",
            )

    # Launch background task
    background_tasks.add_task(
        execute_triage,
        body.batch_id,
        body.confirmed_items,
    )

    return TriageExecuteResult(
        batch_id=body.batch_id,
        moved_count=0,  # will be updated asynchronously
        failed_count=0,
        errors=[],
    )


# --------------------------------------------------------------------------- #
# Poll batch status                                                            #
# --------------------------------------------------------------------------- #

@router.get("/batch/{batch_id}/status")
async def get_triage_batch_status(batch_id: str) -> dict:
    """Poll the progress of an ongoing or completed triage batch."""
    status_store = get_triage_status_store()
    status = status_store.get(batch_id)
    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Triage-Batch nicht gefunden: {batch_id}",
        )

    return {
        "batch_id": batch_id,
        "total": status["total"],
        "moved": status["moved"],
        "failed": status["failed"],
        "done": status["done"],
        "errors": status["errors"],
    }


# --------------------------------------------------------------------------- #
# Feedback (user corrects folder assignment)                                   #
# --------------------------------------------------------------------------- #

@router.post("/feedback", dependencies=[Depends(check_triage_rate_limit)])
async def submit_feedback(body: FeedbackRequest) -> dict:
    """
    When user manually corrects a folder assignment, update
    folder_profiles.keywords to improve future matching.
    """
    chosen_folder = (
        body.chosen_folder
        if isinstance(body.chosen_folder, Path)
        else Path(body.chosen_folder)
    )

    try:
        await apply_feedback(body.file_name, chosen_folder)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Feedback konnte nicht gespeichert werden: {exc}",
        )

    return {"status": "ok", "message": "Feedback gespeichert."}


# --------------------------------------------------------------------------- #
# List known folders (for dropdown in UI)                                      #
# --------------------------------------------------------------------------- #

@router.get("/folders")
async def list_known_folders() -> list[str]:
    """Return all known folder paths from folder_profiles for UI dropdowns."""
    return await get_all_folder_paths()
