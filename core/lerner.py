"""
PROJ-4: Semantischer Struktur-Lerner -- Business Logic.

Responsibilities:
- Recursively scan a reference folder (pathlib)
- Aggregate per-subfolder statistics (collections.Counter for extensions + n-grams)
- Sample max 50 filenames per folder before sending to AI
- Call ai_service.ask_json() for folder profiling (AIFolderProfile response)
- Offline fallback: store only extension stats without AI description
- Persist results to folder_profiles table (INSERT OR REPLACE)
- Generate structure_rules.yaml from folder_profiles (PyYAML)
- Concurrency managed by ai_service.py semaphore (no own queue)
"""
import json
import logging
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.ai_service import AIServiceError, ask_json
from models.index import AIFolderProfile, FolderProfile, IndexStatus
from utils.db import get_db

logger = logging.getLogger("core.lerner")

# --------------------------------------------------------------------------- #
# In-memory indexing state (single-user tool)                                  #
# --------------------------------------------------------------------------- #

_index_status: dict[str, Any] = {
    "status": "idle",
    "processed_count": 0,
    "total_count": 0,
    "error": None,
}

_MAX_SAMPLE_FILENAMES = 50
_CHAOS_EXTENSION_THRESHOLD = 3  # more than this many distinct extensions = "mixed"


def get_index_status() -> IndexStatus:
    """Return current indexing progress for the polling endpoint."""
    return IndexStatus(
        status=_index_status["status"],
        processed_count=_index_status["processed_count"],
        total_count=_index_status["total_count"],
        error=_index_status.get("error"),
    )


def mark_status_running() -> None:
    """BUG-1: Pre-emptively set status to 'running' before the background task starts.
    Called synchronously in the route handler so the first polling response
    already reflects the new state."""
    _index_status["status"] = "running"
    _index_status["processed_count"] = 0
    _index_status["total_count"] = 0
    _index_status["error"] = None


# --------------------------------------------------------------------------- #
# Subfolder statistics                                                         #
# --------------------------------------------------------------------------- #

def _collect_subfolder_stats(folder: Path) -> dict[str, Any]:
    """
    Aggregate file statistics for a single folder (non-recursive within it).

    Returns dict with:
      - file_count: int
      - filenames: list[str]  (all filenames)
      - extension_counter: Counter  (lowercase extensions)
      - primary_extension: str | None
    """
    filenames: list[str] = []
    extension_counter: Counter = Counter()

    try:
        for item in folder.iterdir():
            if item.is_file() and not item.name.startswith("."):
                filenames.append(item.name)
                if item.suffix:
                    extension_counter[item.suffix.lower()] += 1
    except PermissionError:
        logger.warning("Keine Leseberechtigung fuer: %s", folder)

    primary_ext = extension_counter.most_common(1)[0][0] if extension_counter else None

    return {
        "file_count": len(filenames),
        "filenames": filenames,
        "extension_counter": extension_counter,
        "primary_extension": primary_ext,
    }


def _extract_name_tokens(filenames: list[str]) -> list[str]:
    """
    Extract common word tokens from filenames for n-gram analysis.
    Strips extensions, splits on common separators.
    """
    tokens: list[str] = []
    for name in filenames:
        stem = Path(name).stem
        # Split on common separators: -, _, ., spaces, camelCase boundaries
        parts = re.split(r"[-_.\s]+", stem)
        for part in parts:
            # Also split camelCase
            camel_parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).split()
            for token in camel_parts:
                clean = token.strip().lower()
                if clean and len(clean) > 1:
                    tokens.append(clean)
    return tokens


def _is_chaos_folder(extension_counter: Counter) -> bool:
    """Detect if a folder has too many mixed file types to be meaningful."""
    return len(extension_counter) > _CHAOS_EXTENSION_THRESHOLD


# --------------------------------------------------------------------------- #
# AI profiling                                                                 #
# --------------------------------------------------------------------------- #

