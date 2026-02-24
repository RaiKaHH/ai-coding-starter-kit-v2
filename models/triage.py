"""
Pydantic models for PROJ-5: Smart Inbox Triage.
"""
from typing import Literal

from pydantic import BaseModel, Field

from utils.paths import SafePath


MatchType = Literal["strict", "fuzzy"] | None


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class TriageRequest(BaseModel):
    inbox_path: SafePath = Field(..., description="Inbox / Downloads folder to triage")
    confidence_threshold: int = Field(
        40,
        ge=0,
        le=100,
        description="Minimum fuzzy score (0-99) to show a suggestion",
    )


class TriageConfirmItem(BaseModel):
    """One confirmed row; user may have changed the suggested folder."""
    file_name: str
    source_path: str
    confirmed_folder: str   # absolute target folder path


class TriageExecuteRequest(BaseModel):
    batch_id: str
    confirmed_items: list[TriageConfirmItem]


class FeedbackRequest(BaseModel):
    """Sent when user manually corrects a folder to update folder_profiles."""
    file_name: str
    chosen_folder: SafePath


# --------------------------------------------------------------------------- #
# Responses                                                                    #
# --------------------------------------------------------------------------- #

class TriageItem(BaseModel):
    file_name: str
    source_path: str
    suggested_folder: str | None    # None = 'Nicht zugeordnet'
    confidence: int | None          # 0-100; 100 for strict matches
    match_type: MatchType
    # Multiple top candidates (shown in dropdown when confidence tied)
    alternatives: list[str] = []


class TriageResponse(BaseModel):
    batch_id: str
    items: list[TriageItem]
    unmatched_count: int


class TriageExecuteResult(BaseModel):
    batch_id: str
    moved_count: int
    failed_count: int
    errors: list[str] = []
