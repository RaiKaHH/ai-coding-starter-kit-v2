"""
PROJ-5: Smart Inbox Triage -- Business Logic.

Responsibilities:
- Stage 1 (strict match): compare filename against structure_rules.yaml rules
  using fnmatch/regex (reuses core.mover._file_matches_rule)
- Stage 2 (fuzzy match): compare filename tokens against folder_profiles.keywords
  using TF-IDF (scikit-learn) + difflib.SequenceMatcher for combined scoring
- Return confidence score (0-100) per file
- Handle ties: surface top-2 candidates without auto-selecting
- Delegate actual move execution to core/mover.py (no own shutil calls)
- Feedback loop: when user corrects folder, update folder_profiles.keywords
"""
import asyncio
import json
import logging
import re
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from core.mover import (
    _file_matches_rule,
    _resolve_name_conflict,
    execute_batch as mover_execute_batch,
    get_batch_cache as mover_batch_cache,
    get_batch_status_store as mover_batch_status,
    parse_yaml_rules,
    RuleParseError,
)
from models.move import MovePreviewItem
from models.triage import (
    TriageConfirmItem,
    TriageItem,
    TriageResponse,
    TriageExecuteResult,
)
from utils.db import get_db

logger = logging.getLogger("core.triage")

# --------------------------------------------------------------------------- #
# In-memory triage batch cache (single-user tool)                              #
# --------------------------------------------------------------------------- #

_triage_cache: dict[str, list[TriageItem]] = {}
_triage_status: dict[str, dict[str, Any]] = {}

# BUG-3 FIX: Maximum number of cached triage batches before evicting oldest
_MAX_TRIAGE_CACHE_SIZE = 20


def get_triage_cache() -> dict[str, list[TriageItem]]:
    return _triage_cache


def get_triage_status_store() -> dict[str, dict[str, Any]]:
    return _triage_status


def _evict_old_cache_entries() -> None:
    """BUG-3 FIX: Remove oldest cache entries when exceeding max size."""
    while len(_triage_cache) > _MAX_TRIAGE_CACHE_SIZE:
        oldest_key = next(iter(_triage_cache))
        _triage_cache.pop(oldest_key, None)
        _triage_status.pop(oldest_key, None)
        logger.info("Triage-Cache: Eintrag %s entfernt (max %d)", oldest_key, _MAX_TRIAGE_CACHE_SIZE)


# --------------------------------------------------------------------------- #
# Token extraction (shared between fuzzy match and feedback)                   #
# --------------------------------------------------------------------------- #

def _tokenize_filename(filename: str, *, sanitize: bool = False) -> list[str]:
    """
    Extract meaningful lowercase tokens from a filename.
    Strips extension, splits on separators and camelCase boundaries.

    If sanitize=True, strips non-alphanumeric characters from tokens
    (BUG-9 FIX: prevents storing HTML/script fragments as keywords).
    """
    stem = Path(filename).stem
    # Split on common separators: -, _, ., spaces, digits-to-alpha boundaries
    parts = re.split(r"[-_.\s]+", stem)
    tokens: list[str] = []
    for part in parts:
        # Split camelCase
        camel_parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).split()
        for token in camel_parts:
            clean = token.strip().lower()
            if sanitize:
                # BUG-9 FIX: Remove all non-alphanumeric characters (keep umlauts etc.)
                clean = re.sub(r"[^a-z0-9\u00e4\u00f6\u00fc\u00df]", "", clean)
            if clean and len(clean) > 1:
                tokens.append(clean)
    return tokens


# --------------------------------------------------------------------------- #
# Stage 1: Strict matching against structure_rules.yaml                        #
# --------------------------------------------------------------------------- #

async def _load_yaml_rules() -> list[dict] | None:
    """
    Try to load the default structure_rules.yaml from the data/ directory.
    Returns None if no YAML file exists (user has not created one yet).
    """
    default_path = Path("data/structure_rules.yaml")
    if not default_path.exists():
        return None
    try:
        rules, _ = parse_yaml_rules(default_path)
        return rules
    except RuleParseError as exc:
        logger.warning("Konnte YAML-Regeln nicht laden: %s", exc)
        return None


def _strict_match(filename: str, rules: list[dict]) -> str | None:
    """
    Check filename against YAML rules. Returns the target folder path
    of the first matching rule, or None.
    """
    for rule in rules:
        if _file_matches_rule(filename, rule["match"]):
            return rule["target"]
    return None


# --------------------------------------------------------------------------- #
# Stage 2: Fuzzy matching against folder_profiles                              #
# --------------------------------------------------------------------------- #

