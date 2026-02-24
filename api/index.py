"""
API routes for PROJ-4: Semantischer Struktur-Lerner.

Endpoints:
  GET  /index/              -- indexer UI page
  POST /index/start         -- kick off async folder profiling
  GET  /index/status        -- poll indexing progress
  GET  /index/profiles      -- list all learned folder profiles
  DELETE /index/profiles/{id} -- remove a profile from memory
  GET  /index/export-yaml   -- generate structure_rules.yaml for PROJ-2
  POST /index/pick-folder   -- open native macOS folder picker dialog
"""
import logging
import subprocess
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from core.lerner import (
    delete_profile,
    generate_yaml_from_profiles,
    get_all_profiles,
    get_index_status,
    mark_status_running,
    scan_and_profile,
)
from models.index import FolderProfile, IndexRequest, IndexStatus, YamlExportResponse

logger = logging.getLogger("api.index")

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# --------------------------------------------------------------------------- #
# Rate limiting                                                                #
# --------------------------------------------------------------------------- #

_RATE_WINDOW_S = 60.0
_RATE_MAX_START = 5  # max indexing starts per minute

_start_timestamps: deque[float] = deque()


def _check_rate_limit() -> None:
    """Raise HTTP 429 if too many indexing requests in the sliding window."""
    now = time.monotonic()
    while _start_timestamps and _start_timestamps[0] < now - _RATE_WINDOW_S:
        _start_timestamps.popleft()
    if len(_start_timestamps) >= _RATE_MAX_START:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Zu viele Indexierungs-Anfragen. "
                f"Maximal {_RATE_MAX_START} pro Minute erlaubt."
            ),
        )
    _start_timestamps.append(now)


# --------------------------------------------------------------------------- #
# UI page                                                                      #
# --------------------------------------------------------------------------- #

@router.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Render the indexer UI page."""
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "page_title": "Indexer -- Ordner lernen"},
    )


# --------------------------------------------------------------------------- #
# Native macOS folder picker                                                   #
# --------------------------------------------------------------------------- #

@router.post("/pick-folder")
async def pick_folder() -> dict[str, str | None]:
    """
    Open native macOS folder dialog via osascript; return chosen path.
    Returns {"path": "/chosen/path"} or {"path": null} if cancelled.
    """
    script = (
        'tell application "System Events"\n'
        '  activate\n'
        '  set chosenFolder to choose folder with prompt '
        '"Muster-Ordner zum Lernen auswaehlen:"\n'
        '  return POSIX path of chosenFolder\n'
        'end tell'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            chosen = result.stdout.strip().rstrip("/")
            p = Path(chosen).resolve()
            if p.is_dir():
                return {"path": str(p)}
        return {"path": None}
    except subprocess.TimeoutExpired:
        return {"path": None}
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Ordner-Dialog konnte nicht geoeffnet werden.",
        )


# --------------------------------------------------------------------------- #
# Start indexing                                                               #
# --------------------------------------------------------------------------- #

@router.post("/start")
async def start_indexing(
    body: IndexRequest,
    background_tasks: BackgroundTasks,
) -> IndexStatus:
    """
    Validate folder path, launch background indexing task.
    Returns current status immediately so the UI can start polling.
    """
    _check_rate_limit()

    source = Path(body.folder_path) if isinstance(body.folder_path, str) else body.folder_path

    # BUG-2 fix: validate path BEFORE checking running state so that invalid
    # paths always get a 400/403, even when another indexing run is in progress.
    if not source.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Pfad existiert nicht: {source}",
        )
    if not source.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Pfad ist kein Ordner: {source}",
        )
    try:
        list(source.iterdir())
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail=f"Keine Leseberechtigung fuer: {source}",
        )

    # Check if indexing is already running (after path validation)
    current = get_index_status()
    if current.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Eine Indexierung laeuft bereits. Bitte warten.",
        )

    # BUG-1 fix: set status to 'running' synchronously before queuing the task
    # so the very first poll already returns the correct state.
    mark_status_running()
    background_tasks.add_task(scan_and_profile, source)

    return get_index_status()


# --------------------------------------------------------------------------- #
# Poll indexing status                                                         #
# --------------------------------------------------------------------------- #

@router.get("/status")
async def get_status() -> IndexStatus:
    """Short-polling endpoint for indexing progress (called every 2s by UI)."""
    return get_index_status()


# --------------------------------------------------------------------------- #
# List profiles                                                                #
# --------------------------------------------------------------------------- #

@router.get("/profiles")
async def list_profiles() -> list[FolderProfile]:
    """Return all learned folder profiles from the database."""
    return await get_all_profiles()


# --------------------------------------------------------------------------- #
# Delete profile                                                               #
# --------------------------------------------------------------------------- #

@router.delete("/profiles/{profile_id}")
async def remove_profile(profile_id: int):
    """Remove a single folder profile from the database."""
    deleted = await delete_profile(profile_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Profil mit ID {profile_id} nicht gefunden.",
        )
    return {"ok": True, "deleted_id": profile_id}


# --------------------------------------------------------------------------- #
# YAML export                                                                  #
# --------------------------------------------------------------------------- #

@router.get("/export-yaml")
async def export_yaml():
    """
    Generate a PROJ-2-compatible structure_rules.yaml and return it
    as a downloadable file.
    """
    yaml_content = await generate_yaml_from_profiles()

    if not yaml_content.strip() or yaml_content.strip() == "rules: []":
        raise HTTPException(
            status_code=404,
            detail="Keine Profile vorhanden. Bitte zuerst einen Ordner indexieren.",
        )

    return Response(
        content=yaml_content,
        media_type="application/x-yaml",
        headers={
            "Content-Disposition": 'attachment; filename="structure_rules.yaml"',
        },
    )
