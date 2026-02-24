# PROJ-6: KI-Integrations-Schicht (AI Gateway)

## Status: Fertig
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-24

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

### Architektur-Übersicht

PROJ-6 ist eine reine Service-Schicht — kein Feature, das der Nutzer direkt benutzt,
sondern die gemeinsame Grundlage aller KI-Features (PROJ-3, PROJ-4, PROJ-8).
Es gibt zwei Teile: den internen Service (`core/ai_service.py`) und die
Einstellungs-UI für den Nutzer (`/ai/settings`).

```
Konsumenten (PROJ-3, PROJ-4, PROJ-8)
      |  await ai_service.ask_json(prompt, ResponseModel)
      v
┌─────────────────────────────────────────────────────┐
│            core/ai_service.py                        │
│                                                      │
│  asyncio.Semaphore(3)  ← max. 3 parallele Anfragen  │
│                                                      │
│  ┌─────────────────┐   ┌──────────────────────────┐ │
│  │  Ollama-Backend │   │  Cloud-Backend            │ │
│  │  (Standard)     │   │  (Mistral / OpenAI)       │ │
│  │                 │   │                           │ │
│  │  httpx POST     │   │  httpx POST               │ │
│  │  localhost:11434│   │  api.mistral.ai           │ │
│  │  format="json"  │   │  MISTRAL_API_KEY aus .env │ │
│  └─────────────────┘   └──────────────────────────┘ │
│                                                      │
│  Pydantic-Validierung ──── ungültiges JSON ──> Retry │
│  (max. 2 Versuche)                                   │
└─────────────────────────────────────────────────────┘
      |
      v  validiertes Python-Objekt (z.B. AIRenameResult)
Konsumenten nutzen das Ergebnis direkt weiter
```

---

### Modul-Struktur (bereits als Skeleton vorhanden)

| Datei | Verantwortlichkeit |
|-------|--------------------|
| `core/ai_service.py` | Unified async client — zentrales `ask_json()`, Ollama-/Cloud-Adaptern, Retry-Logik, Semaphore |
| `api/ai_gateway.py` | HTTP-Routen für Settings-Page und Verbindungstest |
| `models/ai_gateway.py` | Pydantic-Modelle für Settings, Test-Antwort und alle Consumer-Outputs |
| `templates/settings.html` | Jinja2+Alpine.js UI für Provider-Konfiguration |

---

### Settings UI — Komponenten-Baum

```
Settings Page  GET /ai/settings
└── Formular-Card (x-data: Alpine.js hält Zustand + Ladestatus)
    ├── Provider-Auswahl (Radio-Buttons)
    │   ├── ◉ Ollama  (lokal, Standard)
    │   ├── ○ Mistral (Cloud)
    │   └── ○ OpenAI  (Cloud)
    │
    ├── Modell-Konfiguration
    │   ├── Modell-Name   (Text-Input, z.B. "llama3", "mistral")
    │   └── [nur Ollama]  Basis-URL (default: http://localhost:11434)
    │
    ├── API-Key-Bereich (x-show: provider !== 'ollama')
    │   └── API-Key     (Passwort-Input, niemals vorausgefüllt)
    │       └── Hinweis: "Wird nur in .env gespeichert, nicht in der DB"
    │
    ├── "Einstellungen speichern"-Button
    │   └── Ladespinner während PUT /ai/settings/data
    │
    └── Verbindungstest-Bereich
        ├── "Verbindung testen"-Button
        │   └── POST /ai/test
        ├── [Erfolg]  Grüne Box: "✓ Verbunden · 842 ms"
        └── [Fehler]  Rote Box:  "✗ Ollama läuft nicht. Starte Ollama zuerst."
```

---

### Interner Aufruf-Ablauf (`ask_json`)

```
Konsument ruft ask_json(prompt, ResponseModel) auf
    │
    ├─ Semaphore verfügbar? ──nein──> warten (kein Fehler, nur queuen)
    │
    ├─ Einstellungen aus DB lesen (provider, model_name, ollama_url)
    │
    ├─ [Ollama]   httpx POST /api/generate, format="json"
    │  [Cloud]    httpx POST cloud-endpoint, Bearer Token aus .env
    │
    ├─ Antwort erhalten
    │   ├─ JSON gültig?  ──ja──> Pydantic-Validierung gegen ResponseModel
    │   │                         ├─ valide?  ──> Ergebnis zurückgeben ✓
    │   │                         └─ invalid? ──> Retry (Versuch 1 / 2)
    │   │
    │   ├─ HTTP 429?  ──> Exponential Backoff (1s → 2s → Fehler)
    │   └─ ConnectionRefused?  ──> AIServiceError("Ollama nicht erreichbar")
    │
    └─ Nach 2 Retries: AIServiceError("Kein valides JSON nach 3 Versuchen")
```

