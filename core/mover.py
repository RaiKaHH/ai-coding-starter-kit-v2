"""
PROJ-2: Struktur-basierter Datei-Verschieber -- Business Logic.

Responsibilities:
- Parse structure_rules.yaml (PyYAML)
- Infer rules from a well-organised reference folder
- Map scan_files against rules (fnmatch / re)
- Dry-run: return MovePreviewItem list (no I/O)
- Execute: shutil.move() for confirmed items (BackgroundTask)
- Write every move to operation_log with batch_id
- Handle name collisions (_1, _2 suffixes)
"""
import fnmatch
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import yaml

from models.move import MovePreviewItem, MovePreviewResponse
from utils.db import get_db


# --------------------------------------------------------------------------- #
# In-memory batch cache (single-user tool, acceptable trade-off)              #
# --------------------------------------------------------------------------- #

_batch_cache: dict[str, list[MovePreviewItem]] = {}
_batch_status: dict[str, dict[str, Any]] = {}


def get_batch_cache() -> dict[str, list[MovePreviewItem]]:
    """Return the global batch cache (for testing / API access)."""
    return _batch_cache


def get_batch_status_store() -> dict[str, dict[str, Any]]:
    """Return the global batch status store."""
    return _batch_status


# --------------------------------------------------------------------------- #
# YAML rule parsing                                                           #
# --------------------------------------------------------------------------- #

class RuleParseError(Exception):
    """Raised when the YAML rules file is invalid or malformed."""


