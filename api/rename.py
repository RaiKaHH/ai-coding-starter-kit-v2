"""
API routes for PROJ-3: KI-gestuetzter Datei-Umbenenner.

Endpoints:
  GET  /rename/             -- rename UI page
  POST /rename/preview      -- generate rename preview (fast or smart mode)
  POST /rename/execute      -- execute confirmed renames (BackgroundTask)
  GET  /rename/batch/{id}/status -- poll async progress
"""
import logging
import time
from collections import deque

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.renamer import (
    execute_batch,
    generate_preview,
    get_batch_cache,
    get_batch_status_store,
)
from models.rename import (
    RenameExecuteRequest,
    RenameExecuteResult,
    RenamePreviewResponse,
    RenameRequest,
)

logger = logging.getLogger("api.rename")

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --------------------------------------------------------------------------- #
# Rate limiting                                                               #
# --------------------------------------------------------------------------- #

_RATE_WINDOW_S = 60.0
_RATE_MAX_PREVIEW = 10  # max preview calls per minute
_RATE_MAX_EXECUTE = 5   # max execute calls per minute

_preview_timestamps: deque[float] = deque()
_execute_timestamps: deque[float] = deque()


def _check_rate_limit(timestamps: deque[float], max_calls: int, label: str) -> None:
    """Raise HTTP 429 if more than max_calls have occurred in the sliding window."""
    now = time.monotonic()
    while timestamps and timestamps[0] < now - _RATE_WINDOW_S:
        timestamps.popleft()
    if len(timestamps) >= max_calls:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Zu viele Anfragen an {label}. "
                f"Maximal {max_calls} Anfragen pro Minute erlaubt."
            ),
        )
    timestamps.append(now)


# --------------------------------------------------------------------------- #
# UI page                                                                     #
# --------------------------------------------------------------------------- #

@router.get("/", response_class=HTMLResponse)
async def rename_page(request: Request):
    """Render the rename UI page."""
    return templates.TemplateResponse(
        "rename.html",
        {"request": request, "page_title": "Datei-Umbenenner"},
    )


# --------------------------------------------------------------------------- #
# Preview endpoint                                                            #
# --------------------------------------------------------------------------- #

@router.post("/preview")
async def preview_rename(body: RenameRequest) -> RenamePreviewResponse:
    """
    Generate a rename preview for the selected files.

    Fast mode: uses EXIF/OS date, keeps original base name.
    Smart mode: uses AI content analysis for date + descriptive name.

    Returns a preview with batch_id for later execution.
    """
    _check_rate_limit(_preview_timestamps, _RATE_MAX_PREVIEW, "/rename/preview")

    if not body.file_ids:
        raise HTTPException(status_code=400, detail="Keine Dateien ausgewaehlt.")

    if len(body.file_ids) > 500:
        raise HTTPException(
            status_code=400,
            detail="Maximal 500 Dateien pro Vorschau erlaubt.",
        )

    try:
        return await generate_preview(
            scan_id=body.scan_id,
            mode=body.mode,
            file_ids=body.file_ids,
        )
    except Exception as exc:
        logger.error("Fehler bei Vorschau-Erstellung: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Vorschau konnte nicht erstellt werden: {type(exc).__name__}",
        )


# --------------------------------------------------------------------------- #
# Execute endpoint                                                            #
# --------------------------------------------------------------------------- #

@router.post("/execute")
async def execute_rename(
    body: RenameExecuteRequest,
    background_tasks: BackgroundTasks,
) -> RenameExecuteResult:
    """
    Execute the confirmed renames as a background task.

    The user sends back the (possibly edited) preview items.
    Renames run asynchronously; poll /rename/batch/{id}/status for progress.
    """
    _check_rate_limit(_execute_timestamps, _RATE_MAX_EXECUTE, "/rename/execute")

    if not body.items:
        raise HTTPException(status_code=400, detail="Keine Dateien zum Umbenennen.")

    # Verify batch exists in cache
    cache = get_batch_cache()
    if body.batch_id not in cache:
        raise HTTPException(
            status_code=404,
            detail=f"Batch {body.batch_id} nicht gefunden oder bereits ausgefuehrt.",
        )

    # Validate all filenames are non-empty
    for item in body.items:
        if not item.new_filename or not item.new_filename.strip():
            raise HTTPException(
                status_code=400,
                detail=f"Leerer Dateiname fuer scan_file_id={item.scan_file_id}.",
            )

    # Convert to dicts for the background task
    items_data = [
        {"scan_file_id": item.scan_file_id, "new_filename": item.new_filename}
        for item in body.items
    ]

    # Determine mode from the cached preview
    cached_items = cache.get(body.batch_id, [])
    # We don't have mode in cache, so accept it from the status or default
    status_store = get_batch_status_store()
    batch_status = status_store.get(body.batch_id, {})

    # Launch background task
    background_tasks.add_task(
        execute_batch,
        batch_id=body.batch_id,
        items=items_data,
        mode=body.mode,
    )

    return RenameExecuteResult(
        batch_id=body.batch_id,
        renamed_count=0,
        failed_count=0,
        errors=[],
    )


# --------------------------------------------------------------------------- #
# Batch status polling                                                        #
# --------------------------------------------------------------------------- #

@router.get("/batch/{batch_id}/status")
async def get_batch_status(batch_id: str) -> dict:
    """
    Poll the progress of an ongoing rename batch.

    Returns:
        {total, renamed, failed, done, errors}
    """
    status_store = get_batch_status_store()
    status = status_store.get(batch_id)

    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Batch {batch_id} nicht gefunden.",
        )

    return {
        "batch_id": batch_id,
        "total": status.get("total", 0),
        "renamed": status.get("renamed", 0),
        "failed": status.get("failed", 0),
        "done": status.get("done", False),
        "errors": status.get("errors", []),
    }
