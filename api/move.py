"""
API routes for PROJ-2: Struktur-basierter Datei-Verschieber.

Endpoints:
  GET  /move/               – move UI page
  POST /move/preview        – dry-run: map files → rules, return preview table
  POST /move/execute        – execute confirmed preview batch (BackgroundTask)
  GET  /move/batch/{id}/status – poll async move progress
"""
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from models.move import (
    MoveByPatternRequest,
    MoveByRulesRequest,
    MoveExecuteRequest,
    MoveExecuteResult,
    MovePreviewResponse,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def move_page(request: Request):
    ...


@router.post("/preview/by-rules")
async def preview_by_rules(body: MoveByRulesRequest) -> MovePreviewResponse:
    ...


@router.post("/preview/by-pattern")
async def preview_by_pattern(body: MoveByPatternRequest) -> MovePreviewResponse:
    ...


@router.post("/execute")
async def execute_move(
    body: MoveExecuteRequest, background_tasks: BackgroundTasks
) -> MoveExecuteResult:
    ...


@router.get("/batch/{batch_id}/status")
async def get_batch_status(batch_id: str):
    ...