def parse_yaml_rules(path: Path) -> tuple[list[dict], str]:
    """
    Parse a structure_rules.yaml file and return (rules_list, unmatched_policy).

    Each rule dict has:
      - name: str
      - target: str (absolute path, ~ expanded)
      - match: dict with optional keys: extensions, name_pattern, name_regex

    Raises RuleParseError on invalid input.
    """
    if not path.exists():
        raise RuleParseError(f"YAML-Datei nicht gefunden: {path}")
    if not path.is_file():
        raise RuleParseError(f"Pfad ist keine Datei: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except PermissionError:
        raise RuleParseError(f"Keine Leseberechtigung fuer: {path}")
    except Exception as exc:
        raise RuleParseError(f"Fehler beim Lesen der Datei: {exc}")

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise RuleParseError(f"YAML-Syntaxfehler: {exc}")

    if not isinstance(data, dict):
        raise RuleParseError("YAML-Datei muss ein Dictionary auf Root-Ebene enthalten.")

    raw_rules = data.get("rules")
    if not raw_rules or not isinstance(raw_rules, list):
        raise RuleParseError("YAML-Datei muss eine 'rules'-Liste enthalten.")

    parsed_rules: list[dict] = []
    for idx, rule in enumerate(raw_rules):
        if not isinstance(rule, dict):
            raise RuleParseError(f"Regel #{idx + 1} muss ein Dictionary sein.")

        name = rule.get("name")
        if not name:
            raise RuleParseError(f"Regel #{idx + 1}: 'name' fehlt.")

        target = rule.get("target")
        if not target:
            raise RuleParseError(f"Regel '{name}': 'target' fehlt.")

        # Expand ~ to home directory
        target_path = Path(target).expanduser().resolve()

        match_block = rule.get("match")
        if not match_block or not isinstance(match_block, dict):
            raise RuleParseError(f"Regel '{name}': 'match'-Block fehlt oder ist ungueltig.")

        parsed_rules.append({
            "name": str(name),
            "target": str(target_path),
            "match": {
                "extensions": [
                    ext.lower() if ext.startswith(".") else f".{ext.lower()}"
                    for ext in (match_block.get("extensions") or [])
                ],
                "name_pattern": match_block.get("name_pattern"),
                "name_regex": match_block.get("name_regex"),
            },
        })

    unmatched = data.get("unmatched", "skip")
    if isinstance(unmatched, str) and unmatched.startswith("move_to:"):
        unmatched_target = unmatched.split(":", 1)[1].strip()
        unmatched = f"move_to:{Path(unmatched_target).expanduser().resolve()}"

    return parsed_rules, str(unmatched)


# --------------------------------------------------------------------------- #
# Infer rules from a reference folder                                         #
# --------------------------------------------------------------------------- #

def infer_rules_from_folder(folder_path: Path) -> tuple[list[dict], str]:
    """
    Analyse a well-organised reference folder and derive move rules.

    Strategy: for each immediate subfolder, collect the file extensions found
    within it and create a rule that maps those extensions to that subfolder.

    Returns (rules_list, unmatched_policy).
    """
    if not folder_path.exists():
        raise RuleParseError(f"Referenzordner nicht gefunden: {folder_path}")
    if not folder_path.is_dir():
        raise RuleParseError(f"Pfad ist kein Ordner: {folder_path}")

    rules: list[dict] = []

    try:
        subdirs = sorted(
            [d for d in folder_path.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=lambda d: d.name.lower(),
        )
    except PermissionError:
        raise RuleParseError(f"Keine Leseberechtigung fuer: {folder_path}")

    for subdir in subdirs:
        extensions: set[str] = set()
        try:
            for item in subdir.rglob("*"):
                if item.is_file() and item.suffix:
                    extensions.add(item.suffix.lower())
        except PermissionError:
            continue

        if extensions:
            rules.append({
                "name": f"{subdir.name} (abgeleitet)",
                "target": str(subdir),
                "match": {
                    "extensions": sorted(extensions),
                    "name_pattern": None,
                    "name_regex": None,
                },
            })

    return rules, "skip"


# --------------------------------------------------------------------------- #
# File-to-rule matching (dry-run / preview)                                   #
# --------------------------------------------------------------------------- #

def _file_matches_rule(file_name: str, rule_match: dict) -> bool:
    """Check if a filename matches a single rule's match criteria."""
    extensions = rule_match.get("extensions", [])
    name_pattern = rule_match.get("name_pattern")
    name_regex = rule_match.get("name_regex")

    # At least one criterion must be defined
    has_criteria = bool(extensions or name_pattern or name_regex)
    if not has_criteria:
        return False

    # All defined criteria must match (AND logic)
    if extensions:
        file_ext = Path(file_name).suffix.lower()
        if file_ext not in extensions:
            return False

    if name_pattern:
        if not fnmatch.fnmatch(file_name, name_pattern):
            return False

    if name_regex:
        try:
            if not re.search(name_regex, file_name):
                return False
        except re.error:
            return False

    return True


async def match_files_to_rules(
    scan_id: str,
    rules: list[dict],
    unmatched_policy: str,
) -> MovePreviewResponse:
    """
    Load files from scan_files for the given scan_id, match them against
    rules (top-down priority), and return a preview response.

    No file I/O happens here -- pure matching logic.
    """
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT id, name, path FROM scan_files WHERE scan_id = ?",
            (scan_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    if not rows:
        batch_id = str(uuid.uuid4())
        response = MovePreviewResponse(batch_id=batch_id, items=[], unmatched_count=0)
        _batch_cache[batch_id] = []
        _batch_status[batch_id] = {
            "total": 0, "moved": 0, "failed": 0,
            "done": True, "errors": [],
        }
        return response

    items: list[MovePreviewItem] = []
    unmatched_count = 0
    item_id = 0

    # Determine unmatched target if policy is move_to
    unmatched_target: str | None = None
    if unmatched_policy.startswith("move_to:"):
        unmatched_target = unmatched_policy.split(":", 1)[1].strip()

    for row in rows:
        file_name: str = row["name"]
        file_path: str = row["path"]
        source_path = Path(file_path)

        matched = False
        for rule in rules:
            if _file_matches_rule(file_name, rule["match"]):
                target_dir = Path(rule["target"])
                target_path = target_dir / file_name

                # Skip if source == target (circular path)
                if source_path.parent == target_dir:
                    continue

                items.append(MovePreviewItem(
                    id=item_id,
                    file_name=file_name,
                    source_path=file_path,
                    target_path=str(target_path),
                    rule_matched=rule["name"],
                ))
                item_id += 1
                matched = True
                break  # Top-down priority: first match wins

        if not matched:
            if unmatched_target:
                target_dir = Path(unmatched_target)
                if source_path.parent != target_dir:
                    items.append(MovePreviewItem(
                        id=item_id,
                        file_name=file_name,
                        source_path=file_path,
                        target_path=str(target_dir / file_name),
                        rule_matched="(Unsortiert)",
                    ))
                    item_id += 1
                else:
                    unmatched_count += 1
            else:
                unmatched_count += 1

    batch_id = str(uuid.uuid4())
    response = MovePreviewResponse(
        batch_id=batch_id,
        items=items,
        unmatched_count=unmatched_count,
    )

    # Cache preview for later execution
    _batch_cache[batch_id] = items
    _batch_status[batch_id] = {
        "total": len(items),
        "moved": 0,
        "failed": 0,
        "done": False,
        "errors": [],
    }

    return response


# --------------------------------------------------------------------------- #
# Name collision resolution                                                   #
# --------------------------------------------------------------------------- #

def _resolve_name_conflict(target: Path) -> Path:
    """
    If target already exists, append _1, _2, ... until a free name is found.
    Example: rechnung.pdf -> rechnung_1.pdf -> rechnung_2.pdf
    """
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 1

    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
        if counter > 9999:
            # Safety valve
            raise OSError(f"Zu viele Namenskonflikte fuer: {target}")


# --------------------------------------------------------------------------- #
# Batch execution (runs as BackgroundTask)                                    #
# --------------------------------------------------------------------------- #

async def execute_batch(batch_id: str, selected_ids: list[int]) -> None:
    """
    Execute the confirmed move operations for a batch.

    This function is designed to run as a FastAPI BackgroundTask.
    It moves files via shutil.move, handles name conflicts, creates
    missing target directories, and logs every operation to operation_log.
    """
    cached_items = _batch_cache.get(batch_id)
    if cached_items is None:
        _batch_status[batch_id] = {
            "total": 0, "moved": 0, "failed": 0,
            "done": True, "errors": [f"Batch {batch_id} nicht gefunden."],
        }
        return

    # Filter to only selected items
    selected_set = set(selected_ids)
    items_to_move = [item for item in cached_items if item.id in selected_set]

    status = _batch_status.setdefault(batch_id, {
        "total": len(items_to_move),
        "moved": 0,
        "failed": 0,
        "done": False,
        "errors": [],
    })
    status["total"] = len(items_to_move)
    status["moved"] = 0
    status["failed"] = 0
    status["done"] = False
    status["errors"] = []

    db = await get_db()
    try:
        for item in items_to_move:
            source = Path(item.source_path)
            target = Path(item.target_path)
            actual_target = target
            op_status = "completed"

            try:
                # Verify source still exists
                if not source.exists():
                    raise FileNotFoundError(f"Quelldatei nicht mehr vorhanden: {source}")

                # Create target directory if needed
                target.parent.mkdir(parents=True, exist_ok=True)

                # Resolve name conflicts
                actual_target = _resolve_name_conflict(target)

                # Perform the move
                shutil.move(str(source), str(actual_target))
                status["moved"] += 1

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

            # Log to operation_log regardless of success/failure
            now = datetime.now(tz=timezone.utc).isoformat()
            await db.execute(
                """
                INSERT INTO operation_log
                    (batch_id, operation_type, source_path, target_path, timestamp, status)
                VALUES (?, 'MOVE', ?, ?, ?, ?)
                """,
                (batch_id, str(source), str(actual_target), now, op_status),
            )
            await db.commit()

        status["done"] = True

    except Exception as exc:
        status["errors"].append(f"Unerwarteter Fehler: {exc}")
        status["done"] = True
    finally:
        await db.close()

    # Clean up cache after execution
    _batch_cache.pop(batch_id, None)
