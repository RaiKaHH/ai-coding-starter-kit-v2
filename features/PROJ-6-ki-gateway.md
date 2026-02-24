# PROJ-6: KI-Integrations-Schicht (AI Gateway)

## Status: Geplant
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-23

## Abhängigkeiten
- Keine. (Dieses Modul ist ein Core-Service, der später von PROJ-3, PROJ-4 und PROJ-8 konsumiert wird).

## User Stories

- Als Nutzer möchte ich Ollama (lokal) als Standard-KI nutzen, damit meine sensiblen Dokumente (Rechnungen, Verträge) meinen Mac niemals verlassen.
- Als Nutzer möchte ich optional die Mistral API (oder OpenAI) als Fallback aktivieren können, falls mein Mac für Ollama zu langsam ist.
- Als Entwickler brauche ich eine einheitliche, abstrakte interne Python-API, damit ich in den anderen Modulen einfach `await ai_service.ask_json(...)` aufrufen kann, ohne mich um das zugrundeliegende LLM zu kümmern.

## Akzeptanzkriterien

- [ ] Modul `core/ai_service.py` stellt asynchrone Methoden bereit (z.B. `analyze_text`, `categorize_file`).
- [ ] **Ollama-Integration:** Native HTTP-Requests an `http://localhost:11434/api/generate`.
- [ ] **Cloud-Fallback:** Integration der Mistral API via Umgebungsvariablen (`MISTRAL_API_KEY`).
- [ ] **Strukturierter Output:** Das Gateway *erzwingt* bei jedem LLM-Aufruf ein gültiges JSON-Format als Antwort (z.B. durch Prompt-Engineering und Ollamas `format="json"` Parameter).
- [ ] Das Gateway fängt fehlerhaftes JSON (Halluzinationen) ab und führt automatisch bis zu 2 Retries durch.
- [ ] UI-Settings-Page: Eingabefeld für API-Keys, Dropdown für Modelle (z.B. `llama3`, `mistral`), Button für "Verbindung testen".
- [ ] API-Keys werden nur im `.env` File oder im macOS Keychain gespeichert, niemals unverschlüsselt in SQLite.

## Randfälle

- **Ollama down:** Der Service erkennt, wenn Ollama nicht läuft (Connection Refused) und wirft eine saubere Exception, die die UI als Warnung anzeigen kann.
- **Rate Limits:** Wenn die Mistral-API ein 429 wirft, greift ein Exponential Backoff (Warten & Neuversuch).
- **Concurrency:** Um RAM-Overflows (bei Ollama) zu verhindern, nutzt der Service intern ein `asyncio.Semaphore(3)`, sodass app-weit maximal 3 KI-Anfragen gleichzeitig laufen.

## Technische Anforderungen

- Nutzung von Pydantic v2 zur strikten Validierung der LLM-Antworten.
- Verzicht auf fette Frameworks wie `LangChain` – reines `httpx` (async) reicht für diesen Anwendungsfall völlig aus und ist viel robuster beim KI-generierten Code.
- Kein Logging von Dateiinhalten oder API-Keys. Nur Metadaten ("Anfrage dauerte 4.2s") dürfen geloggt werden.

---
## Tech Design (Solution Architect)
### Module
- `api/ai_gateway.py` – routes: GET+PUT /ai/settings/data, POST /ai/test
- `core/ai_service.py` – einheitlicher async Client für Ollama + Cloud-APIs
- `models/ai_gateway.py` – AISettingsUpdate, AISettingsResponse, AITestResponse, AIFolderSuggestion, AIRenameResult, AIFolderProfile

### Datenbank
- Tabelle `settings`: key/value für provider, model_name, ollama_url
- API-Keys werden NICHT in SQLite gespeichert; nur .env / macOS Keychain

### HTTP-Client
- httpx (async) – kein LangChain, kein OpenAI-SDK
- Ollama: POST http://localhost:11434/api/generate mit format="json"
- Cloud: MISTRAL_API_KEY aus Umgebungsvariable
- Retry-Logik: bis zu 2 Retries bei ungültigem JSON
- Exponential Backoff bei HTTP 429
- app-weites asyncio.Semaphore(3)