---

### Datenbank: `settings`-Tabelle

Bereits in `utils/db.py` angelegt als key/value-Store:

| Key | Beispielwert | Beschreibung |
|-----|-------------|--------------|
| `ai.provider` | `"ollama"` | Aktiver Provider |
| `ai.model_name` | `"llama3"` | Modell-Bezeichner |
| `ai.ollama_url` | `"http://localhost:11434"` | Ollama-Endpunkt |

**API-Keys werden NICHT in SQLite gespeichert.**
Sie kommen ausschließlich aus `.env` via `os.getenv("MISTRAL_API_KEY")`.

---

### Fehler-Zustände und Verhalten

| Fehler | Verhalten im Service | Darstellung in der UI |
|--------|---------------------|----------------------|
| Ollama nicht gestartet | `AIServiceError` mit Code `OLLAMA_UNREACHABLE` | Rote Warnung mit Anleitung |
| Ungültiges JSON (Halluzination) | Bis zu 2 Retries, dann `AIServiceError` | Fehlermeldung im aufrufenden Feature |
| Cloud-Rate-Limit (HTTP 429) | Exponential Backoff (1s, 2s), dann Fehler | Nur Metadaten-Log (keine Inhalte) |
| Semaphore voll (>3 parallel) | Anfrage wartet in Queue | Kein UI-Feedback nötig |
| Cloud-Key nicht in `.env` | `AIServiceError` mit Code `MISSING_API_KEY` | Settings-Page zeigt Hinweis |

---

### Consumer-Modelle (wie andere Features das Gateway nutzen)

Alle Consumer-Antwortmodelle sind bereits in `models/ai_gateway.py` definiert:

| Modell | Genutzt von | Felder |
|--------|-------------|--------|
| `AIRenameResult` | PROJ-3 Umbenenner | `datum` (YYYY-MM-DD), `dateiname` (snake_case) |
| `AIFolderSuggestion` | PROJ-8 Deep Sort | `zielordner`, `begruendung` |
| `AIFolderProfile` | PROJ-4 Lerner | `zweck`, `keywords[]`, `empfohlene_regel` |

---

### Abhängigkeiten (neu in `requirements.txt`)

| Paket | Zweck |
|-------|-------|
| `httpx[asyncio]` | Async HTTP-Client für Ollama + Cloud-APIs |
| `python-dotenv` | `.env`-Datei für API-Keys einlesen |

*(Kein LangChain, kein OpenAI-SDK — nur httpx)*

---

### API-Endpunkte

| Methode | Pfad | Zweck |
|---------|------|-------|
| `GET` | `/ai/settings` | HTML-Seite für Einstellungen (Jinja2) |
| `GET` | `/ai/settings/data` | Aktuelle Config als JSON (kein API-Key) |
| `PUT` | `/ai/settings/data` | Config speichern (provider, model, URL) |
| `POST` | `/ai/test` | Verbindung testen — gibt Latenz oder Fehler zurück |

---

## QA Test Results

**Tested:** 2026-02-24
**App URL:** http://127.0.0.1:8111
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: Modul `core/ai_service.py` stellt asynchrone Methoden bereit
- [x] `ask_json()` ist vorhanden und async (`async def ask_json(...)`)
- [x] `test_connection()` ist vorhanden und async
- [x] `load_settings()` und `save_settings()` sind async
- [ ] BUG: Die im AC genannten Methoden `analyze_text` und `categorize_file` existieren nicht. Stattdessen gibt es die generische `ask_json(prompt, response_model)` Methode, die den gleichen Zweck erfuellt. Das ist architektonisch besser, aber die Spec-Benennung stimmt nicht ueberein.

**Ergebnis: PASS** (funktional erfuellt, nur Namensabweichung zur Spec)

#### AC-2: Ollama-Integration mit Native HTTP-Requests
- [x] `_call_ollama()` sendet POST an `{base_url}/api/generate`
- [x] Default-URL ist `http://localhost:11434`
- [x] `format="json"` Parameter wird mitgesendet
- [x] `stream: False` ist gesetzt
- [x] Verbindungstest (`POST /ai/test`) mit laufendem Ollama erfolgreich (Antwort: `"Verbunden mit Ollama (llama3)"`, 36.7ms)

