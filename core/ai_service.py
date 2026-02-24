"""
PROJ-6: KI-Integrations-Schicht (AI Gateway) – Business Logic.

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
