"""
API routes for PROJ-3: KI-gestützter Datei-Umbenenner.

Endpoints:
  GET  /rename/             – rename UI page
  POST /rename/preview      – generate rename preview (fast or smart mode)
  POST /rename/execute      – execute confirmed renames (BackgroundTask)
  GET  /rename/batch/{id}/status – poll async progress
"""
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from models.rename import (
    RenameExecuteRequest,
    RenameExecuteResult,
    RenamePreviewResponse,
    RenameRequest,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def rename_page(request: Request):
    ...


@router.post("/preview")
async def preview_rename(body: RenameRequest) -> RenamePreviewResponse:
    ...


@router.post("/execute")
async def execute_rename(
    body: RenameExecuteRequest, background_tasks: BackgroundTasks
) -> RenameExecuteResult:
    ...


@router.get("/batch/{batch_id}/status")
async def get_batch_status(batch_id: str):
    ...
