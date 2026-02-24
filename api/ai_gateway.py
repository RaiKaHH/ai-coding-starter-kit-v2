"""
API routes for PROJ-6: KI-Integrations-Schicht.

Endpoints:
  GET  /ai/settings         -- HTML settings page (Jinja2)
  GET  /ai/settings/data    -- current AI provider config as JSON (no raw key)
  PUT  /ai/settings/data    -- update provider, model, ollama URL
  POST /ai/test             -- test connectivity to the configured LLM
"""
import logging
import os
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.ai_service import (
    AIServiceError,
    load_settings,
    save_settings,
    test_connection,
)
from models.ai_gateway import AISettingsResponse, AISettingsUpdate, AITestResponse

logger = logging.getLogger("ai_gateway")

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --------------------------------------------------------------------------- #
# Simple in-memory rate limiter (BUG-5)                                       #
# --------------------------------------------------------------------------- #

_RATE_WINDOW_S = 60.0   # sliding window in seconds
_RATE_MAX_TEST = 10     # max /ai/test calls per window
_RATE_MAX_SAVE = 20     # max PUT /ai/settings/data calls per window

_test_timestamps: deque[float] = deque()
_save_timestamps: deque[float] = deque()


def _check_rate_limit(timestamps: deque[float], max_calls: int, label: str) -> None:
    """Raise HTTP 429 if more than *max_calls* have occurred in the sliding window."""
    now = time.monotonic()
    while timestamps and timestamps[0] < now - _RATE_WINDOW_S:
        timestamps.popleft()
    if len(timestamps) >= max_calls:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Zu viele Anfragen an {label}. "
                f"Maximal {max_calls} Anfragen pro Minute erlaubt."
            ),
        )
    timestamps.append(now)


# --------------------------------------------------------------------------- #
# HTML page                                                                   #
# --------------------------------------------------------------------------- #

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render the AI settings page."""
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "page_title": "KI-Einstellungen"},
    )


# --------------------------------------------------------------------------- #
# JSON API                                                                    #
# --------------------------------------------------------------------------- #

@router.get("/settings/data")
async def get_settings() -> AISettingsResponse:
    """Return current AI configuration. Never returns the raw API key."""
    try:
        return await load_settings()
    except Exception as exc:
        logger.error("Fehler beim Laden der Einstellungen: %s", exc)
        raise HTTPException(status_code=500, detail="Einstellungen konnten nicht geladen werden.")


@router.put("/settings/data")
async def update_settings(body: AISettingsUpdate) -> AISettingsResponse:
    """
    Update AI provider settings.

    - Provider, model_name, and ollama_url are persisted in SQLite.
    - If an api_key is provided, it is written to the .env file (never to DB).
    """
    _check_rate_limit(_save_timestamps, _RATE_MAX_SAVE, "/ai/settings/data")
    try:
        # Persist non-secret settings to DB
        await save_settings(
            provider=body.provider,
            model_name=body.model_name,
            ollama_url=body.ollama_url,
        )

        # If a cloud API key was supplied, write it to .env
        if body.api_key is not None:
            key_value = body.api_key.get_secret_value()
            if key_value:
                _write_env_key(body.provider, key_value)

        return await load_settings()

    except Exception as exc:
        logger.error("Fehler beim Speichern der Einstellungen: %s", exc)
        raise HTTPException(status_code=500, detail="Einstellungen konnten nicht gespeichert werden.")


@router.post("/test")
async def test_connection_endpoint() -> AITestResponse:
    """Test connectivity to the configured AI provider."""
    _check_rate_limit(_test_timestamps, _RATE_MAX_TEST, "/ai/test")
    try:
        success, message, latency_ms = await test_connection()
        return AITestResponse(
            success=success,
            message=message,
            latency_ms=round(latency_ms, 1) if latency_ms is not None else None,
        )
    except AIServiceError as exc:
        return AITestResponse(
            success=False,
            message=str(exc),
            latency_ms=None,
        )
    except Exception as exc:
        logger.error("Fehler beim Verbindungstest: %s", exc)
        return AITestResponse(
            success=False,
            message=f"Unerwarteter Fehler: {type(exc).__name__}",
            latency_ms=None,
        )


# --------------------------------------------------------------------------- #
# .env file helper                                                            #
# --------------------------------------------------------------------------- #

def _write_env_key(provider: str, key_value: str) -> None:
    """
    Write or update an API key in the project .env file.
    Only MISTRAL_API_KEY or OPENAI_API_KEY are supported.
    The key is never logged.
    """
    env_var_map = {
        "mistral": "MISTRAL_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_var = env_var_map.get(provider)
    if not env_var:
        return  # Ollama does not need a key

    # BUG-2 fix: strip newlines and null bytes to prevent .env injection
    key_value = key_value.replace("\n", "").replace("\r", "").replace("\x00", "")
    if not key_value:
        return  # nothing to write after sanitization

    env_path = Path(".env")
    lines: list[str] = []

    # Read existing .env if it exists
    if env_path.exists():
        lines = env_path.read_text().splitlines()

    # Replace existing key or append
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{env_var}=") or stripped.startswith(f"export {env_var}="):
            lines[i] = f"{env_var}={key_value}"
            found = True
            break

    if not found:
        lines.append(f"{env_var}={key_value}")

    env_path.write_text("\n".join(lines) + "\n")

    # Also set in current process environment so it takes effect immediately
    os.environ[env_var] = key_value

    logger.info("API-Key fuer %s in .env aktualisiert.", provider)
