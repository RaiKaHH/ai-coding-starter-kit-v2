"""
PROJ-9: Undo / Rollback -- Business Logic.

Responsibilities:
- Read operation_log from DB (single op or full batch)
- LIFO ordering for batch undos
- Pre-flight checks before each operation:
    1. target_path still exists (file not deleted)
    2. source_path is free (no collision) -- prompt UI if blocked
    3. Volume / mount point still available (os.path.exists on parent)
- Execute reverse operation via shutil.move()
- Create missing source directories with os.makedirs
- Update operation_log.status: 'reverted' | 'revert_failed'
- Partial batch failure: log failed item, continue remaining ops
"""
import asyncio
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from models.history import OperationLog, UndoResult
from utils.db import get_db


# --------------------------------------------------------------------------- #
# In-memory progress tracker for async batch undos                            #
# --------------------------------------------------------------------------- #

_undo_progress: dict[str, dict[str, Any]] = {}

# TTL in seconds for completed progress entries
_PROGRESS_TTL_SECONDS = 300  # 5 minutes


def _cleanup_stale_progress() -> None:
    """Remove progress entries that finished more than TTL seconds ago."""
    now = time.monotonic()
    stale_keys = [
        key
        for key, val in _undo_progress.items()
        if val.get("done") and now - val.get("_finished_at", now) > _PROGRESS_TTL_SECONDS
    ]
    for key in stale_keys:
        del _undo_progress[key]


def get_undo_progress() -> dict[str, dict[str, Any]]:
    """Return the global undo progress store (with stale entry cleanup)."""
    _cleanup_stale_progress()
    return _undo_progress


# --------------------------------------------------------------------------- #
# DB helpers                                                                   #
# --------------------------------------------------------------------------- #

async def _get_operation_by_id(db: aiosqlite.Connection, operation_id: int) -> dict | None:
    """Fetch a single operation_log row by id."""
    cursor = await db.execute(
        "SELECT id, batch_id, operation_type, source_path, target_path, "
        "timestamp, status, mode FROM operation_log WHERE id = ?",
        (operation_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "operation_type": row["operation_type"],
        "source_path": row["source_path"],
        "target_path": row["target_path"],
        "timestamp": row["timestamp"],
        "status": row["status"],
        "mode": row["mode"],
    }


async def _get_batch_operations(
    db: aiosqlite.Connection, batch_id: str
) -> list[dict]:
    """Fetch all completed operations for a batch, ordered LIFO (newest first)."""
    cursor = await db.execute(
        "SELECT id, batch_id, operation_type, source_path, target_path, "
        "timestamp, status, mode FROM operation_log "
        "WHERE batch_id = ? AND status = 'completed' "
        "ORDER BY id DESC",
        (batch_id,),
    )
    rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "batch_id": row["batch_id"],
            "operation_type": row["operation_type"],
            "source_path": row["source_path"],
            "target_path": row["target_path"],
            "timestamp": row["timestamp"],
            "status": row["status"],
            "mode": row["mode"],
        }
        for row in rows
    ]