**Ergebnis: PASS**

#### AC-3: Cloud-Fallback (Mistral API via Umgebungsvariablen)
- [x] `_call_cloud()` unterstuetzt Mistral und OpenAI
- [x] API-Key wird via `os.getenv("MISTRAL_API_KEY")` gelesen
- [x] Bearer-Token wird im Authorization-Header gesendet
- [x] Chat-Completions-Endpoint wird korrekt angesprochen
- [x] OpenAI JSON-Mode (`response_format: json_object`) wird gesetzt

**Ergebnis: PASS**

#### AC-4: Strukturierter Output (JSON erzwungen)
- [x] Ollama: `format="json"` Parameter in jedem Request
- [x] Cloud: System-Prompt erzwingt JSON ("Antworte IMMER ausschliesslich mit validem JSON")
- [x] OpenAI: `response_format: json_object` wird gesetzt
- [x] Schema-Felder werden am Prompt-Ende angehaengt
- [x] Pydantic `model_validate()` validiert die Antwort gegen das Response-Modell

**Ergebnis: PASS**

#### AC-5: Retry bei fehlerhaftem JSON (bis zu 2 Retries)
- [x] `MAX_RETRIES = 3` (1 initial + 2 Retries) -- korrekt
- [x] Bei `json.JSONDecodeError` oder Pydantic `ValidationError` wird erneut versucht
- [x] Nach jedem Fehlversuch wird ein Korrekturhinweis an den Prompt angehaengt
- [x] Nach 3 Versuchen wird `AIServiceError` mit Code `INVALID_JSON` geworfen
- [x] `AIServiceError` (Verbindungsfehler) wird sofort re-raised, nicht erneut versucht

**Ergebnis: PASS**

#### AC-6: UI-Settings-Page
- [x] `GET /ai/settings` liefert HTML-Seite (HTTP 200)
- [x] Provider-Auswahl als Radio-Buttons (Ollama, Mistral, OpenAI)
- [x] Modell-Name Eingabefeld vorhanden
- [x] Ollama Basis-URL Feld nur sichtbar wenn Provider = Ollama (`x-show`)
- [x] API-Key Eingabefeld nur sichtbar wenn Provider != Ollama (`x-show`)
- [x] API-Key ist ein `type="password"` Feld
- [x] "Einstellungen speichern" Button mit Ladespinner
- [x] "Verbindung testen" Button mit Erfolgs-/Fehler-Anzeige
- [x] Latenz wird bei erfolgreichem Test angezeigt
- [x] BUG-1 FIXED: Dropdown fuer Modelle implementiert (providerabhängige Optionen per Alpine.js `get modelOptions()`)

**Ergebnis: PASS**

#### AC-7: API-Keys nur in `.env` gespeichert, nie in SQLite
- [x] `_write_env_key()` schreibt Keys in `.env` Datei
- [x] `AISettingsResponse` enthaelt nur `api_key_set: bool`, nie den Key selbst
- [x] `GET /ai/settings/data` gibt keinen API-Key zurueck (verifiziert: Feld fehlt in Response)
- [x] SQLite `settings`-Tabelle speichert nur `ai.provider`, `ai.model_name`, `ai.ollama_url`

**Ergebnis: PASS**

### Edge Cases Status

#### EC-1: Ollama down (Connection Refused)
- [x] Getestet mit falscher URL (`http://localhost:99999`)
- [x] Verbindungstest gibt `success: false` mit Nachricht "Ollama ist nicht erreichbar. Bitte starte Ollama zuerst." zurueck
- [x] Kein Crash, saubere Fehlerbehandlung

**Ergebnis: PASS**

#### EC-2: Rate Limits (HTTP 429)
- [x] Code implementiert Exponential Backoff: 1s, 2s Verzoegerung
- [x] Nach 3 Versuchen wird `AIServiceError` mit Code `RATE_LIMIT` geworfen
- [x] Doppelte 429-Behandlung: sowohl im `resp.status_code` Check als auch im `HTTPStatusError` Handler

**Ergebnis: PASS** (Code-Review, kein Live-Test moeglich ohne echte Rate-Limits)

#### EC-3: Concurrency (asyncio.Semaphore)
- [x] `_semaphore = asyncio.Semaphore(3)` auf Modul-Ebene
- [x] `ask_json()` nutzt `async with _semaphore:` Block
- [x] Ueberschuessige Anfragen warten in der Queue (kein Fehler)

