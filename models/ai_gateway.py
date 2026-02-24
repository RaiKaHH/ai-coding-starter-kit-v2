"""
Pydantic models for PROJ-6: KI-Integrations-Schicht (AI Gateway).
"""
import ipaddress
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, field_validator


AIProvider = Literal["ollama", "mistral", "openai"]


# --------------------------------------------------------------------------- #
# Settings (stored in DB settings table)                                       #
# --------------------------------------------------------------------------- #

class AISettingsUpdate(BaseModel):
    """Request body for PUT /ai/settings."""
    provider: AIProvider = "ollama"
    model_name: str = Field(
        "llama3",
        min_length=1,
        max_length=100,
        description="Model identifier, e.g. 'llama3', 'mistral'",
    )
    ollama_url: str = Field("http://localhost:11434", description="Ollama API base URL")
    api_key: SecretStr | None = Field(None, description="Cloud API key (stored in .env, not DB)")

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        """BUG-4: Reject empty, HTML, and overlong model names."""
        if not re.match(r"^[a-zA-Z0-9._:/-]+$", v):
            raise ValueError(
                "Modell-Name darf nur Buchstaben, Ziffern sowie . _ : / - enthalten."
            )
        return v

    @field_validator("ollama_url")
    @classmethod
    def validate_ollama_url(cls, v: str) -> str:
        """BUG-3: Allow only localhost and private/loopback IPs (SSRF protection)."""
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("Ollama URL muss http:// oder https:// verwenden.")
        hostname = parsed.hostname
        if hostname is None:
            raise ValueError("Ungültige Ollama URL.")
        if hostname.lower() == "localhost":
            return v
        try:
            addr = ipaddress.ip_address(hostname)
        except ValueError:
            raise ValueError(
                "Ollama URL: Nur 'localhost' oder private IP-Adressen erlaubt (SSRF-Schutz)."
            )
        if not (addr.is_loopback or addr.is_private):
            raise ValueError(
                "Ollama URL: Nur 'localhost' oder private IP-Adressen erlaubt (SSRF-Schutz)."
            )
        return v

    @field_validator("api_key", mode="before")
    @classmethod
    def sanitize_api_key(cls, v: object) -> object:
        """BUG-2: Strip newlines and null bytes to prevent .env injection."""
        if v is None:
            return v
        if isinstance(v, str):
            return v.replace("\n", "").replace("\r", "").replace("\x00", "")
        return v


class AISettingsResponse(BaseModel):
    """Safe read-back – never returns the raw api_key."""
    provider: AIProvider
    model_name: str
    ollama_url: str
    api_key_set: bool   # True if a key has been configured, False otherwise


# --------------------------------------------------------------------------- #
# AI Test                                                                      #
# --------------------------------------------------------------------------- #

class AITestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None


# --------------------------------------------------------------------------- #
# Internal AI call models (used by core/ai_service.py, not exposed as API)    #
# --------------------------------------------------------------------------- #

class AIAnalysisRequest(BaseModel):
    """Input for core/ai_service.py internal methods."""
    text: str = Field(..., description="Content snippet to analyse (max ~3000 chars)")
    context: list[str] = Field(
        default_factory=list,
        description="Known folder paths / keywords for grounding the response",
    )


class AIFolderSuggestion(BaseModel):
    """Expected LLM JSON output for folder suggestion (PROJ-8)."""
    zielordner: str
    begruendung: str


class AIRenameResult(BaseModel):
    """Expected LLM JSON output for rename (PROJ-3)."""
    datum: str          # YYYY-MM-DD
    dateiname: str      # snake_case, max 5 words, no extension


class AIFolderProfile(BaseModel):
    """Expected LLM JSON output for folder profiling (PROJ-4)."""
    zweck: str
    keywords: list[str]
    empfohlene_regel: str   # e.g. '*.pdf' or 'RE-*.pdf'
