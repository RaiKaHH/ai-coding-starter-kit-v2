"""
API routes for PROJ-5: Smart Inbox Triage.

Endpoints:
  GET  /triage/             – triage UI page
  POST /triage/analyse      – analyse inbox and return match suggestions
  POST /triage/execute      – move confirmed files (BackgroundTask)
  POST /triage/feedback     – store user correction to improve folder_profiles
"""
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from models.triage import (
    FeedbackRequest,
    TriageExecuteRequest,
    TriageExecuteResult,
    TriageRequest,
    TriageResponse,
)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def triage_page(request: Request):
    ...


@router.post("/analyse")
async def analyse_inbox(body: TriageRequest) -> TriageResponse:
    ...


@router.post("/execute")
async def execute_triage(
    body: TriageExecuteRequest, background_tasks: BackgroundTasks
) -> TriageExecuteResult:
    ...


@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest):
    ...
