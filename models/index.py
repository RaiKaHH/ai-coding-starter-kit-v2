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
    status: str                     # 'running' | 'completed' | 'failed'
    processed_count: int
    total_count: int


class YamlExportResponse(BaseModel):
    """Returned when user clicks 'Generate rules for PROJ-2'."""
    content: str        # full YAML string
    filename: str       # suggested filename, e.g. 'structure_rules.yaml'
