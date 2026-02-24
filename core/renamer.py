"""
PROJ-3: KI-gestuetzter Datei-Umbenenner -- Business Logic.

Responsibilities:
- Fast mode: extract date from EXIF / OS metadata, keep base name
- Smart mode:
    - Extract text via utils/text_extractor.py (max 2000 chars)
    - Call ai_service.ask_json() for date + filename extraction
    - Validate AI JSON response (Pydantic AIRenameResult)
    - Fallback chain: AI date -> EXIF date -> OS ctime
- Build target filename: YYYY-MM-DD_snake_case_name.ext
- Sanitise AI-suggested names (only a-z, 0-9, -, _)
- Execute renames via shutil.move()
- Write every rename to operation_log with batch_id
- Concurrency: delegates to ai_service.py semaphore (no own semaphore)
"""
import asyncio
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

from models.ai_gateway import AIRenameResult
from models.rename import (
    RenameMode,
    RenamePreviewItem,
    RenamePreviewResponse,
)
from utils.db import get_db
from utils.text_extractor import extract_text

logger = logging.getLogger("renamer")


# --------------------------------------------------------------------------- #
# In-memory batch cache (single-user tool, acceptable trade-off)              #
# --------------------------------------------------------------------------- #

_batch_cache: dict[str, list[RenamePreviewItem]] = {}
_batch_status: dict[str, dict[str, Any]] = {}


def get_batch_cache() -> dict[str, list[RenamePreviewItem]]:
    """Return the global batch cache."""
    return _batch_cache


def get_batch_status_store() -> dict[str, dict[str, Any]]:
    """Return the global batch status store."""
    return _batch_status


# --------------------------------------------------------------------------- #
# Date extraction helpers                                                     #
# --------------------------------------------------------------------------- #

def _extract_exif_date(file_path: Path) -> str | None:
    """
    Extract date from EXIF metadata (photos).
    Returns YYYY-MM-DD string or None.
    """
    try:
        import exifread
        with open(file_path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="DateTimeOriginal", details=False)

        # Try DateTimeOriginal first, then DateTimeDigitized, then DateTime
        for tag_name in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
            tag_val = tags.get(tag_name)
            if tag_val:
                # EXIF format: "2024:03:15 14:30:00"
                dt_str = str(tag_val).strip()
                dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                return dt.strftime("%Y-%m-%d")
    except (ImportError, ValueError, KeyError, Exception):
        pass
    return None


