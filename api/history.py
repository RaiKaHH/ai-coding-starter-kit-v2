"""
API routes for PROJ-9: Undo / Rollback-System.

Endpoints:
  GET  /history/            – history UI page
  GET  /history/operations  – paginated list of all operations
  GET  /history/batches     – grouped batch summaries
  POST /history/undo/{id}   – undo a single operation
  POST /history/undo/batch/{batch_id} – undo all operations in a batch (LIFO)
  GET  /history/batch/{batch_id}/status – poll async undo progress
"""
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from models.history import BatchSummary, OperationLog, UndoBatchRequest, UndoResult

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def history_page(request: Request):
    ...


@router.get("/operations")
async def list_operations(
    page: int = 1,
    page_size: int = 50,
    operation_type: str | None = None,
) -> list[OperationLog]:
    ...


@router.get("/batches")
async def list_batches() -> list[BatchSummary]:
    ...


@router.post("/undo/{operation_id}")
async def undo_single(operation_id: int) -> UndoResult:
    ...


@router.post("/undo/batch/{batch_id}")
async def undo_batch(batch_id: str, background_tasks: BackgroundTasks) -> UndoResult:
    ...


@router.get("/batch/{batch_id}/status")
async def get_undo_status(batch_id: str):
    ...
