"""
Database connection and schema initialisation.
Uses aiosqlite with WAL mode for non-blocking concurrent reads.

Schema overview:
  scans           – PROJ-1: scan sessions (one per user-initiated scan)
  scan_files      – PROJ-1: individual files found during a scan
  folder_profiles – PROJ-4: learned folder characteristics (semantic learner)
  operation_log   – PROJ-2 + PROJ-3 + PROJ-9: central audit log for every
                    move/rename; is the source-of-truth for undo/rollback
  ai_cache        – PROJ-8: caches LLM responses keyed by file hash
  settings        – PROJ-6: key/value store for AI provider config
"""
import aiosqlite
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path("data/filemanager.db")


async def get_db() -> aiosqlite.Connection:
    """Return an open aiosqlite connection with WAL mode enabled."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db() -> None:
    """Create all tables on first startup (idempotent – uses IF NOT EXISTS)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")

        # ------------------------------------------------------------------ #
        # PROJ-1: Verzeichnis-Scanner                                         #
        # ------------------------------------------------------------------ #
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id     TEXT    NOT NULL UNIQUE,   -- UUID v4
                source_path TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'running',
                                    -- 'running' | 'completed' | 'failed'
                file_count  INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL            -- ISO-8601 datetime
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS scan_files (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id        TEXT    NOT NULL REFERENCES scans(scan_id)
                                        ON DELETE CASCADE,
                name           TEXT    NOT NULL,
                path           TEXT    NOT NULL,        -- absolute path
                size_bytes     INTEGER NOT NULL DEFAULT 0,
                mime_type      TEXT,
                created_at     TEXT,                   -- ISO-8601
                modified_at    TEXT,                   -- ISO-8601
                is_symlink     INTEGER NOT NULL DEFAULT 0,  -- 0/1 boolean
                access_denied  INTEGER NOT NULL DEFAULT 0   -- 0/1 boolean
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_files_scan_id
                ON scan_files(scan_id)
        """)

        # ------------------------------------------------------------------ #
        # PROJ-4: Semantischer Struktur-Lerner                                #
        # ------------------------------------------------------------------ #
        await db.execute("""
            CREATE TABLE IF NOT EXISTS folder_profiles (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path       TEXT    NOT NULL UNIQUE,  -- absolute path
                primary_extension TEXT,                     -- e.g. '.pdf'
                ai_description    TEXT,                     -- LLM summary
                keywords          TEXT    NOT NULL DEFAULT '[]',
                                          -- JSON array, e.g. '["steuer","pdf"]'
                file_count        INTEGER NOT NULL DEFAULT 0,
                indexed_at        TEXT    NOT NULL           -- ISO-8601
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_folder_profiles_path
                ON folder_profiles(folder_path)
        """)

        # ------------------------------------------------------------------ #
        # PROJ-2 + PROJ-3 + PROJ-9: Central Operation Log                    #
        #                                                                     #
        # Every move AND rename writes one row here.                          #
        # batch_id groups all files from a single user-triggered action.      #
        # PROJ-9 reads this table to power the undo/rollback UI.              #
        # ------------------------------------------------------------------ #
        await db.execute("""
            CREATE TABLE IF NOT EXISTS operation_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id        TEXT    NOT NULL,            -- UUID v4
                operation_type  TEXT    NOT NULL,            -- 'MOVE' | 'RENAME'
                source_path     TEXT    NOT NULL,            -- absolute path before
                target_path     TEXT    NOT NULL,            -- absolute path after
                timestamp       TEXT    NOT NULL,            -- ISO-8601
                status          TEXT    NOT NULL DEFAULT 'completed',
                                        -- 'completed' | 'reverted' | 'revert_failed'
                mode            TEXT                         -- 'fast' | 'smart' | NULL
            )
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_operation_log_batch_id
                ON operation_log(batch_id)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_operation_log_status
                ON operation_log(status)
        """)

        # ------------------------------------------------------------------ #
        # PROJ-8: Deep-AI Smart Sorting – LLM response cache                 #
        # ------------------------------------------------------------------ #
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ai_cache (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                file_hash        TEXT    NOT NULL UNIQUE,    -- SHA-256 hex
                suggested_folder TEXT    NOT NULL,
                reasoning        TEXT,
                model_used       TEXT,
                created_at       TEXT    NOT NULL            -- ISO-8601
            )
        """)

        # ------------------------------------------------------------------ #
        # PROJ-6: KI-Integrations-Schicht – Settings                         #
        #                                                                     #
        # Key/value store. API keys are stored here only as references;       #
        # actual secrets live in .env or macOS Keychain.                      #
        # ------------------------------------------------------------------ #
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key        TEXT NOT NULL PRIMARY KEY,
                value      TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL            -- ISO-8601
            )
        """)

        await db.commit()


async def cleanup_old_scans(days: int = 30) -> int:
    """
    Delete scan records (and their files via CASCADE) older than `days` days.
    Called once on startup to prevent unbounded DB growth (BUG-6).
    Returns the number of deleted scan records.
    """
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        cursor = await db.execute(
            "DELETE FROM scans WHERE created_at < ?",
            (cutoff,),
        )
        await db.commit()
        return cursor.rowcount
