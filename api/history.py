"""
API routes for PROJ-9: Undo / Rollback-System.

Endpoints:
  GET  /history/            -- history UI page
  GET  /history/operations  -- paginated list of all operations
  GET  /history/batches     -- grouped batch summaries
  POST /history/undo/{id}   -- undo a single operation
  POST /history/undo/batch/{batch_id} -- undo all operations in a batch (LIFO)
  GET  /history/batch/{batch_id}/status -- poll async undo progress
"""
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.undo import get_undo_progress, undo_batch_operations, undo_single_operation
from models.history import BatchSummary, OperationLog, UndoResult
from utils.db import get_db
from utils.rate_limit import check_undo_rate_limit

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def history_page(request: Request):
    """Render the history UI page."""
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "page_title": "Historie"},
    )


@router.get("/operations", response_model=list[OperationLog])
async def list_operations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    operation_type: str | None = Query(None, pattern="^(MOVE|RENAME)$"),
) -> list[OperationLog]:
    """Return a paginated list of all operations, newest first."""
    db = await get_db()
    try:
        offset = (page - 1) * page_size

        if operation_type:
            cursor = await db.execute(
                "SELECT id, batch_id, operation_type, source_path, target_path, "
                "timestamp, status, mode FROM operation_log "
                "WHERE operation_type = ? "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (operation_type, page_size, offset),
            )
        else:
            cursor = await db.execute(
                "SELECT id, batch_id, operation_type, source_path, target_path, "
                "timestamp, status, mode FROM operation_log "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            )

        rows = await cursor.fetchall()
        return [
            OperationLog(
                id=row["id"],
                batch_id=row["batch_id"],
                operation_type=row["operation_type"],
                source_path=row["source_path"],
                target_path=row["target_path"],
                timestamp=row["timestamp"],
                status=row["status"],
                mode=row["mode"],
            )
            for row in rows
        ]
    finally:
        await db.close()


@router.get("/operations/count")
async def count_operations(
    operation_type: str | None = Query(None, pattern="^(MOVE|RENAME)$"),
) -> dict:
    """Return total count of operations (for pagination)."""
    db = await get_db()
    try:
        if operation_type:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM operation_log WHERE operation_type = ?",
                (operation_type,),
            )
        else:
            cursor = await db.execute(
                "SELECT COUNT(*) as cnt FROM operation_log",
            )
        row = await cursor.fetchone()
        return {"total": row["cnt"]}
    finally:
        await db.close()


@router.get("/batches", response_model=list[BatchSummary])
async def list_batches() -> list[BatchSummary]:
    """Return grouped batch summaries, newest first."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT
                batch_id,
                CASE
                    WHEN COUNT(DISTINCT operation_type) > 1 THEN 'MIXED'
                    ELSE MAX(operation_type)
                END as operation_type,
                COUNT(*) as file_count,
                MIN(timestamp) as first_timestamp,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_count,
                SUM(CASE WHEN status = 'reverted' THEN 1 ELSE 0 END) as reverted_count,
                SUM(CASE WHEN status IN ('revert_failed', 'failed') THEN 1 ELSE 0 END) as failed_count
            FROM operation_log
            GROUP BY batch_id
            ORDER BY MAX(id) DESC
            LIMIT 100
            """
        )
        rows = await cursor.fetchall()

        batches: list[BatchSummary] = []
        for row in rows:
            total = row["file_count"]
            reverted = row["reverted_count"]
            failed = row["failed_count"]

            if reverted == total:
                status = "reverted"
            elif reverted > 0 or failed > 0:
                status = "partially_reverted"
            else:
                status = "completed"

            batches.append(
                BatchSummary(
                    batch_id=row["batch_id"],
                    operation_type=row["operation_type"],
                    file_count=total,
                    timestamp=row["first_timestamp"],
                    status=status,
                )
            )

        return batches
    finally:
        await db.close()


@router.post("/undo/{operation_id}", dependencies=[Depends(check_undo_rate_limit)])
async def undo_single(operation_id: int) -> JSONResponse:
    """Undo a single operation by its ID."""
    result, status_code = await undo_single_operation(operation_id)
    return JSONResponse(content=result.model_dump(), status_code=status_code)


@router.post("/undo/batch/{batch_id}", dependencies=[Depends(check_undo_rate_limit)])
async def undo_batch(
    batch_id: str, background_tasks: BackgroundTasks
) -> JSONResponse:
    """Start an async batch undo (LIFO order). Returns immediately."""
    # Verify the batch exists and has undoable operations
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM operation_log "
            "WHERE batch_id = ? AND status = 'completed'",
            (batch_id,),
        )
        row = await cursor.fetchone()
        count = row["cnt"]
    finally:
        await db.close()

    if count == 0:
        return JSONResponse(
            content=UndoResult(
                success=False,
                message="Keine rueckgaengig machbaren Operationen in diesem Batch.",
            ).model_dump(),
            status_code=404,
        )

    # Initialize progress tracker
    progress_store = get_undo_progress()
    progress_store[batch_id] = {
        "batch_id": batch_id,
        "total": count,
        "reverted": 0,
        "failed": 0,
        "done": False,
        "errors": [],
    }

    # Start background task
    background_tasks.add_task(undo_batch_operations, batch_id)

    return JSONResponse(
        content={
            "success": True,
            "message": f"Batch-Undo gestartet fuer {count} Operationen.",
            "reverted_count": 0,
            "failed_count": 0,
            "errors": [],
        },
        status_code=202,
    )


@router.get("/batch/{batch_id}/status")
async def get_undo_status(batch_id: str) -> JSONResponse:
    """Poll the progress of an async batch undo."""
    progress_store = get_undo_progress()
    progress = progress_store.get(batch_id)

    if progress is None:
        return JSONResponse(
            content={
                "batch_id": batch_id,
                "total": 0,
                "reverted": 0,
                "failed": 0,
                "done": True,
                "errors": ["Kein laufender Undo-Vorgang fuer diesen Batch."],
            },
            status_code=404,
        )

    return JSONResponse(content=progress, status_code=200)
