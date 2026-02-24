"""
API routes for PROJ-8: Deep-AI Smart Sorting.

Endpoints:
  POST /deep-sort/analyse/{file_name} -- AI analysis of a single low-confidence file
  POST /deep-sort/analyse-batch       -- AI analysis for all unmatched triage items
"""
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from core.ai_service import AIServiceError, ask_json, load_settings
from core.triage import (
    _fuzzy_match_all,
    _load_folder_profiles,
    get_triage_cache,
)
from models.ai_gateway import AIFolderSuggestion
from models.deep_sort import (
    DeepSortBatchRequest,
    DeepSortBatchResult,
    DeepSortBatchStatus,
    DeepSortRequest,
    DeepSortResult,
)
from utils.db import get_db
from utils.rate_limit import check_triage_rate_limit
from utils.text_extractor import extract_text

logger = logging.getLogger("api.deep_sort")

router = APIRouter()

# Special sentinel value returned by AI when no folder fits
_NO_FOLDER_SENTINEL = "KEIN_ORDNER"

# Maximum number of folder candidates to send to the LLM
_MAX_FOLDER_CANDIDATES = 20

# --------------------------------------------------------------------------- #
# In-memory batch status store for BackgroundTask polling                      #
# --------------------------------------------------------------------------- #

_deep_sort_batch_status: dict[str, dict[str, Any]] = {}


def get_deep_sort_batch_status() -> dict[str, dict[str, Any]]:
    """Expose batch status store (e.g. for testing)."""
    return _deep_sort_batch_status


# --------------------------------------------------------------------------- #
# Helpers: SHA-256 hashing                                                     #
# --------------------------------------------------------------------------- #

async def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file's content (async-safe via chunked read)."""
    import asyncio

    def _hash_sync() -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    return await asyncio.to_thread(_hash_sync)


# --------------------------------------------------------------------------- #
# Helpers: ai_cache CRUD                                                       #
# --------------------------------------------------------------------------- #

