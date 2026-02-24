"""
Pydantic models for PROJ-4: Semantischer Struktur-Lerner & Regel-Generator.
"""
from pydantic import BaseModel, Field

from utils.paths import SafePath


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class IndexRequest(BaseModel):
    folder_path: SafePath = Field(..., description="Root folder to learn structure from")


# --------------------------------------------------------------------------- #
# Responses                                                                    #
# --------------------------------------------------------------------------- #

class FolderProfile(BaseModel):
    id: int
    folder_path: str
    primary_extension: str | None   # most common file extension in this folder
    ai_description: str | None      # LLM-generated one-liner
    keywords: list[str]             # parsed from JSON column
    file_count: int
    indexed_at: str                 # ISO-8601


class IndexStatus(BaseModel):
    """Polling response for the async indexing background task."""
    status: str                     # 'idle' | 'running' | 'completed' | 'failed'
    processed_count: int
    total_count: int
    error: str | None = None


class YamlExportResponse(BaseModel):
    """Returned when user clicks 'Generate rules for PROJ-2'."""
    content: str        # full YAML string
    filename: str       # suggested filename, e.g. 'structure_rules.yaml'


# --------------------------------------------------------------------------- #
# AI response model (structured LLM output)                                    #
# --------------------------------------------------------------------------- #

class AIFolderProfile(BaseModel):
    """
    Pydantic model for the structured JSON response from the LLM.
    Used by ai_service.ask_json() to validate and parse the AI output.
    """
    zweck: str = Field(..., description="Purpose of this folder, e.g. 'Steuerdokumente 2023'")
    keywords: list[str] = Field(
        ...,
        max_length=5,
        description="Up to 5 keywords describing the folder content",
    )
    empfohlene_regel: str = Field(
        ...,
        description="Suggested glob/filename pattern, e.g. '*.pdf' or 'RE-*.pdf'",
    )