def _extract_os_date(file_path: Path) -> str:
    """
    Extract creation date from OS file metadata.
    On macOS, st_birthtime is the actual creation date.
    Returns YYYY-MM-DD string (always succeeds).
    """
    stat = file_path.stat()
    # macOS: st_birthtime is creation date; Linux: fall back to mtime
    ctime = getattr(stat, "st_birthtime", stat.st_mtime)
    dt = datetime.fromtimestamp(ctime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _validate_date(date_str: str | None) -> str | None:
    """
    Validate a date string (YYYY-MM-DD).
    Returns the date string if valid and not in the future; None otherwise.
    """
    if not date_str:
        return None

    try:
        parsed = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None

    # Reject dates in the future
    if parsed > date.today():
        return None

    # Reject obviously wrong dates (before 1900)
    if parsed.year < 1900:
        return None

    return date_str


# --------------------------------------------------------------------------- #
# Filename sanitisation                                                       #
# --------------------------------------------------------------------------- #

def _sanitize_filename(name: str) -> str:
    """
    Sanitise an AI-suggested filename.
    Only allows: a-z, 0-9, -, _
    Converts to lowercase, replaces spaces with underscores.
    Strips leading/trailing underscores.
    Max 60 characters.
    """
    # Convert to lowercase
    name = name.lower().strip()
    # Replace common separators (including / : \ which AI may produce) with underscores
    name = name.replace(" ", "_").replace(".", "_").replace("-", "_")
    name = name.replace("/", "_").replace(":", "_").replace("\\", "_")
    # Remove everything except allowed chars
    name = re.sub(r"[^a-z0-9_]", "", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    # Truncate
    if len(name) > 60:
        name = name[:60].rstrip("_")
    return name or "unnamed"


def _build_target_filename(
    date_str: str,
    description: str,
    extension: str,
) -> str:
    """
    Build the final filename: YYYY-MM-DD_description.ext
    """
    clean_desc = _sanitize_filename(description)
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{date_str}_{clean_desc}{ext}"


# --------------------------------------------------------------------------- #
# Name collision resolution                                                   #
# --------------------------------------------------------------------------- #

def _resolve_name_conflict(target: Path) -> Path:
    """
    If target already exists, append _01, _02, ... until a free name is found.
    """
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 1

    while True:
        candidate = parent / f"{stem}_{counter:02d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
        if counter > 9999:
            raise OSError(f"Zu viele Namenskonflikte fuer: {target}")


# --------------------------------------------------------------------------- #
# Preview generation                                                          #
# --------------------------------------------------------------------------- #

async def generate_preview(
    scan_id: str,
    mode: RenameMode,
    file_ids: list[int],
) -> RenamePreviewResponse:
    """
    Generate a rename preview for the given files.

    Fast mode: uses EXIF/OS date, keeps original base name.
    Smart mode: uses AI to extract date and suggest descriptive name.

    Returns a RenamePreviewResponse with a batch_id for later execution.
    """
    # Load files from DB
    db = await get_db()
    try:
        if not file_ids:
            batch_id = str(uuid.uuid4())
            return RenamePreviewResponse(batch_id=batch_id, mode=mode, items=[])

        placeholders = ",".join("?" * len(file_ids))
        cursor = await db.execute(
            f"""
            SELECT id, name, path, created_at, mime_type
            FROM scan_files
            WHERE scan_id = ? AND id IN ({placeholders})
            """,
            [scan_id] + file_ids,
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    if not rows:
        batch_id = str(uuid.uuid4())
        return RenamePreviewResponse(batch_id=batch_id, mode=mode, items=[])

    # Generate preview items
    if mode == "smart":
        items = await _generate_smart_preview(rows)
    else:
        items = await _generate_fast_preview(rows)

    batch_id = str(uuid.uuid4())
    response = RenamePreviewResponse(
        batch_id=batch_id,
        mode=mode,
        items=items,
    )

    # Cache for later execution
    _batch_cache[batch_id] = items
    _batch_status[batch_id] = {
        "total": len(items),
        "renamed": 0,
        "failed": 0,
        "done": False,
        "errors": [],
    }

    return response


async def _generate_fast_preview(rows: list) -> list[RenamePreviewItem]:
    """
    Fast mode: use EXIF date -> OS date, keep original base name.
    """
    items: list[RenamePreviewItem] = []

    for row in rows:
        file_path = Path(row["path"])
        file_name = row["name"]
        extension = file_path.suffix

        # Date fallback chain: EXIF -> OS
        exif_date = _extract_exif_date(file_path) if file_path.exists() else None
        exif_date = _validate_date(exif_date)

        if exif_date:
            found_date = exif_date
            date_source = "exif"
        else:
            found_date = _extract_os_date(file_path) if file_path.exists() else None
            found_date = _validate_date(found_date) or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            date_source = "os"

        # Keep original name stem (sanitised)
        original_stem = file_path.stem
        clean_name = _sanitize_filename(original_stem)
        new_filename = _build_target_filename(found_date, clean_name, extension)

        items.append(RenamePreviewItem(
            scan_file_id=row["id"],
            current_name=file_name,
            found_date=found_date,
            date_source=date_source,
            ai_suggestion=None,
            new_filename=new_filename,
            editable=True,
        ))

    return items


async def _generate_smart_preview(rows: list) -> list[RenamePreviewItem]:
    """
    Smart mode: extract text, call AI, use date fallback chain.
    Processes files concurrently (limited by ai_service semaphore).
    """
    from core.ai_service import ask_json, AIServiceError

    async def _process_one(row: dict) -> RenamePreviewItem:
        file_path = Path(row["path"])
        file_name = row["name"]
        extension = file_path.suffix

        # Step 1: Extract text
        text, text_ok = await extract_text(file_path)

        ai_date: str | None = None
        ai_name: str | None = None
        date_source = "os"

        if text_ok and text.strip():
            # Step 2: Ask AI for date + descriptive name
            try:
                prompt = (
                    f"Analysiere den folgenden Dokumentinhalt und extrahiere:\n"
                    f"1. Das relevante Datum des Dokuments (z.B. Rechnungsdatum, Briefdatum, Erstellungsdatum) "
                    f"im Format YYYY-MM-DD.\n"
                    f"2. Einen kurzen, beschreibenden Dateinamen (max. 5 Woerter, snake_case, ohne Dateiendung). "
                    f"Beispiel: 'rechnung_telekom_internet' oder 'mietvertrag_hauptstrasse'.\n\n"
                    f"Dateiname: {file_name}\n"
                    f"Dokumentinhalt:\n{text}"
                )

                ai_result: AIRenameResult = await ask_json(
                    prompt=prompt,
                    response_model=AIRenameResult,
                    system_hint=(
                        "Du bist ein Dokumenten-Analyse-Assistent. "
                        "Extrahiere das Datum und einen beschreibenden Dateinamen. "
                        "Falls kein Datum erkennbar ist, setze datum auf einen leeren String."
                    ),
                )

                ai_date = _validate_date(ai_result.datum)
                ai_name = ai_result.dateiname

                if ai_date:
                    date_source = "ai"

            except AIServiceError as exc:
                logger.warning(
                    "AI-Analyse fehlgeschlagen fuer %s: %s",
                    file_name, exc,
                )

        # Step 3: Date fallback chain: AI -> EXIF -> OS
        found_date = ai_date

        if not found_date:
            exif_date = _extract_exif_date(file_path) if file_path.exists() else None
            exif_date = _validate_date(exif_date)
            if exif_date:
                found_date = exif_date
                date_source = "exif"

        if not found_date:
            found_date = _extract_os_date(file_path) if file_path.exists() else None
            found_date = _validate_date(found_date) or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            date_source = "os"

        # Step 4: Build target filename
        if ai_name:
            clean_name = _sanitize_filename(ai_name)
            ai_suggestion = ai_name
        else:
            # Fallback: use original filename stem
            clean_name = _sanitize_filename(file_path.stem)
            ai_suggestion = None

        new_filename = _build_target_filename(found_date, clean_name, extension)

        return RenamePreviewItem(
            scan_file_id=row["id"],
            current_name=file_name,
            found_date=found_date,
            date_source=date_source,
            ai_suggestion=ai_suggestion,
            new_filename=new_filename,
            editable=True,
        )

    # Process all files concurrently (ai_service.py caps at 3 parallel)
    tasks = [_process_one(dict(row)) for row in rows]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[RenamePreviewItem] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            # On unexpected error, create a fallback item
            row = rows[i]
            file_path = Path(row["path"])
            found_date = _extract_os_date(file_path) if file_path.exists() else datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            items.append(RenamePreviewItem(
                scan_file_id=row["id"],
                current_name=row["name"],
                found_date=found_date,
                date_source="os",
                ai_suggestion=None,
                new_filename=_build_target_filename(
                    found_date, _sanitize_filename(file_path.stem), file_path.suffix,
                ),
                editable=True,
            ))
            logger.error(
                "Fehler bei Smart-Vorschau fuer %s: %s",
                row["name"], result,
            )
        else:
            items.append(result)

    return items


# --------------------------------------------------------------------------- #
# Batch execution (runs as BackgroundTask)                                    #
# --------------------------------------------------------------------------- #

async def execute_batch(
    batch_id: str,
    items: list[dict[str, Any]],
    mode: RenameMode,
) -> None:
    """
    Execute the confirmed rename operations for a batch.

    This function is designed to run as a FastAPI BackgroundTask.
    It renames files via shutil.move, handles name conflicts,
    and logs every operation to operation_log.

    Args:
        batch_id: UUID identifying this batch.
        items: List of dicts with 'scan_file_id' and 'new_filename'.
        mode: 'fast' or 'smart' (stored in operation_log).
    """
    status = _batch_status.setdefault(batch_id, {
        "total": len(items),
        "renamed": 0,
        "failed": 0,
        "done": False,
        "errors": [],
    })
    status["total"] = len(items)
    status["renamed"] = 0
    status["failed"] = 0
    status["done"] = False
    status["errors"] = []

    # Build a map of scan_file_id -> new_filename from user input
    rename_map: dict[int, str] = {
        item["scan_file_id"]: item["new_filename"]
        for item in items
    }

    # Look up original paths from scan_files
    db = await get_db()
    try:
        ids = list(rename_map.keys())
        placeholders = ",".join("?" * len(ids))
        cursor = await db.execute(
            f"SELECT id, path FROM scan_files WHERE id IN ({placeholders})",
            ids,
        )
        file_rows = await cursor.fetchall()

        for row in file_rows:
            scan_file_id = row["id"]
            source = Path(row["path"])
            new_name = rename_map.get(scan_file_id)
            if not new_name:
                continue

            # Target: same directory, new filename
            target = source.parent / new_name
            actual_target = target
            op_status = "completed"

            try:
                if not source.exists():
                    raise FileNotFoundError(f"Quelldatei nicht mehr vorhanden: {source}")

                # Skip if source and target are the same
                if source.name == new_name:
                    status["renamed"] += 1
                    continue

                # Resolve name conflicts
                actual_target = _resolve_name_conflict(target)

                # Perform the rename
                shutil.move(str(source), str(actual_target))
                status["renamed"] += 1

            except FileNotFoundError as exc:
                op_status = "failed"
                status["failed"] += 1
                status["errors"].append(str(exc))
            except PermissionError:
                op_status = "failed"
                status["failed"] += 1
                status["errors"].append(
                    f"Keine Berechtigung: {source} -> {actual_target}"
                )
            except OSError as exc:
                op_status = "failed"
                status["failed"] += 1
                status["errors"].append(f"Fehler bei {source.name}: {exc}")

            # Log to operation_log
            now = datetime.now(tz=timezone.utc).isoformat()
            await db.execute(
                """
                INSERT INTO operation_log
                    (batch_id, operation_type, source_path, target_path,
                     timestamp, status, mode)
                VALUES (?, 'RENAME', ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    str(source),
                    str(actual_target),
                    now,
                    op_status,
                    mode,
                ),
            )
            await db.commit()

        status["done"] = True

    except Exception as exc:
        status["errors"].append(f"Unerwarteter Fehler: {exc}")
        status["done"] = True
        logger.error("Batch %s fehlgeschlagen: %s", batch_id, exc)
    finally:
        await db.close()

    # Clean up cache after execution
    _batch_cache.pop(batch_id, None)