async def _cache_lookup(file_hash: str, db=None) -> DeepSortResult | None:
    """Check ai_cache for a previous AI result. Returns None on miss.

    BUG-5 FIX: Accepts an optional db connection to reuse across operations.
    If not provided, opens and closes its own connection.
    """
    own_db = db is None
    if own_db:
        db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT suggested_folder, reasoning FROM ai_cache WHERE file_hash = ?",
            (file_hash,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return DeepSortResult(
            source_path="",  # caller fills this in
            suggested_folder=row["suggested_folder"] if row["suggested_folder"] != "__none__" else None,
            reasoning=row["reasoning"] or "",
            from_cache=True,
            readable=True,
        )
    finally:
        if own_db:
            await db.close()


async def _cache_write(
    file_hash: str,
    suggested_folder: str | None,
    reasoning: str,
    model_used: str,
    db=None,
) -> None:
    """Write an AI result to ai_cache (upsert).

    BUG-5 FIX: Accepts an optional db connection to reuse across operations.
    If not provided, opens and closes its own connection.
    """
    own_db = db is None
    if own_db:
        db = await get_db()
    try:
        now = datetime.now(tz=timezone.utc).isoformat()
        folder_value = suggested_folder if suggested_folder else "__none__"
        await db.execute(
            """
            INSERT INTO ai_cache (file_hash, suggested_folder, reasoning, model_used, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(file_hash) DO UPDATE SET
                suggested_folder = excluded.suggested_folder,
                reasoning = excluded.reasoning,
                model_used = excluded.model_used,
                created_at = excluded.created_at
            """,
            (file_hash, folder_value, reasoning, model_used, now),
        )
        await db.commit()
    finally:
        if own_db:
            await db.close()


# --------------------------------------------------------------------------- #
# Helpers: Prompt building                                                     #
# --------------------------------------------------------------------------- #

def _build_prompt(text_content: str, folder_candidates: list[str], file_name: str) -> str:
    """
    Build the LLM prompt for folder suggestion.
    Asks for structured JSON output: {zielordner, begruendung}.
    """
    folder_list = "\n".join(f"  - {f}" for f in folder_candidates)

    return (
        f"Du bist ein Datei-Organisations-Assistent. "
        f"Analysiere den folgenden Dateiinhalt und bestimme, in welchen Ordner die Datei gehoert.\n\n"
        f"Dateiname: {file_name}\n\n"
        f"Dateiinhalt (Ausschnitt):\n---\n{text_content}\n---\n\n"
        f"Moegliche Zielordner:\n{folder_list}\n\n"
        f"Regeln:\n"
        f"1. Waehle genau EINEN Ordner aus der obigen Liste, der am besten passt.\n"
        f"2. Wenn KEIN Ordner passt, setze zielordner auf \"{_NO_FOLDER_SENTINEL}\".\n"
        f"3. Schreibe eine kurze, 1-Satz-Begruendung auf Deutsch.\n"
        f"4. Antworte NUR mit einem JSON-Objekt."
    )


# --------------------------------------------------------------------------- #
# Core analysis logic (shared between single + batch)                          #
# --------------------------------------------------------------------------- #

async def _analyse_single_file(
    file_path: Path,
    file_name: str,
    profiles: list[dict[str, Any]] | None = None,
) -> DeepSortResult:
    """
    Full analysis pipeline for a single file:
    1. Hash -> cache lookup
    2. Text extraction
    3. Pre-filter top-20 folders
    4. LLM call
    5. Hallucination check
    6. Cache write

    BUG-5 FIX: Uses a single DB connection for cache lookup + write.
    RETEST-BUG-2 FIX: Accepts optional pre-loaded profiles to avoid
    opening a separate DB connection per file during batch analysis.
    """
    source_str = str(file_path)

    # Validate file exists
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Datei nicht gefunden: {file_path}")
    if not file_path.is_file():
        raise HTTPException(status_code=422, detail=f"Pfad ist keine Datei: {file_path}")

    # BUG-5 FIX: Open a single DB connection for the entire pipeline
    db = await get_db()
    try:
        # Step 1: Cache lookup
        file_hash = await _compute_file_hash(file_path)
        cached = await _cache_lookup(file_hash, db=db)
        if cached is not None:
            cached.source_path = source_str
            logger.info("Cache-Hit fuer %s (hash=%s...)", file_name, file_hash[:12])
            return cached

        # Step 2: Text extraction
        text_content, readable = await extract_text(file_path)
        if not readable or not text_content.strip():
            logger.info("Datei nicht lesbar: %s", file_name)
            return DeepSortResult(
                source_path=source_str,
                suggested_folder=None,
                reasoning="Datei enthaelt keinen extrahierbaren Text. Nur Dateiname-Analyse moeglich.",
                from_cache=False,
                readable=False,
            )

        # Step 3: Pre-filter top-20 folders via fuzzy match
        # RETEST-BUG-2 FIX: Reuse pre-loaded profiles if provided (batch mode)
        if profiles is None:
            profiles = await _load_folder_profiles()
        if not profiles:
            return DeepSortResult(
                source_path=source_str,
                suggested_folder=None,
                reasoning="Keine Ordner-Profile vorhanden. Bitte zuerst Ordner indexieren.",
                from_cache=False,
                readable=True,
            )

        # Get all folder paths for validation
        all_folder_paths = {p["folder_path"] for p in profiles}

        # Fuzzy pre-filter: get top candidates sorted by score
        candidates = _fuzzy_match_all(file_name, profiles, threshold=0)
        top_folders = [folder for folder, _score in candidates[:_MAX_FOLDER_CANDIDATES]]

        # If fuzzy match returns fewer than 5, pad with random profiles
        if len(top_folders) < 5:
            for p in profiles:
                if p["folder_path"] not in top_folders:
                    top_folders.append(p["folder_path"])
                if len(top_folders) >= _MAX_FOLDER_CANDIDATES:
                    break

        # Step 4: LLM call
        prompt = _build_prompt(text_content, top_folders, file_name)

        try:
            ai_result = await ask_json(prompt, AIFolderSuggestion)
        except AIServiceError as exc:
            logger.error("AI-Fehler fuer %s: %s", file_name, exc)
            if exc.code == "OLLAMA_UNREACHABLE":
                raise HTTPException(
                    status_code=503,
                    detail="Ollama ist nicht erreichbar. Bitte starte Ollama zuerst.",
                )
            raise HTTPException(
                status_code=503,
                detail=f"KI-Analyse fehlgeschlagen: {exc}",
            )

        # Step 5: Hallucination check
        suggested = ai_result.zielordner.strip()
        reasoning = ai_result.begruendung.strip()

        # Load current settings to record model name
        settings = await load_settings()
        model_used = settings.model_name

        if suggested == _NO_FOLDER_SENTINEL:
            # AI says no folder fits -> suggest [Dateityp]/Unsortiert as fallback
            file_ext = file_path.suffix.lstrip(".").upper() or "Sonstige"
            unsortiert_folder = f"{file_ext}/Unsortiert"
            reasoning_with_hint = (
                f"{reasoning} (Kein passender Ordner gefunden. "
                f"Vorschlag: '{unsortiert_folder}' als neuen Ordner anlegen.)"
            )
            await _cache_write(file_hash, None, reasoning_with_hint, model_used, db=db)
            return DeepSortResult(
                source_path=source_str,
                suggested_folder=None,
                reasoning=reasoning_with_hint,
                from_cache=False,
                readable=True,
                unsortiert_suggestion=unsortiert_folder,
            )

        if suggested not in all_folder_paths:
            # Hallucination: suggested folder does not exist
            logger.warning(
                "Halluzination erkannt: KI schlug '%s' vor, existiert nicht in Profilen.",
                suggested,
            )
            await _cache_write(file_hash, None, "KI-Vorschlag nicht validierbar (Ordner existiert nicht).", model_used, db=db)
            return DeepSortResult(
                source_path=source_str,
                suggested_folder=None,
                reasoning=f"KI-Vorschlag '{suggested}' existiert nicht in den bekannten Ordnern.",
                from_cache=False,
                readable=True,
            )

        # Step 6: Valid result -> cache and return
        await _cache_write(file_hash, suggested, reasoning, model_used, db=db)
        logger.info("KI-Analyse erfolgreich: %s -> %s", file_name, suggested)

        return DeepSortResult(
            source_path=source_str,
            suggested_folder=suggested,
            reasoning=reasoning,
            from_cache=False,
            readable=True,
        )
    finally:
        await db.close()


# --------------------------------------------------------------------------- #
# POST /deep-sort/analyse/{file_name}                                          #
# --------------------------------------------------------------------------- #

@router.post(
    "/analyse/{file_name}",
    response_model=DeepSortResult,
    dependencies=[Depends(check_triage_rate_limit)],
)
async def analyse_single(file_name: str, body: DeepSortRequest) -> DeepSortResult:
    """
    Read file content, query AI Gateway, return folder suggestion + reasoning.

    Pipeline:
    1. SafePath validation (via Pydantic model)
    2. Validate file_name against source_path
    3. SHA-256 hash -> cache lookup
    4. Text extraction (max 2000 chars)
    5. Pre-filter top-20 folders via fuzzy match
    6. LLM call via ai_service.ask_json()
    7. Hallucination check against real folder_profiles
    8. Cache write + return
    """
    file_path = Path(body.source_path) if isinstance(body.source_path, str) else body.source_path

    # BUG-6 FIX: Validate that the URL file_name matches the actual filename
    # from source_path to prevent manipulation of fuzzy-match pre-filtering
    actual_file_name = file_path.name
    if file_name != actual_file_name:
        logger.warning(
            "file_name Mismatch: URL='%s', source_path='%s' -> verwende '%s'",
            file_name, file_path, actual_file_name,
        )
        file_name = actual_file_name

    return await _analyse_single_file(file_path, file_name)


# --------------------------------------------------------------------------- #
# POST /deep-sort/analyse-batch  (BackgroundTask + polling)                    #
# --------------------------------------------------------------------------- #

async def _run_batch_analysis(batch_id: str, to_analyse: list, threshold: int) -> None:
    """
    Background coroutine that processes all eligible triage items via AI.
    Updates _deep_sort_batch_status in-place so the frontend can poll progress.

    RETEST-BUG-2 FIX: Pre-loads folder profiles once and passes them to each
    _analyse_single_file call, avoiding N redundant DB connection cycles.
    """
    status = _deep_sort_batch_status[batch_id]
    results: list[DeepSortResult] = []
    failed = 0

    # Pre-load folder profiles once for the entire batch
    profiles = await _load_folder_profiles()

    for item in to_analyse:
        try:
            file_path = Path(item.source_path)
            result = await _analyse_single_file(file_path, item.file_name, profiles=profiles)
            results.append(result)
        except HTTPException:
            failed += 1
            results.append(DeepSortResult(
                source_path=item.source_path,
                suggested_folder=None,
                reasoning="KI-Analyse fehlgeschlagen.",
                from_cache=False,
                readable=True,
            ))
        except Exception as exc:
            logger.error("Unerwarteter Fehler bei Batch-Analyse von %s: %s", item.file_name, exc)
            failed += 1
            results.append(DeepSortResult(
                source_path=item.source_path,
                suggested_folder=None,
                reasoning=f"Unerwarteter Fehler: {type(exc).__name__}",
                from_cache=False,
                readable=True,
            ))

        # Update progress for polling
        status["processed"] = len(results) - failed
        status["failed"] = failed
        status["results"] = results

    # Mark as done
    status["processed"] = len(results) - failed
    status["failed"] = failed
    status["results"] = results
    status["done"] = True
    logger.info(
        "Batch-KI-Analyse %s abgeschlossen: %d verarbeitet, %d fehlgeschlagen",
        batch_id, len(results) - failed, failed,
    )


@router.post(
    "/analyse-batch",
    response_model=DeepSortBatchStatus,
    dependencies=[Depends(check_triage_rate_limit)],
)
async def analyse_batch(
    body: DeepSortBatchRequest,
    background_tasks: BackgroundTasks,
) -> DeepSortBatchStatus:
    """
    Start AI analysis for all low-confidence files from a triage batch.

    Runs as a BackgroundTask to avoid HTTP timeouts with large file counts.
    Returns immediately with a batch_id that can be polled via
    GET /deep-sort/batch/{batch_id}/status.
    """
    cache = get_triage_cache()
    items = cache.get(body.batch_id)

    if items is None:
        raise HTTPException(
            status_code=404,
            detail=f"Triage-Batch nicht gefunden: {body.batch_id}",
        )

    # Filter items that need AI analysis
    to_analyse = [
        item for item in items
        if (item.confidence is None)
        or (item.confidence < body.threshold)
        or (item.suggested_folder is None)
    ]

    if not to_analyse:
        return DeepSortBatchStatus(
            batch_id=body.batch_id, total=0, processed=0, failed=0, done=True, results=[],
        )

    # Initialize status for polling
    _deep_sort_batch_status[body.batch_id] = {
        "total": len(to_analyse),
        "processed": 0,
        "failed": 0,
        "done": False,
        "results": [],
    }

    # Schedule background processing
    background_tasks.add_task(_run_batch_analysis, body.batch_id, to_analyse, body.threshold)

    return DeepSortBatchStatus(
        batch_id=body.batch_id,
        total=len(to_analyse),
        processed=0,
        failed=0,
        done=False,
        results=[],
    )


# --------------------------------------------------------------------------- #
# GET /deep-sort/batch/{batch_id}/status  (polling endpoint)                   #
# --------------------------------------------------------------------------- #

@router.get(
    "/batch/{batch_id}/status",
    response_model=DeepSortBatchStatus,
)
async def batch_status(batch_id: str) -> DeepSortBatchStatus:
    """
    Poll the progress of a running batch AI analysis.
    Returns current progress, results so far, and done flag.
    """
    status = _deep_sort_batch_status.get(batch_id)
    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Batch-KI-Analyse nicht gefunden: {batch_id}",
        )

    return DeepSortBatchStatus(
        batch_id=batch_id,
        total=status["total"],
        processed=status["processed"],
        failed=status["failed"],
        done=status["done"],
        results=[r if isinstance(r, DeepSortResult) else DeepSortResult(**r) for r in status["results"]],
    )
