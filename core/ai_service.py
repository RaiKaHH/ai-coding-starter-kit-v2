"""
PROJ-6: KI-Integrations-Schicht (AI Gateway) -- Business Logic.

Responsibilities:
- Unified async interface: ai_service.ask_json(prompt, response_model)
- Ollama backend: HTTP POST to http://localhost:11434/api/generate
  with format="json" parameter
- Cloud fallback: Mistral / OpenAI via httpx (no LangChain)
- Enforce structured JSON output; validate response with Pydantic
- Retry up to 2 times on malformed JSON (hallucination guard)
- Exponential backoff on HTTP 429 (cloud rate limits)
- Global asyncio.Semaphore(3) to cap concurrent requests app-wide
- Never log file contents or API keys; only log latency metadata
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import TypeVar

import httpx
from pydantic import BaseModel

from models.ai_gateway import AIProvider, AISettingsResponse
from utils.db import get_db

logger = logging.getLogger("ai_service")

# Type variable for generic Pydantic response models
T = TypeVar("T", bound=BaseModel)

# --------------------------------------------------------------------------- #
# Global concurrency limiter: max 3 parallel AI requests app-wide             #
# --------------------------------------------------------------------------- #
_semaphore = asyncio.Semaphore(3)

# Max retries for malformed JSON responses
MAX_RETRIES = 3  # 1 initial + 2 retries

# httpx timeout configuration (generous for local LLMs)
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)


# --------------------------------------------------------------------------- #
# Custom exception                                                            #
# --------------------------------------------------------------------------- #

class AIServiceError(Exception):
    """Raised when the AI service cannot fulfil a request."""

    def __init__(self, message: str, code: str = "UNKNOWN"):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- #
# Settings helpers                                                            #
# --------------------------------------------------------------------------- #

async def load_settings() -> AISettingsResponse:
    """
    Load AI settings from the SQLite settings table.
    Returns defaults if no settings have been saved yet.
    """
    db = await get_db()
    try:
        defaults = {
            "ai.provider": "ollama",
            "ai.model_name": "llama3",
            "ai.ollama_url": "http://localhost:11434",
        }
        result: dict[str, str] = {}
        for key, default in defaults.items():
            cursor = await db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            result[key] = row["value"] if row else default

        provider: AIProvider = result["ai.provider"]  # type: ignore[assignment]
        api_key_set = _has_api_key(provider)

        return AISettingsResponse(
            provider=provider,
            model_name=result["ai.model_name"],
            ollama_url=result["ai.ollama_url"],
            api_key_set=api_key_set,
        )
    finally:
        await db.close()


async def save_settings(
    provider: AIProvider,
    model_name: str,
    ollama_url: str,
) -> None:
    """Persist AI settings to the SQLite settings table."""
    db = await get_db()
    try:
        now = datetime.now(tz=timezone.utc).isoformat()
        pairs = {
            "ai.provider": provider,
            "ai.model_name": model_name,
            "ai.ollama_url": ollama_url,
        }
        for key, value in pairs.items():
            await db.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                               updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
        await db.commit()
    finally:
        await db.close()


def _has_api_key(provider: AIProvider) -> bool:
    """Check whether the relevant API key environment variable is set."""
    if provider == "mistral":
        return bool(os.getenv("MISTRAL_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    # Ollama does not need an API key
    return True


def _get_api_key(provider: AIProvider) -> str:
    """
    Retrieve the API key from the environment.
    Raises AIServiceError if the key is missing.
    """
    if provider == "mistral":
        key = os.getenv("MISTRAL_API_KEY")
        if not key:
            raise AIServiceError(
                "MISTRAL_API_KEY ist nicht in .env gesetzt.",
                code="MISSING_API_KEY",
            )
        return key
    if provider == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise AIServiceError(
                "OPENAI_API_KEY ist nicht in .env gesetzt.",
                code="MISSING_API_KEY",
            )
        return key
    return ""


# --------------------------------------------------------------------------- #
# Ollama backend                                                              #
# --------------------------------------------------------------------------- #

async def _call_ollama(
    prompt: str,
    model: str,
    base_url: str,
) -> str:
    """
    Send a generate request to the local Ollama instance.
    Returns the raw response text from the model.
    """
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "")
    except httpx.ConnectError:
        raise AIServiceError(
            "Ollama ist nicht erreichbar. Bitte starte Ollama zuerst.",
            code="OLLAMA_UNREACHABLE",
        )
    except httpx.HTTPStatusError as exc:
        raise AIServiceError(
            f"Ollama hat mit Status {exc.response.status_code} geantwortet.",
            code="OLLAMA_ERROR",
        )


# --------------------------------------------------------------------------- #
# Cloud backends (Mistral / OpenAI)                                           #
# --------------------------------------------------------------------------- #

async def _call_cloud(
    prompt: str,
    model: str,
    provider: AIProvider,
) -> str:
    """
    Send a chat completion request to Mistral or OpenAI.
    Handles HTTP 429 with exponential backoff (1s, 2s, then error).
    Returns the raw response text.
    """
    api_key = _get_api_key(provider)

    if provider == "mistral":
        url = "https://api.mistral.ai/v1/chat/completions"
    else:  # openai
        url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Du bist ein Datei-Analyse-Assistent. "
                    "Antworte IMMER ausschliesslich mit validem JSON. "
                    "Kein Markdown, kein erklaernder Text."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    # Add response_format for OpenAI JSON mode
    if provider == "openai":
        payload["response_format"] = {"type": "json_object"}

    backoff_delays = [1.0, 2.0]

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(len(backoff_delays) + 1):
            try:
                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 429:
                    if attempt < len(backoff_delays):
                        delay = backoff_delays[attempt]
                        logger.warning(
                            "Rate limit (429) von %s, warte %.1fs (Versuch %d)",
                            provider,
                            delay,
                            attempt + 1,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise AIServiceError(
                        f"Rate Limit bei {provider} nach {attempt + 1} Versuchen.",
                        code="RATE_LIMIT",
                    )

                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

            except httpx.ConnectError:
                raise AIServiceError(
                    f"{provider} API ist nicht erreichbar.",
                    code="CLOUD_UNREACHABLE",
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < len(backoff_delays):
                    await asyncio.sleep(backoff_delays[attempt])
                    continue
                raise AIServiceError(
                    f"{provider} API Fehler: Status {exc.response.status_code}",
                    code="CLOUD_ERROR",
                )

    # Should not reach here, but safety net
    raise AIServiceError("Unerwarteter Fehler im Cloud-Backend.", code="CLOUD_ERROR")


# --------------------------------------------------------------------------- #
# Unified public interface                                                    #
# --------------------------------------------------------------------------- #

async def ask_json(
    prompt: str,
    response_model: type[T],
    *,
    system_hint: str | None = None,
) -> T:
    """
    Send a prompt to the configured AI provider and return a validated
    Pydantic model instance.

    - Acquires the global semaphore (max 3 concurrent requests).
    - Reads current settings from DB.
    - Dispatches to Ollama or Cloud backend.
    - Validates the JSON response against `response_model`.
    - Retries up to 2 times on invalid JSON.
    - Logs only timing metadata, never content or keys.

    Args:
        prompt: The user/system prompt for the LLM.
        response_model: A Pydantic BaseModel subclass describing expected output.
        system_hint: Optional extra system instruction prepended to the prompt.

    Returns:
        A validated instance of `response_model`.

    Raises:
        AIServiceError: On connection errors, missing keys, or exhausted retries.
    """
    async with _semaphore:
        settings = await load_settings()

        # Prepend system hint if provided
        full_prompt = prompt
        if system_hint:
            full_prompt = f"{system_hint}\n\n{prompt}"

        # Append schema description to help the LLM produce valid JSON
        schema_fields = response_model.model_json_schema().get("properties", {})
        field_desc = ", ".join(
            f'"{k}": {v.get("type", "string")}'
            for k, v in schema_fields.items()
        )
        full_prompt += (
            f"\n\nAntworte NUR mit einem JSON-Objekt mit diesen Feldern: {{{field_desc}}}"
        )

        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            start = time.monotonic()

            try:
                if settings.provider == "ollama":
                    raw = await _call_ollama(
                        full_prompt,
                        settings.model_name,
                        settings.ollama_url,
                    )
                else:
                    raw = await _call_cloud(
                        full_prompt,
                        settings.model_name,
                        settings.provider,
                    )

                elapsed_ms = (time.monotonic() - start) * 1000
                logger.info(
                    "AI-Anfrage: provider=%s, model=%s, versuch=%d, dauer=%.0fms",
                    settings.provider,
                    settings.model_name,
                    attempt + 1,
                    elapsed_ms,
                )

                # Parse JSON from the raw response
                parsed = json.loads(raw)
                result = response_model.model_validate(parsed)
                return result

            except (json.JSONDecodeError, Exception) as exc:
                # On AIServiceError (connection issues), re-raise immediately
                if isinstance(exc, AIServiceError):
                    raise

                elapsed_ms = (time.monotonic() - start) * 1000
                last_error = exc
                logger.warning(
                    "Ungueltige AI-Antwort (Versuch %d/%d, %.0fms): %s",
                    attempt + 1,
                    MAX_RETRIES,
                    elapsed_ms,
                    type(exc).__name__,
                )

                if attempt < MAX_RETRIES - 1:
                    # Add a correction hint for the next attempt
                    full_prompt += (
                        "\n\nDeine letzte Antwort war kein valides JSON. "
                        "Bitte antworte NUR mit einem JSON-Objekt."
                    )

        raise AIServiceError(
            f"Kein valides JSON nach {MAX_RETRIES} Versuchen. "
            f"Letzter Fehler: {last_error}",
            code="INVALID_JSON",
        )


async def test_connection() -> tuple[bool, str, float | None]:
    """
    Test connectivity to the configured AI provider.

    Returns:
        Tuple of (success, message, latency_ms or None).
    """
    settings = await load_settings()
    start = time.monotonic()

    try:
        if settings.provider == "ollama":
            # Simple connectivity check: hit the Ollama version endpoint
            url = f"{settings.ollama_url.rstrip('/')}/api/tags"
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                elapsed_ms = (time.monotonic() - start) * 1000

                # Check if the configured model is available
                data = resp.json()
                model_names = [
                    m.get("name", "").split(":")[0]
                    for m in data.get("models", [])
                ]
                if settings.model_name not in model_names:
                    available = ", ".join(model_names) if model_names else "keine"
                    return (
                        False,
                        f"Ollama erreichbar, aber Modell '{settings.model_name}' "
                        f"nicht gefunden. Verfuegbar: {available}",
                        elapsed_ms,
                    )

                return (
                    True,
                    f"Verbunden mit Ollama ({settings.model_name})",
                    elapsed_ms,
                )

        else:
            # Cloud provider: send a minimal chat request
            api_key = _get_api_key(settings.provider)

            if settings.provider == "mistral":
                url = "https://api.mistral.ai/v1/models"
            else:
                url = "https://api.openai.com/v1/models"

            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                resp = await client.get(url, headers=headers)
                elapsed_ms = (time.monotonic() - start) * 1000

                if resp.status_code == 401:
                    return (False, "API-Key ungueltig (401 Unauthorized).", elapsed_ms)
                resp.raise_for_status()

                return (
                    True,
                    f"Verbunden mit {settings.provider} ({settings.model_name})",
                    elapsed_ms,
                )

    except AIServiceError as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return (False, str(exc), elapsed_ms)
    except httpx.ConnectError:
        elapsed_ms = (time.monotonic() - start) * 1000
        if settings.provider == "ollama":
            return (
                False,
                "Ollama ist nicht erreichbar. Bitte starte Ollama zuerst.",
                elapsed_ms,
            )
        return (
            False,
            f"{settings.provider} API ist nicht erreichbar.",
            elapsed_ms,
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        return (False, f"Unerwarteter Fehler: {type(exc).__name__}", elapsed_ms)
