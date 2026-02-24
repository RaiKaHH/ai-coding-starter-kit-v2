"""
Pydantic models for PROJ-6: KI-Integrations-Schicht (AI Gateway).
"""
from typing import Literal

from pydantic import BaseModel, Field, SecretStr


AIProvider = Literal["ollama", "mistral", "openai"]


# --------------------------------------------------------------------------- #
# Settings (stored in DB settings table)                                       #
# --------------------------------------------------------------------------- #

class AISettingsUpdate(BaseModel):
    """Request body for PUT /ai/settings."""
    provider: AIProvider = "ollama"
    model_name: str = Field("llama3", description="Model identifier, e.g. 'llama3', 'mistral'")
    ollama_url: str = Field("http://localhost:11434", description="Ollama API base URL")
    api_key: SecretStr | None = Field(None, description="Cloud API key (stored in .env, not DB)")


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
