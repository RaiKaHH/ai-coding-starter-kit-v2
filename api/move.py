"""
API routes for PROJ-2: Struktur-basierter Datei-Verschieber.

Endpoints:
  GET  /move/                       -- move UI page
  POST /move/preview/by-rules       -- dry-run via YAML rules file
  POST /move/preview/by-pattern     -- dry-run via reference folder analysis
  POST /move/execute                -- execute confirmed preview batch (BackgroundTask)
  GET  /move/batch/{id}/status      -- poll async move progress
  GET  /move/scans                  -- list completed scans for dropdown
"""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.mover import (
    RuleParseError,
    execute_batch,
    get_batch_cache,
    get_batch_status_store,
    infer_rules_from_folder,
    match_files_to_rules,
    parse_yaml_rules,
)
from models.move import (
    MoveByPatternRequest,
    MoveByRulesRequest,
    MoveExecuteRequest,
    MovePreviewResponse,
)
from utils.db import get_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# --------------------------------------------------------------------------- #
# UI page                                                                      #
# --------------------------------------------------------------------------- #

@router.get("/", response_class=HTMLResponse)
async def move_page(request: Request):
    """Render the move/organise UI."""
    return templates.TemplateResponse("move.html", {
        "request": request,
        "page_title": "Dateien verschieben",
    })


# --------------------------------------------------------------------------- #
# List available scans (for dropdown in UI)                                    #
# --------------------------------------------------------------------------- #

@router.get("/scans")
async def list_completed_scans() -> list[dict]:
    """Return completed scans so the UI can offer them in a dropdown."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT scan_id, source_path, file_count, created_at
            FROM scans
            WHERE status = 'completed'
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        rows = await cursor.fetchall()
        return [
            {
                "scan_id": row["scan_id"],
                "source_path": row["source_path"],
                "file_count": row["file_count"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# Preview: by YAML rules                                                       #
# --------------------------------------------------------------------------- #

@router.post("/preview/by-rules")
async def preview_by_rules(body: MoveByRulesRequest) -> MovePreviewResponse:
    """
    Dry-run: parse the YAML rules file, load scan files from DB,
    match files to rules (top-down priority), and return a preview table.
    """
    # Validate scan exists
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT scan_id FROM scans WHERE scan_id = ? AND status = 'completed'",
            (body.scan_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Kein abgeschlossener Scan gefunden: {body.scan_id}",
            )
    finally:
        await db.close()

    # Parse YAML rules
    rules_path = body.rules_path if isinstance(body.rules_path, Path) else Path(body.rules_path)
    try:
        rules, unmatched_policy = parse_yaml_rules(rules_path)
    except RuleParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Match files to rules
    return await match_files_to_rules(body.scan_id, rules, unmatched_policy)


# --------------------------------------------------------------------------- #
# Preview: by reference folder                                                 #
# --------------------------------------------------------------------------- #

@router.post("/preview/by-pattern")
async def preview_by_pattern(body: MoveByPatternRequest) -> MovePreviewResponse:
    """
    Dry-run: analyse a reference folder to infer rules, load scan files,
    match files to inferred rules, and return a preview table.
    """
    # Validate scan exists
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT scan_id FROM scans WHERE scan_id = ? AND status = 'completed'",
            (body.scan_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Kein abgeschlossener Scan gefunden: {body.scan_id}",
            )
    finally:
        await db.close()

    # Infer rules from reference folder
    pattern_folder = (
        body.pattern_folder
        if isinstance(body.pattern_folder, Path)
        else Path(body.pattern_folder)
    )
    try:
        rules, unmatched_policy = infer_rules_from_folder(pattern_folder)
    except RuleParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not rules:
        raise HTTPException(
            status_code=422,
            detail=(
                "Aus dem Referenzordner konnten keine Regeln abgeleitet werden. "
                "Stell sicher, dass der Ordner Unterordner mit Dateien enthaelt."
            ),
        )

    # Match files to rules
    return await match_files_to_rules(body.scan_id, rules, unmatched_policy)


# --------------------------------------------------------------------------- #
# Execute confirmed batch                                                      #
# --------------------------------------------------------------------------- #

@router.post("/execute")
async def execute_move(
    body: MoveExecuteRequest, background_tasks: BackgroundTasks
) -> dict:
    """
    Execute the confirmed move operations as a background task.
    The user must pass the batch_id from the preview and the selected item IDs.
    """
    cache = get_batch_cache()
    if body.batch_id not in cache:
        raise HTTPException(
            status_code=404,
            detail=f"Batch nicht gefunden oder bereits ausgefuehrt: {body.batch_id}",
        )

    if not body.selected_ids:
        raise HTTPException(
            status_code=422,
            detail="Keine Dateien zum Verschieben ausgewaehlt.",
        )

    # Validate selected_ids exist in the cached batch
    cached_ids = {item.id for item in cache[body.batch_id]}
    invalid_ids = set(body.selected_ids) - cached_ids
    if invalid_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Unbekannte Item-IDs: {sorted(invalid_ids)}",
        )

    # Launch background task
    background_tasks.add_task(execute_batch, body.batch_id, body.selected_ids)

    return {
        "batch_id": body.batch_id,
        "selected_count": len(body.selected_ids),
        "message": "Verschiebe-Vorgang gestartet.",
    }


# --------------------------------------------------------------------------- #
# Poll batch status                                                            #
# --------------------------------------------------------------------------- #

@router.get("/batch/{batch_id}/status")
async def get_batch_status(batch_id: str) -> dict:
    """
    Poll the progress of an ongoing or completed batch move operation.
    Returns moved/failed/total counts plus error details.
    """
    status_store = get_batch_status_store()
    status = status_store.get(batch_id)
    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Batch-Status nicht gefunden: {batch_id}",
        )

    return {
        "batch_id": batch_id,
        "total": status["total"],
        "moved": status["moved"],
        "failed": status["failed"],
        "done": status["done"],
        "errors": status["errors"],
    }
