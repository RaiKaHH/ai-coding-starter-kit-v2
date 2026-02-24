"""
API routes for PROJ-6: KI-Integrations-Schicht.

Endpoints:
  GET  /ai/settings         – return current AI provider config (no raw key)
  PUT  /ai/settings         – update provider, model, API key reference
  POST /ai/test             – test connectivity to the configured LLM
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from models.ai_gateway import AISettingsResponse, AISettingsUpdate, AITestResponse

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    ...


@router.get("/settings/data")
async def get_settings() -> AISettingsResponse:
    ...


@router.put("/settings/data")
async def update_settings(body: AISettingsUpdate) -> AISettingsResponse:
    ...


@router.post("/test")
async def test_connection() -> AITestResponse:
    ...