**Ergebnis: PASS** (Code-Review)

### Security Audit Results

#### SEC-1: .env-Injection ueber API-Key (KRITISCH)
- [x] **BUG-2 FIXED:** `_write_env_key()` (api/ai_gateway.py) bereinigt `key_value` vor dem Schreiben via `.replace("\n","").replace("\r","").replace("\x00","")`. Zusaetzlich sanitiert ein Pydantic-`field_validator(mode="before")` auf `api_key` in `AISettingsUpdate` denselben Zeichensatz vor der SecretStr-Verpackung.

#### SEC-2: SSRF ueber ollama_url (MEDIUM)
- [x] **BUG-3 FIXED:** `AISettingsUpdate.validate_ollama_url()` (models/ai_gateway.py) prueft Schema (`http`/`https`), Hostname und IP-Adresse. Nur `localhost` und private/loopback IPs (`ipaddress.ip_address().is_private | .is_loopback`) sind erlaubt. Alle anderen Hosts werden mit HTTP 422 abgelehnt.

#### SEC-3: Keine Eingabevalidierung fuer model_name und ollama_url
- [x] **BUG-4 FIXED:** `AISettingsUpdate.model_name` hat `min_length=1`, `max_length=100` und Regex `^[a-zA-Z0-9._:/-]+$`. HTML/JS-Payloads und leere Strings werden mit HTTP 422 abgelehnt.

#### SEC-4: Keine Authentifizierung auf Settings-Endpunkten
- [x] Erwartet fuer eine lokale Single-User-App. Kein Bug, aber dokumentiert.

#### SEC-5: Keine Rate-Limiting auf API-Endpunkten
- [x] **BUG-5 FIXED:** `_check_rate_limit()` (api/ai_gateway.py) implementiert einen In-Memory Sliding-Window-Limiter. `/ai/test` erlaubt max. 10 Requests/min, `PUT /ai/settings/data` max. 20 Requests/min. Ueberschreitung liefert HTTP 429.

#### SEC-6: API-Key Leakage
- [x] `GET /ai/settings/data` gibt keinen API-Key zurueck (nur `api_key_set: bool`)
- [x] Logging enthaelt keine API-Keys oder Dateiinhalte
- [x] `SecretStr` wird in Pydantic-Modell fuer API-Key genutzt

#### SEC-7: Security Headers
- [x] `X-Frame-Options: DENY` -- vorhanden
- [x] `X-Content-Type-Options: nosniff` -- vorhanden
- [x] `Referrer-Policy: strict-origin-when-cross-origin` -- vorhanden
- [x] `Content-Security-Policy` -- vorhanden (mit `unsafe-inline` fuer Alpine.js)
- [x] `X-XSS-Protection: 1; mode=block` -- vorhanden

#### SEC-8: SQL-Injection
- [x] Parameterisierte Queries via `aiosqlite` -- sicher. SQL-Injection in `model_name` wird korrekt escaped.

### Cross-Browser & Responsive

Die Settings-Page nutzt Tailwind CSS mit `max-w-2xl mx-auto` Layout. Basierend auf Code-Review:
- [x] **Desktop (1440px):** Zentrierte Karte, ausreichend Platz
- [x] **Tablet (768px):** Gleiche Darstellung, passt sich an
- [x] **Mobile (375px):** `max-w-2xl` passt sich an, Padding via `px-4`
- [x] Alpine.js und Tailwind werden via CDN geladen (browser-unabhaengig)

Hinweis: Kein manueller Cross-Browser-Test moeglich in CLI-Umgebung. Code-Analyse zeigt keine browser-spezifischen APIs oder CSS-Probleme.

### Regression Test (PROJ-1: Verzeichnis-Scanner)
- [x] `GET /scan/` liefert HTTP 200
- [x] Scan-API-Endpunkte sind erreichbar (`/scan/start`, `/scan/pick-folder`, etc.)
- [x] Keine Fehler im Server-Log durch PROJ-6 Aenderungen


### Summary
- **Acceptance Criteria:** 7/7 bestanden
- **Bugs Found:** 5 total — alle behoben (1 Critical, 2 Medium, 2 Low)
- **Security:** Alle sicherheitsrelevanten Befunde (BUG-2, BUG-3, BUG-4, BUG-5) wurden gefixt.
- **Production Ready:** **JA**