async def _profile_folder_with_ai(
    folder_path: str,
    filenames: list[str],
    extension_counter: Counter,
) -> AIFolderProfile | None:
    """
    Send sampled filenames to the LLM for semantic profiling.
    Returns AIFolderProfile or None if AI is unavailable.
    """
    # Sample filenames to stay within token limits
    sample = filenames
    if len(filenames) > _MAX_SAMPLE_FILENAMES:
        sample = random.sample(filenames, _MAX_SAMPLE_FILENAMES)

    # Build informative prompt
    ext_summary = ", ".join(
        f"{ext} ({count}x)" for ext, count in extension_counter.most_common(5)
    )

    prompt = (
        f"Analysiere die folgenden Dateinamen aus dem Ordner '{folder_path}'.\n\n"
        f"Dateiendungen-Verteilung: {ext_summary}\n\n"
        f"Beispiel-Dateinamen:\n"
        + "\n".join(f"- {name}" for name in sample)
        + "\n\n"
        "Welchem Zweck dient dieser Ordner? "
        "Nenne den Zweck als kurzen Satz, bis zu 5 Keywords, "
        "und eine empfohlene Dateinamen-Regel (z.B. '*.pdf' oder 'RE-*.pdf')."
    )

    try:
        result = await ask_json(
            prompt=prompt,
            response_model=AIFolderProfile,
            system_hint=(
                "Du bist ein Dateiorganisations-Experte. "
                "Analysiere Dateinamen und erkenne Muster. "
                "Antworte NUR mit validem JSON."
            ),
        )
        return result
    except AIServiceError as exc:
        logger.warning(
            "KI nicht verfuegbar fuer Ordner %s: %s – nutze Fallback",
            folder_path,
            exc,
        )
        return None
    except Exception as exc:
        logger.error(
            "Unerwarteter Fehler bei KI-Profiling fuer %s: %s",
            folder_path,
            exc,
        )
        return None


# --------------------------------------------------------------------------- #
# Heuristic fallback (when AI is not available)                                #
# --------------------------------------------------------------------------- #

def _heuristic_keywords(filenames: list[str], extension_counter: Counter) -> list[str]:
    """
    Generate keywords from filename tokens and extensions without AI.
    Returns up to 5 keywords.
    """
    tokens = _extract_name_tokens(filenames)
    token_counter = Counter(tokens)

    # Take the 3 most common meaningful tokens
    keywords = [
        token for token, _ in token_counter.most_common(10)
        if len(token) > 2
    ][:3]

    # Add top extensions as keywords
    for ext, _ in extension_counter.most_common(2):
        keywords.append(ext.lstrip("."))

    return keywords[:5]


# --------------------------------------------------------------------------- #
# Main background task: scan_and_profile                                       #
# --------------------------------------------------------------------------- #

async def scan_and_profile(folder_path: Path) -> None:
    """
    Background task: recursively scan folder, profile each subfolder,
    persist results to folder_profiles table.

    Updates _index_status in-place for polling.
    Note: _index_status is already set to 'running' by mark_status_running()
    before this task is queued (BUG-1 fix).
    """
    _index_status["processed_count"] = 0
    _index_status["total_count"] = 0
    _index_status["error"] = None

    # BUG-3 fix: open a single DB connection for the entire scan instead of
    # opening/closing one per subfolder (avoids thousands of connection cycles).
    db = await get_db()
    try:
        # Step 1: Collect all subfolders (including root)
        subfolders: list[Path] = [folder_path]
        try:
            for item in folder_path.rglob("*"):
                if item.is_dir() and not item.name.startswith("."):
                    subfolders.append(item)
        except PermissionError:
            logger.warning("Eingeschraenkter Zugriff beim Scannen von: %s", folder_path)

        _index_status["total_count"] = len(subfolders)
        logger.info(
            "Indexierung gestartet: %s (%d Unterordner)",
            folder_path,
            len(subfolders),
        )

        # Step 2: Process each subfolder, reusing the shared DB connection
        for subfolder in subfolders:
            try:
                await _process_subfolder(subfolder, db)
            except Exception as exc:
                logger.error(
                    "Fehler beim Verarbeiten von %s: %s",
                    subfolder,
                    exc,
                )
            finally:
                _index_status["processed_count"] += 1

        _index_status["status"] = "completed"
        logger.info("Indexierung abgeschlossen: %s", folder_path)

    except Exception as exc:
        _index_status["status"] = "failed"
        _index_status["error"] = str(exc)
        logger.error("Indexierung fehlgeschlagen: %s – %s", folder_path, exc)
    finally:
        await db.close()