async def _load_folder_profiles() -> list[dict[str, Any]]:
    """Load all folder profiles from the database for fuzzy matching."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT folder_path, primary_extension, ai_description, keywords
            FROM folder_profiles
            WHERE keywords != '["gemischt"]'
            ORDER BY file_count DESC
            """
        )
        rows = await cursor.fetchall()
        profiles = []
        for row in rows:
            try:
                keywords = json.loads(row["keywords"]) if row["keywords"] else []
            except (json.JSONDecodeError, TypeError):
                keywords = []
            profiles.append({
                "folder_path": row["folder_path"],
                "primary_extension": row["primary_extension"],
                "ai_description": row["ai_description"] or "",
                "keywords": keywords,
            })
        return profiles
    finally:
        await db.close()


def _fuzzy_score(filename: str, profile: dict[str, Any]) -> int:
    """
    Calculate a fuzzy match score (0-99) between a filename and a folder profile.

    Uses a combination of:
    1. Token overlap between filename tokens and profile keywords (weight: 50%)
    2. SequenceMatcher ratio against profile keywords joined (weight: 30%)
    3. Extension match bonus (weight: 20%)
    """
    file_tokens = _tokenize_filename(filename)
    if not file_tokens:
        return 0

    keywords = profile.get("keywords", [])
    description = profile.get("ai_description", "")
    primary_ext = profile.get("primary_extension", "")

    # Combined profile text for sequence matching
    profile_text = " ".join(keywords).lower()
    if description:
        profile_text += " " + description.lower()

    file_text = " ".join(file_tokens)

    # --- Score component 1: Token overlap (0-50) ---
    token_score = 0
    if keywords:
        kw_lower = [kw.lower() for kw in keywords]
        matches = 0
        for token in file_tokens:
            for kw in kw_lower:
                # Partial match: token is substring of keyword or vice versa
                if token in kw or kw in token:
                    matches += 1
                    break
                # Close match via SequenceMatcher
                if SequenceMatcher(None, token, kw).ratio() > 0.75:
                    matches += 1
                    break
        if file_tokens:
            token_score = int((matches / len(file_tokens)) * 50)

    # --- Score component 2: SequenceMatcher on full text (0-30) ---
    seq_score = 0
    if profile_text.strip():
        ratio = SequenceMatcher(None, file_text, profile_text).ratio()
        seq_score = int(ratio * 30)

    # --- Score component 3: Extension match (0-20) ---
    ext_score = 0
    file_ext = Path(filename).suffix.lower()
    if file_ext and primary_ext and file_ext == primary_ext.lower():
        ext_score = 20

    total = min(token_score + seq_score + ext_score, 99)
    return total


def _fuzzy_match_all(
    filename: str,
    profiles: list[dict[str, Any]],
    threshold: int,
    exclude_folders: set[str] | None = None,
) -> list[tuple[str, int]]:
    """
    Score filename against all profiles, return list of (folder_path, score)
    for scores >= threshold, sorted descending.

    exclude_folders: set of resolved folder paths to skip (e.g. the inbox itself).
    """
    candidates: list[tuple[str, int]] = []
    for profile in profiles:
        # BUG-2 FIX: Skip profiles whose folder_path matches excluded folders
        if exclude_folders and profile["folder_path"] in exclude_folders:
            continue
        score = _fuzzy_score(filename, profile)
        if score >= threshold:
            candidates.append((profile["folder_path"], score))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates


# --------------------------------------------------------------------------- #
# BUG-7 FIX: Synchronous matching helper (runs in thread via asyncio.to_thread)#
# --------------------------------------------------------------------------- #

def _match_files_sync(
    files: list[Path],
    yaml_rules: list[dict] | None,
    profiles: list[dict[str, Any]],
    confidence_threshold: int,
    exclude_folders: set[str],
) -> tuple[list[TriageItem], int]:
    """
    CPU-bound matching logic extracted so it can run in a separate thread.
    Returns (items, unmatched_count).
    """
    items: list[TriageItem] = []
    unmatched_count = 0

    for file in files:
        filename = file.name
        source_path = str(file)

        # Stage 1: Strict match
        if yaml_rules:
            strict_target = _strict_match(filename, yaml_rules)
            if strict_target:
                items.append(TriageItem(
                    file_name=filename,
                    source_path=source_path,
                    suggested_folder=strict_target,
                    confidence=100,
                    match_type="strict",
                    alternatives=[],
                ))
                continue

        # Stage 2: Fuzzy match
        if profiles:
            candidates = _fuzzy_match_all(filename, profiles, confidence_threshold, exclude_folders)
            if candidates:
                top_folder, top_score = candidates[0]

                # Check for ties (scores within 5 points of each other)
                alternatives = [
                    folder for folder, score in candidates[1:5]
                    if score >= top_score - 5
                ]

                # BUG-6 FIX: Check ALL candidates (not just [1:2]) for ties
                has_tie = any(
                    score == top_score for folder, score in candidates[1:]
                )

                items.append(TriageItem(
                    file_name=filename,
                    source_path=source_path,
                    suggested_folder=top_folder if not has_tie else None,
                    confidence=top_score,
                    match_type="fuzzy",
                    alternatives=(
                        [top_folder] + alternatives if has_tie
                        else alternatives
                    ),
                ))
                continue

        # No match found
        items.append(TriageItem(
            file_name=filename,
            source_path=source_path,
            suggested_folder=None,
            confidence=None,
            match_type=None,
            alternatives=[],
        ))
        unmatched_count += 1

    return items, unmatched_count