async def _update_status(
    db: aiosqlite.Connection, operation_id: int, new_status: str
) -> None:
    """Update the status field of an operation_log row."""
    await db.execute(
        "UPDATE operation_log SET status = ? WHERE id = ?",
        (new_status, operation_id),
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Pre-flight checks                                                            #
# --------------------------------------------------------------------------- #

def _preflight_check(op: dict) -> tuple[bool, str, int]:
    """
    Run pre-flight checks before reverting an operation.

    Returns (ok, error_message, http_status_code).
    If ok is True, error_message is empty and http_status_code is 0.
    """
    target = Path(op["target_path"])
    source = Path(op["source_path"])

    # Check 1: Is the operation already reverted?
    if op["status"] == "reverted":
        return False, "Operation wurde bereits rueckgaengig gemacht.", 400

    if op["status"] == "revert_failed":
        return False, "Operation ist bereits als fehlgeschlagen markiert.", 400

    if op["status"] != "completed":
        return False, f"Ungueltiger Status: {op['status']}", 400

    # Check 2: Does the file still exist at the target path?
    if not target.exists():
        return (
            False,
            f"Datei nicht mehr vorhanden am Zielort: {target}",
            409,
        )

    # Check 3: Is the source path free?
    if source.exists():
        return (
            False,
            f"Datei existiert bereits am Ursprungsort: {source}",
            409,
        )

    # Check 4: Is the volume/mount point still accessible?
    # We check that the root of the target path is accessible.
    # For macOS /Volumes/* paths, verify the mount is available.
    target_parts = target.parts
    if len(target_parts) >= 3 and target_parts[1] == "Volumes":
        volume_root = Path("/") / target_parts[1] / target_parts[2]
        if not volume_root.exists():
            return (
                False,
                f"Laufwerk nicht erreichbar: {volume_root}",
                503,
            )

    source_parts = source.parts
    if len(source_parts) >= 3 and source_parts[1] == "Volumes":
        volume_root = Path("/") / source_parts[1] / source_parts[2]
        if not volume_root.exists():
            return (
                False,
                f"Laufwerk nicht erreichbar: {volume_root}",
                503,
            )

    return True, "", 0


# --------------------------------------------------------------------------- #
# Single undo                                                                  #
# --------------------------------------------------------------------------- #

async def undo_single_operation(operation_id: int) -> tuple[UndoResult, int]:
    """
    Revert a single operation.

    Returns (UndoResult, http_status_code).
    """
    db = await get_db()
    try:
        op = await _get_operation_by_id(db, operation_id)
        if op is None:
            return UndoResult(
                success=False,
                message=f"Operation {operation_id} nicht gefunden.",
            ), 404

        # Pre-flight checks (run sync I/O in thread to avoid blocking event loop)
        ok, error_msg, status_code = await asyncio.to_thread(_preflight_check, op)
        if not ok:
            # If file is gone, mark as revert_failed
            if status_code == 409 and "nicht mehr vorhanden" in error_msg:
                await _update_status(db, operation_id, "revert_failed")
            return UndoResult(
                success=False,
                message=error_msg,
                errors=[error_msg],
            ), status_code

        # Create source directory if it no longer exists
        source = Path(op["source_path"])
        target = Path(op["target_path"])
        await asyncio.to_thread(source.parent.mkdir, parents=True, exist_ok=True)

        # Execute the reverse move (in thread to avoid blocking event loop)
        try:
            await asyncio.to_thread(shutil.move, str(target), str(source))
        except Exception as exc:
            await _update_status(db, operation_id, "revert_failed")
            error = f"Fehler beim Rueckgaengigmachen: {exc}"
            return UndoResult(
                success=False,
                message=error,
                errors=[error],
            ), 500

        # Update status
        await _update_status(db, operation_id, "reverted")

        return UndoResult(
            success=True,
            message=f"Erfolgreich rueckgaengig gemacht: {source.name}",
            reverted_count=1,
        ), 200

    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# Batch undo (runs as BackgroundTask)                                          #
# --------------------------------------------------------------------------- #

async def undo_batch_operations(batch_id: str) -> None:
    """
    Revert all completed operations in a batch using LIFO order.

    This function is designed to run as a FastAPI BackgroundTask.
    Progress is tracked in _undo_progress for polling.
    """
    db = await get_db()
    try:
        operations = await _get_batch_operations(db, batch_id)

        progress = {
            "batch_id": batch_id,
            "total": len(operations),
            "reverted": 0,
            "failed": 0,
            "done": False,
            "errors": [],
        }
        _undo_progress[batch_id] = progress

        if not operations:
            progress["done"] = True
            progress["_finished_at"] = time.monotonic()
            progress["errors"].append(
                "Keine rueckgaengig machbaren Operationen in diesem Batch."
            )
            return

        for op in operations:
            # Pre-flight checks (sync I/O in thread)
            ok, error_msg, _ = await asyncio.to_thread(_preflight_check, op)
            if not ok:
                # Mark as failed but continue with the rest
                if op["status"] == "completed":
                    await _update_status(db, op["id"], "revert_failed")
                progress["failed"] += 1
                progress["errors"].append(
                    f"{Path(op['target_path']).name}: {error_msg}"
                )
                continue

            source = Path(op["source_path"])
            target = Path(op["target_path"])

            # Create source directory if needed
            await asyncio.to_thread(source.parent.mkdir, parents=True, exist_ok=True)

            try:
                await asyncio.to_thread(shutil.move, str(target), str(source))
                await _update_status(db, op["id"], "reverted")
                progress["reverted"] += 1
            except Exception as exc:
                await _update_status(db, op["id"], "revert_failed")
                progress["failed"] += 1
                progress["errors"].append(
                    f"{Path(op['target_path']).name}: {exc}"
                )

        progress["done"] = True
        progress["_finished_at"] = time.monotonic()

    except Exception as exc:
        if batch_id in _undo_progress:
            _undo_progress[batch_id]["done"] = True
            _undo_progress[batch_id]["_finished_at"] = time.monotonic()
            _undo_progress[batch_id]["errors"].append(
                f"Unerwarteter Fehler: {exc}"
            )
    finally:
        await db.close()
