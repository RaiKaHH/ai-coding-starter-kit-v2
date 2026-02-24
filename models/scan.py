"""
Pydantic models for PROJ-1: Verzeichnis-Scanner.
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from utils.paths import SafePath


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _human_readable_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string like '4,2 MB'."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size_bytes /= 1024.0
        if size_bytes < 1024.0 or unit == "TB":
            # German locale: comma as decimal separator
            formatted = f"{size_bytes:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"{formatted} {unit}"
    return f"{size_bytes} B"


# --------------------------------------------------------------------------- #
# Requests                                                                     #
# --------------------------------------------------------------------------- #

class ScanRequest(BaseModel):
    source_path: SafePath = Field(..., description="Absolute path of the folder to scan")
    recursive: bool = Field(True, description="Scan sub-folders recursively")


class ScanFilterParams(BaseModel):
    """Query params for filtering / sorting / paginating the scan result."""
    extension: str | None = Field(None, description="Filter by extension, e.g. '.pdf'")
    date_from: datetime | None = Field(None, description="Erstellungsdatum von")
    date_to: datetime | None = Field(None, description="Erstellungsdatum bis")
    sort_by: Literal["name", "size", "type", "created_at", "modified_at"] = "name"
    sort_order: Literal["asc", "desc"] = "asc"
    page: int = Field(1, ge=1, description="Page number (1-based)")
    page_size: int = Field(100, ge=1, le=1000, description="Items per page")


# Keep old name as alias for backward compat
ScanFilterRequest = ScanFilterParams


# --------------------------------------------------------------------------- #
# DB row -> response                                                           #
# --------------------------------------------------------------------------- #

class ScanFile(BaseModel):
    id: int
    scan_id: str
    name: str
    path: str
    size_bytes: int
    mime_type: str | None
    created_at: str | None
    modified_at: str | None
    is_symlink: bool
    access_denied: bool

    # Human-readable size, computed on serialisation
    size_human: str = ""

    @model_validator(mode="after")
    def compute_size_human(self) -> "ScanFile":
        if not self.size_human:
            self.size_human = _human_readable_size(self.size_bytes)
        return self


class ScanStatus(BaseModel):
    scan_id: str
    status: Literal["running", "completed", "failed"]
    file_count: int
    total_count: int = 0  # BUG-2: total files found by walk; 0 until walk completes
    source_path: str
    created_at: str


class ScanResult(BaseModel):
    scan_id: str
    status: Literal["running", "completed", "failed"]
    file_count: int
    files: list[ScanFile] = []
    page: int = 1
    page_size: int = 100
    total_filtered: int = 0