async def _process_subfolder(subfolder: Path, db) -> None:
    """Process a single subfolder: collect stats, profile, persist.

    Accepts a shared DB connection (BUG-3 fix: connection is managed by the
    caller scan_and_profile to avoid per-subfolder open/close overhead).
    """
    stats = _collect_subfolder_stats(subfolder)

    # Skip empty folders
    if stats["file_count"] == 0:
        return

    folder_str = str(subfolder)
    filenames = stats["filenames"]
    ext_counter = stats["extension_counter"]
    primary_ext = stats["primary_extension"]
    file_count = stats["file_count"]

    # Determine if this is a chaos folder
    is_chaos = _is_chaos_folder(ext_counter)

    if is_chaos:
        # Chaos folder: don't ask AI, just mark as mixed
        keywords = ["gemischt"]
        ai_description = "Gemischter Ordner mit vielen verschiedenen Dateitypen."
    else:
        # Try AI profiling
        ai_profile = await _profile_folder_with_ai(
            folder_str, filenames, ext_counter
        )

        if ai_profile:
            keywords = ai_profile.keywords[:5]
            ai_description = ai_profile.zweck
        else:
            # Heuristic fallback
            keywords = _heuristic_keywords(filenames, ext_counter)
            ai_description = None

    # Persist to database using the shared connection
    now = datetime.now(tz=timezone.utc).isoformat()
    keywords_json = json.dumps(keywords, ensure_ascii=False)

    await db.execute(
        """
        INSERT INTO folder_profiles
            (folder_path, primary_extension, ai_description, keywords, file_count, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(folder_path) DO UPDATE SET
            primary_extension = excluded.primary_extension,
            ai_description    = excluded.ai_description,
            keywords          = excluded.keywords,
            file_count        = excluded.file_count,
            indexed_at        = excluded.indexed_at
        """,
        (folder_str, primary_ext, ai_description, keywords_json, file_count, now),
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Profile CRUD                                                                 #
# --------------------------------------------------------------------------- #

async def get_all_profiles() -> list[FolderProfile]:
    """Load all folder profiles from the database."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT id, folder_path, primary_extension, ai_description,
                   keywords, file_count, indexed_at
            FROM folder_profiles
            ORDER BY indexed_at DESC
            """
        )
        rows = await cursor.fetchall()
        profiles: list[FolderProfile] = []
        for row in rows:
            # Parse keywords from JSON string
            try:
                kw = json.loads(row["keywords"]) if row["keywords"] else []
            except (json.JSONDecodeError, TypeError):
                kw = []

            profiles.append(FolderProfile(
                id=row["id"],
                folder_path=row["folder_path"],
                primary_extension=row["primary_extension"],
                ai_description=row["ai_description"],
                keywords=kw,
                file_count=row["file_count"],
                indexed_at=row["indexed_at"],
            ))
        return profiles
    finally:
        await db.close()


async def delete_profile(profile_id: int) -> bool:
    """Delete a profile by ID. Returns True if a row was deleted."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "DELETE FROM folder_profiles WHERE id = ?",
            (profile_id,),
        )
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# YAML export for PROJ-2 compatibility                                         #
# --------------------------------------------------------------------------- #

async def generate_yaml_from_profiles() -> str:
    """
    Read all folder profiles and generate a PROJ-2-compatible
    structure_rules.yaml string.

    Format:
      rules:
        - name: "Steuerdokumente"
          target: "/path/to/folder"
          match:
            extensions: [".pdf"]
            keywords: ["steuer", "elster"]
    """
    profiles = await get_all_profiles()

    if not profiles:
        return yaml.dump({"rules": []}, default_flow_style=False, allow_unicode=True)

    rules: list[dict[str, Any]] = []

    for profile in profiles:
        # Skip chaos/mixed folders -- they don't produce useful rules
        if profile.keywords == ["gemischt"]:
            continue

        # Build match block
        match_block: dict[str, Any] = {}

        if profile.primary_extension:
            match_block["extensions"] = [profile.primary_extension]

        if profile.keywords:
            # Filter out extension-like keywords
            clean_keywords = [
                kw for kw in profile.keywords
                if not kw.startswith(".")
            ]
            if clean_keywords:
                match_block["keywords"] = clean_keywords

        # Only add rule if there's at least one match criterion
        if not match_block:
            continue

        rule_name = profile.ai_description or Path(profile.folder_path).name
        # Truncate long names
        if len(rule_name) > 80:
            rule_name = rule_name[:77] + "..."

        rules.append({
            "name": rule_name,
            "target": profile.folder_path,
            "match": match_block,
        })

    yaml_content = yaml.dump(
        {"rules": rules},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )

    return yaml_content
