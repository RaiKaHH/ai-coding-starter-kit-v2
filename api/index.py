"""
API routes for PROJ-4: Semantischer Struktur-Lerner.

Endpoints:
  GET  /index/              – indexer UI page
  POST /index/start         – kick off async folder profiling
  GET  /index/status        – poll indexing progress
  GET  /index/profiles      – list all learned folder profiles
  DELETE /index/profiles/{id} – remove a profile from memory
  GET  /index/export-yaml   – generate structure_rules.yaml for PROJ-2
"""
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from models.index import FolderProfile, IndexRequest, IndexStatus, YamlExportResponse

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    ...


@router.post("/start")
async def start_indexing(body: IndexRequest, background_tasks: BackgroundTasks) -> IndexStatus:
    ...


@router.get("/status")
async def get_index_status() -> IndexStatus:
    ...


@router.get("/profiles")
async def list_profiles() -> list[FolderProfile]:
    ...


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: int):
    ...


@router.get("/export-yaml")
async def export_yaml() -> YamlExportResponse:
    ...