# --------------------------------------------------------------------------- #
# Main analysis pipeline                                                       #
# --------------------------------------------------------------------------- #

async def analyse_inbox(
    inbox_path: Path,
    confidence_threshold: int = 40,
) -> TriageResponse:
    """
    Analyse all files in inbox_path and return triage suggestions.

    Two-stage matching:
    1. Strict: check against structure_rules.yaml -> 100% confidence
    2. Fuzzy: compare filename tokens against folder_profiles -> 0-99%
    """
    # Validate inbox
    if not inbox_path.exists():
        raise FileNotFoundError(f"Eingangsordner nicht gefunden: {inbox_path}")
    if not inbox_path.is_dir():
        raise NotADirectoryError(f"Pfad ist kein Ordner: {inbox_path}")

    # Load matching data
    yaml_rules = await _load_yaml_rules()
    profiles = await _load_folder_profiles()

    # BUG-2 FIX: Build exclusion set -- the inbox folder itself must never
    # be suggested as a target. Resolve to handle symlinks / /private/tmp etc.
    inbox_resolved = str(inbox_path.resolve())
    exclude_folders: set[str] = set()
    for profile in profiles:
        profile_resolved = str(Path(profile["folder_path"]).resolve())
        if profile_resolved == inbox_resolved:
            exclude_folders.add(profile["folder_path"])

    # Check if we have any data to work with
    has_rules = yaml_rules is not None and len(yaml_rules) > 0
    has_profiles = len(profiles) > 0

    if not has_rules and not has_profiles:
        raise ValueError(
            "Keine Regeln oder Ordner-Profile vorhanden. "
            "Bitte zuerst einen Muster-Ordner indexieren (Indexer) "
            "oder eine structure_rules.yaml im data/-Ordner ablegen."
        )

    # Collect files in inbox (non-recursive, top-level only)
    files: list[Path] = []
    try:
        for item in inbox_path.iterdir():
            if item.is_file() and not item.name.startswith("."):
                files.append(item)
    except PermissionError:
        raise PermissionError(f"Keine Leseberechtigung fuer: {inbox_path}")

    files.sort(key=lambda f: f.name.lower())

    # BUG-7 FIX: Offload CPU-bound matching to a thread to avoid blocking the event loop
    items, unmatched_count = await asyncio.to_thread(
        _match_files_sync,
        files,
        yaml_rules if has_rules else None,
        profiles if has_profiles else [],
        confidence_threshold,
        exclude_folders,
    )

    batch_id = str(uuid.uuid4())

    # Cache for later execution
    _triage_cache[batch_id] = items
    _triage_status[batch_id] = {
        "total": 0, "moved": 0, "failed": 0,
        "done": False, "errors": [],
    }
    # BUG-3 FIX: Evict old entries to prevent unbounded memory growth
    _evict_old_cache_entries()

    return TriageResponse(
        batch_id=batch_id,
        items=items,
        unmatched_count=unmatched_count,
    )


# --------------------------------------------------------------------------- #
# Execute triage (delegates to core/mover.py)                                  #
# --------------------------------------------------------------------------- #

