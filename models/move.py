"""
Pydantic models for PROJ-2: Struktur-basierter Datei-Verschieber.
"""
from pydantic import BaseModel, Field

from utils.paths import SafePath


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class MoveByRulesRequest(BaseModel):
    """Move using a YAML rules file."""
    scan_id: str = Field(..., description="ID of the scan to process")
    rules_path: SafePath = Field(..., description="Absolute path to structure_rules.yaml")


class MoveByPatternRequest(BaseModel):
    """Derive rules from an existing well-organised reference folder."""
    scan_id: str
    pattern_folder: SafePath = Field(..., description="Reference folder to learn structure from")


class MoveExecuteRequest(BaseModel):
    """Confirm and execute a previously generated preview batch."""
    batch_id: str
    selected_ids: list[int] = Field(
        ...,
        description="IDs of MovePreviewItem rows the user confirmed (opt-out model)",
    )


# --------------------------------------------------------------------------- #
# Responses                                                                    #
# --------------------------------------------------------------------------- #

class MovePreviewItem(BaseModel):
    id: int                     # row index in the preview list
    file_name: str
    source_path: str
    target_path: str
    rule_matched: str           # human-readable rule that triggered this match


class MovePreviewResponse(BaseModel):
    batch_id: str               # UUID – passed back to MoveExecuteRequest
    items: list[MovePreviewItem]
    unmatched_count: int = 0    # files with no matching rule


class MoveExecuteResult(BaseModel):
    batch_id: str
    moved_count: int
    failed_count: int
    errors: list[str] = []
