"""
Pydantic models for PROJ-8: Deep-AI Smart Sorting.

Request/Response models for single-file and batch AI analysis endpoints.
"""
from pydantic import BaseModel, Field

from utils.paths import SafePath


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class DeepSortRequest(BaseModel):
    """Request body for POST /deep-sort/analyse/{file_name}."""
    source_path: SafePath = Field(..., description="Absolute path to the file to analyse")
    batch_id: str = Field(..., min_length=1, max_length=100, description="Triage batch ID")
    confidence_threshold: int = Field(
        50, ge=0, le=100,
        description="Files below this confidence were flagged for AI analysis",
    )


class DeepSortBatchRequest(BaseModel):
    """Request body for POST /deep-sort/analyse-batch."""
    batch_id: str = Field(..., min_length=1, max_length=100, description="Triage batch ID")
    threshold: int = Field(
        50, ge=0, le=100,
        description="Confidence threshold: analyse all items below this",
    )


# --------------------------------------------------------------------------- #
# Responses                                                                    #
# --------------------------------------------------------------------------- #

class DeepSortResult(BaseModel):
    """Result of a single AI file analysis."""
    source_path: str
    suggested_folder: str | None = None
    reasoning: str = ""
    from_cache: bool = False
    readable: bool = True
    unsortiert_suggestion: str | None = None


class DeepSortBatchResult(BaseModel):
    """Result of batch AI analysis."""
    results: list[DeepSortResult]
    processed: int
    failed: int


class DeepSortBatchStatus(BaseModel):
    """Status of a running or completed batch AI analysis (for polling)."""
    batch_id: str
    total: int = 0
    processed: int = 0
    failed: int = 0
    done: bool = False
    results: list[DeepSortResult] = []
