"""
API routes for PROJ-1: Verzeichnis-Scanner.

Endpoints:
  POST /scan/start           -- kick off async scan, returns scan_id
  GET  /scan/{scan_id}/status -- polling endpoint for progress
  GET  /scan/{scan_id}/files  -- paginated file list with optional filters
  POST /scan/pick-folder      -- open native macOS folder picker dialog
  GET  /scan/                  -- Scanner UI page
"""
import asyncio
import subprocess
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.analyzer import scan_directory
from models.scan import (
    ScanFile,
    ScanFilterParams,
    ScanRequest,
    ScanResult,
    ScanStatus,
)
from utils.db import get_db

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --------------------------------------------------------------------------- #
# Resource limits (BUG-4: rate limiting, BUG-6: concurrency + DB growth)      #
# --------------------------------------------------------------------------- #

_MAX_SCANS_PER_MINUTE = 5   # max POST /scan/start calls in a 60-second window
_MAX_CONCURRENT_SCANS = 3   # max simultaneously running scans

_rate_window: deque[float] = deque()  # timestamps of recent scan starts
_rate_lock = asyncio.Lock()


async def _check_rate_limit() -> None:
    """Sliding-window rate limiter: max _MAX_SCANS_PER_MINUTE per 60 seconds."""
    async with _rate_lock:
        now = time.monotonic()
        while _rate_window and now - _rate_window[0] > 60:
            _rate_window.popleft()
        if len(_rate_window) >= _MAX_SCANS_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Zu viele Scan-Anfragen. "
                    f"Maximal {_MAX_SCANS_PER_MINUTE} Scans pro Minute erlaubt."
                ),
            )
        _rate_window.append(now)


async def _check_concurrent_scans(db) -> None:
    """Reject new scan if _MAX_CONCURRENT_SCANS are already running."""
    cursor = await db.execute(
        "SELECT COUNT(*) FROM scans WHERE status = 'running'"
    )
    running = (await cursor.fetchone())[0]
    if running >= _MAX_CONCURRENT_SCANS:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Zu viele gleichzeitige Scans (max. {_MAX_CONCURRENT_SCANS}). "
                "Bitte warte, bis ein laufender Scan abgeschlossen ist."
            ),
        )


# --------------------------------------------------------------------------- #
# UI page                                                                      #
# --------------------------------------------------------------------------- #

@router.get("/", response_class=HTMLResponse)
async def scan_page(request: Request):
    """Render the scanner UI."""
    return templates.TemplateResponse("scan.html", {
        "request": request,
        "page_title": "Verzeichnis-Scanner",
    })


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
        '  set chosenFolder to choose folder with prompt "Ordner zum Scannen auswaehlen:"\n'
        '  return POSIX path of chosenFolder\n'
        'end tell'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=120,  # user might take time to pick
        )
        if result.returncode == 0 and result.stdout.strip():
            chosen = result.stdout.strip().rstrip("/")
            # Validate the returned path
            p = Path(chosen).resolve()
            if p.is_dir():
                return {"path": str(p)}
        return {"path": None}
    except subprocess.TimeoutExpired:
        return {"path": None}
    except Exception:
        raise HTTPException(status_code=500, detail="Ordner-Dialog konnte nicht geoeffnet werden.")


# --------------------------------------------------------------------------- #
# Start scan                                                                   #
# --------------------------------------------------------------------------- #

@router.post("/start")
async def start_scan(body: ScanRequest, background_tasks: BackgroundTasks) -> ScanStatus:
    """
    Validate path, create scan record, launch background scan.
    Returns the scan status immediately so the UI can start polling.
    """
    # Rate limiting and concurrency checks (BUG-4, BUG-6)
    await _check_rate_limit()

    source = Path(body.source_path) if isinstance(body.source_path, str) else body.source_path

    # Validate the directory exists and is accessible
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Pfad existiert nicht: {source}")
    if not source.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Pfad ist kein Ordner (sondern eine Datei): {source}",
        )
    try:
        # Quick read test
        list(source.iterdir())
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail=f"Keine Leseberechtigung fuer: {source}",
        )

    scan_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    db = await get_db()
    try:
        await _check_concurrent_scans(db)  # BUG-6: concurrent scan limit

        await db.execute(
            """
            INSERT INTO scans (scan_id, source_path, status, file_count, created_at)
            VALUES (?, ?, 'running', 0, ?)
            """,
            (scan_id, str(source), now),
        )
        await db.commit()
    finally:
        await db.close()

    # Launch the scan in the background
    background_tasks.add_task(scan_directory, scan_id, source, body.recursive)

    return ScanStatus(
        scan_id=scan_id,
        status="running",
        file_count=0,
        total_count=0,
        source_path=str(source),
        created_at=now,
    )


