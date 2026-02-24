"""
Pydantic models for PROJ-3: KI-gestützter Datei-Umbenenner.
"""
from typing import Literal

from pydantic import BaseModel, Field

from utils.paths import SafePath


RenameMode = Literal["fast", "smart"]


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class RenameRequest(BaseModel):
    scan_id: str
    mode: RenameMode = Field("fast", description="'fast' = metadata only; 'smart' = AI content analysis")
    file_ids: list[int] = Field(..., description="IDs from scan_files to process")


class RenameExecuteItem(BaseModel):
    """One confirmed row from the preview, possibly with user override."""
    scan_file_id: int
    new_filename: str   # final name after user edits (may equal ai_suggestion)


class RenameExecuteRequest(BaseModel):
    batch_id: str
    items: list[RenameExecuteItem]


# --------------------------------------------------------------------------- #
# Responses                                                                    #
# --------------------------------------------------------------------------- #

class RenamePreviewItem(BaseModel):
    scan_file_id: int
    current_name: str
    found_date: str | None      # YYYY-MM-DD – from AI / EXIF / OS fallback chain
    date_source: Literal["ai", "exif", "os"] | None
    ai_suggestion: str | None   # populated only in 'smart' mode
    new_filename: str           # full target name: YYYY-MM-DD_description.ext
    editable: bool = True       # user can override in preview table


class RenamePreviewResponse(BaseModel):
    batch_id: str
    mode: RenameMode
    items: list[RenamePreviewItem]


class RenameExecuteResult(BaseModel):
    batch_id: str
    renamed_count: int
    failed_count: int
    errors: list[str] = []
