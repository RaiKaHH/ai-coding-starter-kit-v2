"""
Pydantic models for PROJ-3: KI-gestuetzter Datei-Umbenenner.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


RenameMode = Literal["fast", "smart"]


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class RenameRequest(BaseModel):
    """Request body for POST /rename/preview."""
    scan_id: str = Field(..., min_length=1, description="UUID of the scan to rename files from")
    mode: RenameMode = Field("fast", description="'fast' = metadata only; 'smart' = AI content analysis")
    file_ids: list[int] = Field(..., description="IDs from scan_files to process")

    @field_validator("file_ids")
    @classmethod
    def validate_file_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("Mindestens eine Datei-ID erforderlich.")
        if len(v) > 500:
            raise ValueError("Maximal 500 Dateien pro Vorschau.")
        return v


class RenameExecuteItem(BaseModel):
    """One confirmed row from the preview, possibly with user override."""
    scan_file_id: int
    new_filename: str = Field(..., min_length=1, max_length=255)

    @field_validator("new_filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        """Reject obviously invalid filenames."""
        v = v.strip()
        if not v:
            raise ValueError("Dateiname darf nicht leer sein.")
        # Reject path separators
        if "/" in v or "\\" in v:
            raise ValueError("Dateiname darf keine Pfadtrenner enthalten.")
        # Reject null bytes
        if "\x00" in v:
            raise ValueError("Dateiname darf keine Null-Bytes enthalten.")
        return v


class RenameExecuteRequest(BaseModel):
    """Request body for POST /rename/execute."""
    batch_id: str = Field(..., min_length=1)
    mode: RenameMode = Field("fast", description="'fast' or 'smart' -- stored in operation_log")
    items: list[RenameExecuteItem]


# --------------------------------------------------------------------------- #
# Responses                                                                    #
# --------------------------------------------------------------------------- #

class RenamePreviewItem(BaseModel):
    scan_file_id: int
    current_name: str
    found_date: str | None      # YYYY-MM-DD -- from AI / EXIF / OS fallback chain
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
