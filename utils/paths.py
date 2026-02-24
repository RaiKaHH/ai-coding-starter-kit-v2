"""
Path validation helpers.
Prevents path traversal attacks on all user-supplied path inputs.
Used as a Pydantic validator and independently in route handlers.
"""
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator


# Directories that should never be scannable (system-critical paths)
BLOCKED_PREFIXES = (
    "/System",
    "/usr",
    "/bin",
    "/sbin",
    "/private/var",
)


def validate_safe_path(value: str) -> Path:
    """
    Resolve the path and ensure it:
    - is absolute after resolution
    - does not escape via '..' tricks
    - does not point to system-critical directories
    Raises ValueError on invalid input (Pydantic catches this).
    """
    if not value or not value.strip():
        raise ValueError("Pfad darf nicht leer sein.")

    # BUG-8: reject relative paths *before* resolve() silently maps them to CWD
    stripped = value.strip()
    if not stripped.startswith("/") and not stripped.startswith("~"):
        raise ValueError(
            f"Pfad muss absolut sein (mit / beginnen) oder ~ nutzen. "
            f"Relativer Pfad nicht erlaubt: {value!r}"
        )

    p = Path(value).expanduser().resolve()

    # Must be absolute after resolution
    if not p.is_absolute():
        raise ValueError(f"Pfad muss absolut sein: {value}")

    # Reject '..' in the original input (path traversal attempt)
    if ".." in Path(value).parts:
        raise ValueError(f"Path-Traversal nicht erlaubt: {value}")

    # Block system directories
    p_str = str(p)
    for blocked in BLOCKED_PREFIXES:
        if p_str.startswith(blocked):
            raise ValueError(
                f"Zugriff auf Systemverzeichnis nicht erlaubt: {blocked}"
            )

    return p


# Reusable Pydantic-annotated type for any path input field
SafePath = Annotated[str, AfterValidator(validate_safe_path)]