async def execute_triage(
    batch_id: str,
    confirmed_items: list[TriageConfirmItem],
) -> None:
    """
    Execute confirmed triage moves as a background task.
    Delegates to core/mover.py for the actual file operations.

    This function converts TriageConfirmItems into MovePreviewItems
    and uses the mover's execute_batch for the actual I/O + logging.
    """
    # --- BUG-1 FIX: Validate confirmed items against original batch ---
    cached_items = _triage_cache.get(batch_id)
    if cached_items is None:
        raise ValueError(f"Triage-Batch nicht gefunden: {batch_id}")

    # Build a set of allowed source_paths from the original analysis
    allowed_sources = {item.source_path for item in cached_items}

    for item in confirmed_items:
        source_str = str(item.source_path) if isinstance(item.source_path, Path) else item.source_path
        if source_str not in allowed_sources:
            raise ValueError(
                f"Datei '{item.file_name}' (source_path={source_str}) "
                f"gehoert nicht zum urspruenglichen Analyse-Batch {batch_id}. "
                f"Verschiebung abgelehnt."
            )

    # Build MovePreviewItems for the mover
    move_items: list[MovePreviewItem] = []
    for idx, item in enumerate(confirmed_items):
        target_dir = Path(item.confirmed_folder)
        target_path = target_dir / item.file_name
        move_items.append(MovePreviewItem(
            id=idx,
            file_name=item.file_name,
            source_path=item.source_path,
            target_path=str(target_path),
            rule_matched="triage",
        ))

    # Inject into mover's batch cache and status
    cache = mover_batch_cache()
    status_store = mover_batch_status()

    cache[batch_id] = move_items
    status_store[batch_id] = {
        "total": len(move_items),
        "moved": 0,
        "failed": 0,
        "done": False,
        "errors": [],
    }

    # Delegate to mover (all IDs are selected)
    selected_ids = [item.id for item in move_items]
    await mover_execute_batch(batch_id, selected_ids)

    # Update triage-specific status from mover status
    mover_status = status_store.get(batch_id, {})
    _triage_status[batch_id] = {
        "total": mover_status.get("total", 0),
        "moved": mover_status.get("moved", 0),
        "failed": mover_status.get("failed", 0),
        "done": mover_status.get("done", True),
        "errors": mover_status.get("errors", []),
    }

    # BUG-3 FIX: Remove the batch from triage cache after execution
    # (status is kept so the UI can poll the result, but the heavy item list is freed)
    _triage_cache.pop(batch_id, None)
    logger.info("Triage-Cache: Batch %s nach Ausfuehrung bereinigt", batch_id)


# --------------------------------------------------------------------------- #
# Feedback loop: update folder_profiles keywords                               #
# --------------------------------------------------------------------------- #

async def apply_feedback(file_name: str, chosen_folder: Path) -> None:
    """
    When the user manually corrects a folder assignment, extract tokens
    from the filename and add them to the chosen folder's keywords
    in folder_profiles. This strengthens future matching.
    """
    folder_str = str(chosen_folder)
    # BUG-9 FIX: sanitize tokens to avoid storing HTML/script fragments as keywords
    new_tokens = _tokenize_filename(file_name, sanitize=True)

    if not new_tokens:
        logger.info("Kein Feedback moeglich: keine Tokens in '%s'", file_name)
        return

    db = await get_db()
    try:
        # Load existing keywords for this folder
        cursor = await db.execute(
            "SELECT keywords FROM folder_profiles WHERE folder_path = ?",
            (folder_str,),
        )
        row = await cursor.fetchone()

        if row is None:
            # Folder not in profiles yet -- create a new entry
            from datetime import datetime, timezone
            now = datetime.now(tz=timezone.utc).isoformat()
            keywords = list(set(new_tokens))[:10]
            keywords_json = json.dumps(keywords, ensure_ascii=False)

            # Determine primary extension from the filename
            ext = Path(file_name).suffix.lower() or None

            await db.execute(
                """
                INSERT INTO folder_profiles
                    (folder_path, primary_extension, ai_description, keywords, file_count, indexed_at)
                VALUES (?, ?, NULL, ?, 0, ?)
                """,
                (folder_str, ext, keywords_json, now),
            )
            await db.commit()
            logger.info(
                "Neues Ordner-Profil angelegt fuer '%s' mit Keywords: %s",
                folder_str,
                keywords,
            )
            return

        # Merge new tokens into existing keywords
        try:
            existing = json.loads(row["keywords"]) if row["keywords"] else []
        except (json.JSONDecodeError, TypeError):
            existing = []

        existing_lower = {kw.lower() for kw in existing}
        added = []
        for token in new_tokens:
            if token.lower() not in existing_lower:
                existing.append(token)
                existing_lower.add(token.lower())
                added.append(token)

        # Cap at 20 keywords max
        existing = existing[:20]
        keywords_json = json.dumps(existing, ensure_ascii=False)

        await db.execute(
            "UPDATE folder_profiles SET keywords = ? WHERE folder_path = ?",
            (keywords_json, folder_str),
        )
        await db.commit()

        if added:
            logger.info(
                "Feedback: %d neue Keywords fuer '%s': %s",
                len(added),
                folder_str,
                added,
            )

    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# Helper: get all known folder paths for UI dropdown                           #
# --------------------------------------------------------------------------- #

async def get_all_folder_paths() -> list[str]:
    """Return all known folder paths from folder_profiles for the UI dropdown."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT folder_path FROM folder_profiles
            WHERE keywords != '["gemischt"]'
            ORDER BY folder_path
            """
        )
        rows = await cursor.fetchall()
        return [row["folder_path"] for row in rows]
    finally:
        await db.close()