# --------------------------------------------------------------------------- #
# Poll scan status                                                             #
# --------------------------------------------------------------------------- #

@router.get("/{scan_id}/status")
async def get_scan_status(scan_id: str) -> ScanStatus:
    """Return current scan progress (status + file_count)."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT scan_id, status, file_count, total_count, source_path, created_at "
            "FROM scans WHERE scan_id = ?",
            (scan_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Scan nicht gefunden: {scan_id}")
        return ScanStatus(
            scan_id=row["scan_id"],
            status=row["status"],
            file_count=row["file_count"],
            total_count=row["total_count"] or 0,
            source_path=row["source_path"],
            created_at=row["created_at"],
        )
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# Get scan files (with filtering, sorting, pagination)                         #
# --------------------------------------------------------------------------- #

@router.get("/{scan_id}/files")
async def get_scan_files(
    scan_id: str,
    extension: str | None = Query(None, description="Filter by extension, e.g. '.pdf'"),
    date_from: str | None = Query(None, description="Created after (ISO-8601)"),
    date_to: str | None = Query(None, description="Created before (ISO-8601)"),
    sort_by: str = Query("name", regex="^(name|size|type|created_at|modified_at)$"),
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
) -> ScanResult:
    """Return paginated, filtered, sorted file list for a completed scan."""
    db = await get_db()
    try:
        # Verify scan exists
        cursor = await db.execute(
            "SELECT scan_id, status, file_count FROM scans WHERE scan_id = ?",
            (scan_id,),
        )
        scan_row = await cursor.fetchone()
        if not scan_row:
            raise HTTPException(status_code=404, detail=f"Scan nicht gefunden: {scan_id}")

        # Build dynamic WHERE clause
        conditions = ["scan_id = ?"]
        params: list = [scan_id]

        if extension:
            ext = extension if extension.startswith(".") else f".{extension}"
            conditions.append("name LIKE ?")
            params.append(f"%{ext}")

        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to)

        where_clause = " AND ".join(conditions)

        # Map sort_by to actual column names
        sort_column_map = {
            "name": "name",
            "size": "size_bytes",
            "type": "mime_type",
            "created_at": "created_at",
            "modified_at": "modified_at",
        }
        order_col = sort_column_map.get(sort_by, "name")
        order_dir = "ASC" if sort_order == "asc" else "DESC"

        # Count total filtered results
        count_cursor = await db.execute(
            f"SELECT COUNT(*) FROM scan_files WHERE {where_clause}",
            params,
        )
        total_filtered = (await count_cursor.fetchone())[0]

        # Fetch page
        offset = (page - 1) * page_size
        file_cursor = await db.execute(
            f"""
            SELECT id, scan_id, name, path, size_bytes, mime_type,
                   created_at, modified_at, is_symlink, access_denied
            FROM scan_files
            WHERE {where_clause}
            ORDER BY {order_col} {order_dir}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        )
        rows = await file_cursor.fetchall()

        files = [
            ScanFile(
                id=r["id"],
                scan_id=r["scan_id"],
                name=r["name"],
                path=r["path"],
                size_bytes=r["size_bytes"],
                mime_type=r["mime_type"],
                created_at=r["created_at"],
                modified_at=r["modified_at"],
                is_symlink=bool(r["is_symlink"]),
                access_denied=bool(r["access_denied"]),
            )
            for r in rows
        ]

        return ScanResult(
            scan_id=scan_id,
            status=scan_row["status"],
            file_count=scan_row["file_count"],
            files=files,
            page=page,
            page_size=page_size,
            total_filtered=total_filtered,
        )
    finally:
        await db.close()
