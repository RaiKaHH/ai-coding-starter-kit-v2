"""
PROJ-1: Verzeichnis-Scanner -- Business Logic.

Responsibilities:
- Recursively walk a directory with pathlib.Path
- Collect file metadata (size, mime, timestamps, symlinks, permissions)
- Persist results to scan_files table via aiosqlite
- Report progress via scan status updates
"""
import asyncio
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from utils.db import get_db


# --------------------------------------------------------------------------- #
# Data structures                                                              #
# --------------------------------------------------------------------------- #

class FileInfo:
    """Lightweight container for a single file's metadata."""
    __slots__ = (
        "name", "path", "size_bytes", "mime_type",
        "created_at", "modified_at", "is_symlink", "access_denied",
    )

    def __init__(
        self,
        name: str,
        path: str,
        size_bytes: int = 0,
        mime_type: str | None = None,
        created_at: str | None = None,
        modified_at: str | None = None,
        is_symlink: bool = False,
        access_denied: bool = False,
    ):
        self.name = name
        self.path = path
        self.size_bytes = size_bytes
        self.mime_type = mime_type
        self.created_at = created_at
        self.modified_at = modified_at
        self.is_symlink = is_symlink
        self.access_denied = access_denied


# --------------------------------------------------------------------------- #
# MIME type detection                                                          #
# --------------------------------------------------------------------------- #

# Try python-magic for accurate detection; fall back to mimetypes stdlib
try:
    import magic as _magic
    _HAS_MAGIC = True
except ImportError:
    _HAS_MAGIC = False


def _detect_mime(file_path: Path) -> str | None:
    """Return the MIME type of a file, or None on failure."""
    if _HAS_MAGIC:
        try:
            return _magic.from_file(str(file_path), mime=True)
        except Exception:
            pass
    # Fallback to stdlib
    guessed, _ = mimetypes.guess_type(str(file_path))
    return guessed


# --------------------------------------------------------------------------- #
# Timestamp helpers                                                            #
# --------------------------------------------------------------------------- #

def _ts_to_iso(ts: float) -> str:
    """Convert a POSIX timestamp to ISO-8601 string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _get_creation_time(stat_result: os.stat_result) -> float:
    """macOS stores real creation time in st_birthtime."""
    return getattr(stat_result, "st_birthtime", stat_result.st_ctime)


# --------------------------------------------------------------------------- #
# Directory scanning                                                           #
# --------------------------------------------------------------------------- #

async def collect_file_info(
    entry: Path,
    relative_to: Path | None = None,
) -> FileInfo:
    """
    Gather metadata for a single file/symlink.
    Runs stat and MIME detection in a thread to avoid blocking the event loop.

    If relative_to is provided the stored path is relative to that root (BUG-1).
    """
    is_symlink = entry.is_symlink()

    # BUG-1: store path relative to the scanned root, not the absolute path
    if relative_to is not None:
        try:
            display_path = str(entry.relative_to(relative_to))
        except ValueError:
            display_path = str(entry)  # fallback: absolute
    else:
        display_path = str(entry)

    try:
        # Use lstat for symlinks so we don't follow them
        stat = await asyncio.to_thread(os.lstat if is_symlink else os.stat, entry)
        mime = await asyncio.to_thread(_detect_mime, entry) if not is_symlink else None
        return FileInfo(
            name=entry.name,
            path=display_path,
            size_bytes=stat.st_size,
            mime_type=mime,
            created_at=_ts_to_iso(_get_creation_time(stat)),
            modified_at=_ts_to_iso(stat.st_mtime),
            is_symlink=is_symlink,
            access_denied=False,
        )
    except PermissionError:
        return FileInfo(
            name=entry.name,
            path=display_path,
            access_denied=True,
            is_symlink=is_symlink,
        )
    except OSError:
        return FileInfo(
            name=entry.name,
            path=display_path,
            access_denied=True,
            is_symlink=is_symlink,
        )


def _walk_directory(root: Path, recursive: bool) -> list[Path]:
    """
    Synchronous directory walk (runs in thread pool).
    Collects all file paths. Symlinks are included but NOT followed recursively.
    Directories that cannot be read are silently skipped.
    """
    files: list[Path] = []
    if recursive:
        try:
            for item in root.rglob("*"):
                if item.is_file() or item.is_symlink():
                    files.append(item)
        except PermissionError:
            pass
    else:
        try:
            for item in root.iterdir():
                if item.is_file() or item.is_symlink():
                    files.append(item)
        except PermissionError:
            pass
    return files


async def scan_directory(
    scan_id: str,
    source_path: Path,
    recursive: bool = True,
) -> None:
    """
    Main scan coroutine. Called as a BackgroundTask.

    1. Walk directory to discover all file paths (in thread)
    2. Collect metadata for each file in batches
    3. Persist batches to SQLite
    4. Update scan status on completion / failure
    """
    db = await get_db()
    try:
        # Step 1: discover files (offloaded to thread pool)
        all_paths = await asyncio.to_thread(_walk_directory, source_path, recursive)
        total = len(all_paths)

        # BUG-2: persist total_count immediately so polling UI can show real %
        await db.execute(
            "UPDATE scans SET total_count = ? WHERE scan_id = ?",
            (total, scan_id),
        )
        await db.commit()

        # Step 2+3: process in batches of 200 for good DB throughput
        BATCH_SIZE = 200
        processed = 0

        for batch_start in range(0, total, BATCH_SIZE):
            batch_paths = all_paths[batch_start:batch_start + BATCH_SIZE]

            # Gather metadata concurrently within batch (BUG-1: pass root for relative paths)
            infos = await asyncio.gather(
                *(collect_file_info(p, relative_to=source_path) for p in batch_paths)
            )

            # Insert batch into DB
            await db.executemany(
                """
                INSERT INTO scan_files
                    (scan_id, name, path, size_bytes, mime_type,
                     created_at, modified_at, is_symlink, access_denied)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        scan_id,
                        fi.name,
                        fi.path,
                        fi.size_bytes,
                        fi.mime_type,
                        fi.created_at,
                        fi.modified_at,
                        1 if fi.is_symlink else 0,
                        1 if fi.access_denied else 0,
                    )
                    for fi in infos
                ],
            )

            processed += len(infos)

            # Update file_count for progress polling
            await db.execute(
                "UPDATE scans SET file_count = ? WHERE scan_id = ?",
                (processed, scan_id),
            )
            await db.commit()

        # Mark completed
        await db.execute(
            "UPDATE scans SET status = 'completed', file_count = ? WHERE scan_id = ?",
            (processed, scan_id),
        )
        await db.commit()

    except Exception as exc:
        # Mark failed and store error hint
        try:
            await db.execute(
                "UPDATE scans SET status = 'failed' WHERE scan_id = ?",
                (scan_id,),
            )
            await db.commit()
        except Exception:
            pass
        raise exc
    finally:
        await db.close()
