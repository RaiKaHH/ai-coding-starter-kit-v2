# PROJ-8: Deep-AI Smart Sorting (Inbox Triage Upgrade)

## Status: In Bearbeitung
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-24

## Abhängigkeiten
- Benötigt: PROJ-5 (Inbox Triage) – das ist ein Upgrade für die bestehende UI.
- Benötigt: PROJ-6 (AI Gateway) – für den LLM-Aufruf.

## User Stories

- Als Nutzer möchte ich bei Dateien, die das Tool in PROJ-5 nicht eindeutig zuordnen konnte (Konfidenz < 50%), einen "Frag die KI"-Button klicken können.
- Als Nutzer möchte ich, dass die KI nicht nur den Dateinamen rät, sondern die ersten Textzeilen der Datei liest, diese mit meinen bekannten Ordner-Profilen abgleicht und mir den logischsten Zielordner vorschlägt.
- Als Nutzer möchte ich eine kurze, von der KI generierte Begründung sehen (z.B. *"Dies ist eine Stromrechnung, daher passt sie in /Finanzen/Nebenkosten"*), damit ich der Blackbox vertrauen kann.

## Akzeptanzkriterien

- [ ] In der Triage-Tabelle (aus PROJ-5) erscheint bei Dateien mit niedriger Konfidenz oder Status "Nicht zugeordnet" ein Button: `✨ KI-Analyse`.
- [ ] Bei Klick wird der Dateiinhalt via `utils/text_extractor.py` gelesen (max. 2.000 Zeichen, konsistent mit PROJ-3).
- [ ] Das Backend sendet den Inhalt + die Liste der bekannten Ordner (aus PROJ-4) an das AI Gateway (PROJ-6).
- [ ] Prompt-Ziel: Die KI wählt den besten Ordner aus der Liste und liefert eine 1-Satz-Begründung.
- [ ] UI-Update: Der vorgeschlagene Ordner wird ins Dropdown eingetragen, die Konfidenz auf "AI (Hoch)" gesetzt und die Begründung als Tooltip/Text unter dem Dateinamen angezeigt.
- [ ] Ein globaler Button "KI für alle unklaren Dateien nutzen" erlaubt die Batch-Verarbeitung.

## Randfälle

- **KI findet keinen passenden Ordner:** Die KI darf antworten "Keiner der Ordner passt". In dem Fall schlägt das Tool vor, einen neuen Ordner `[Dateityp]/Unsortiert` anzulegen.
- **Datei nicht lesbar:** Wenn es ein Foto ohne OCR-Text oder ein Video ist, wird der Button ausgegraut (oder es greift nur eine Dateinamen-Analyse).
- **Token-Limit der Ordnerliste:** Wenn der Nutzer 500 Ordner im Index hat, dürfen nicht alle ans LLM geschickt werden. Das Backend filtert vorab die Top 20 wahrscheinlichsten Ordner (via Fuzzy-Match aus PROJ-5) und schickt nur diese als Auswahlmöglichkeiten an die KI.

## Technische Anforderungen

- **KI-Prompt Design:** Muss zwingend den Output als JSON anfordern: `{"zielordner": "...", "begruendung": "..."}`.
- **Validierung:** Der von der KI vorgeschlagene Zielordner muss gegen die tatsächliche Liste der existierenden Ordner validiert werden (Halluzinations-Schutz).
- **Caching:** KI-Antworten für identische Datei-Hashes werden in SQLite (`ai_cache`) gespeichert, um wiederholte teure Anfragen zu vermeiden, falls der Nutzer den Triage-Vorgang abbricht und später neu startet.

---

## Tech Design (Solution Architect)

**Erstellt:** 2026-02-24
**Status nach Design:** In Bearbeitung

---

### Architektur-Überblick

PROJ-8 ist ein **Upgrade für das PROJ-5 Triage-UI**. Es fügt keinen eigenständigen Workflow hinzu,
sondern erweitert die bestehende Triage-Tabelle um einen "Frag die KI"-Escape-Hatch für Dateien,
die das lokale Fuzzy-Matching nicht sicher zuordnen konnte.

Das Feature ist bewusst **dünn gehalten**: Kein neues Core-Modul, keine eigene Datenlogik —
es orchestriert ausschließlich vorhandene Bausteine:

```
Triage-Tabelle (PROJ-5 UI)
      |
      | User klickt "✨ KI-Analyse"
      v
api/deep_sort.py         ← neuer API-Router (Stub bereits vorhanden)
      |
      ├─ 1. Cache-Lookup ──────────── ai_cache (SQLite) ──► Cache-Hit? → sofort zurückgeben
      |
      ├─ 2. Text lesen ──────────── utils/text_extractor.py → max. 2.000 Zeichen
      |
      ├─ 3. Pre-Filter ────────────── core/triage.py (fuzzy_match) → Top-20 Ordner
      |
      ├─ 4. LLM-Aufruf ─────────── core/ai_service.ask_json(prompt, AIFolderSuggestion)
      |
      ├─ 5. Halluzinations-Check ── Zielordner gegen echte folder_profiles validieren
      |
      └─ 6. Cache schreiben + Antwort zurückgeben → UI aktualisiert Zeile inline
```

---

### Modul-Struktur

| Datei | Status | Verantwortlichkeit |
|-------|--------|---------------------|
| `api/deep_sort.py` | Stub vorhanden | HTTP-Routen: Einzel- und Batch-KI-Analyse |
| `models/deep_sort.py` | **neu** | Pydantic-Modelle für Request/Response |
| `models/ai_gateway.py` | Vorhanden | `AIFolderSuggestion` (zielordner, begruendung) — keine Änderung |
| `core/ai_service.py` | Vorhanden | `ask_json()` — wird konsumiert, nicht geändert |
| `core/triage.py` | Vorhanden | Fuzzy-Match-Vorfilterung — wird konsumiert, nicht geändert |
| `utils/text_extractor.py` | Vorhanden | Dateiinhalt lesen (PDF, Text, Bild) — wird konsumiert |
| `utils/db.py` | Vorhanden | SQLite-Verbindung — neue Tabelle `ai_cache` wird dort angelegt |
| `templates/triage.html` | Vorhanden | **Erweiterung:** KI-Button + Reasoning-Anzeige pro Zeile |

---

### Datenmodelle (Plain Language)

#### Neue SQLite-Tabelle: `ai_cache`

Speichert KI-Ergebnisse dauerhaft, damit derselbe Dateiinhalt nie zweimal bezahlt wird.

| Feld | Typ | Beispiel | Beschreibung |
|------|-----|---------|--------------|
| `file_hash` | Text (PK) | `"a3f9b1..."` | SHA-256 des Dateiinhalts (nicht des Namens) |
| `suggested_folder` | Text | `"/Finanzen/Nebenkosten"` | KI-Vorschlag (kann `"__none__"` sein) |
| `reasoning` | Text | `"Dies ist eine Stromrechnung..."` | KI-Begründung |
| `model_used` | Text | `"llama3"` | Welches Modell geantwortet hat |
| `created_at` | Text | `"2026-02-24T10:30:00Z"` | Wann der Cache-Eintrag erstellt wurde |

**Cache-Logik:** Hash des **Dateiinhalts** (nicht des Namens), damit umbenannte Dateien trotzdem einen Cache-Hit landen.

#### Neue Pydantic-Modelle: `models/deep_sort.py`

Jedes Modell beschreibt, was zwischen Frontend und Backend übermittelt wird:

| Modell | Richtung | Felder |
|--------|----------|--------|
| `DeepSortRequest` | Frontend → Backend | `source_path` (SafePath), `batch_id` (str), `confidence_threshold` (int) |
| `DeepSortResult` | Backend → Frontend | `source_path`, `suggested_folder` (str \| None), `reasoning` (str), `from_cache` (bool), `readable` (bool) |
| `DeepSortBatchRequest` | Frontend → Backend | `batch_id` (str), `threshold` (int, default 50) |
| `DeepSortBatchResult` | Backend → Frontend | `results` (list[DeepSortResult]), `processed` (int), `failed` (int) |

---

### API-Endpunkte

| Methode | Pfad | Auslöser | Antwort |
|---------|------|----------|---------|
| `POST` | `/deep-sort/analyse/{file_name}` | User klickt "✨ KI-Analyse" auf einer Zeile | `DeepSortResult` |
| `POST` | `/deep-sort/analyse-batch` | User klickt "✨ KI für alle unklaren Dateien" | `DeepSortBatchResult` via BackgroundTask |

---

### UI-Komponentenbaum (Änderungen an `triage.html`)

Nur Erweiterungen — die bestehende Triage-Tabelle bleibt unverändert.

```
triage.html (PROJ-5, bestehend)
└── Triage-Tabelle
    │
    ├── [NEU] Batch-KI-Leiste (über der Tabelle, x-show wenn unmatched_count > 0)
    │   ├── "✨ KI für alle unklaren Dateien nutzen"-Button
    │   │   └── Fortschrittsanzeige: "KI analysiert 3 / 7 Dateien..."
    │   └── Erfolgsmeldung: "KI hat 5 Dateien zugeordnet, 2 bleiben unklar."
    │
    └── Tabellenzeile (bestehend + Erweiterungen)
        ├── Dateiname (bestehend)
        │   └── [NEU] KI-Begründung (grau-italic unter Dateiname, x-show nach Analyse)
        │       Beispiel: "Dies ist eine Stromrechnung → /Finanzen/Nebenkosten"
        │
        ├── Vorschlag-Dropdown (bestehend, wird nach KI-Analyse mit Ergebnis befüllt)
        │
        ├── Konfidenz-Badge (bestehend)
        │   └── [NEU] Farbe/Text ändert sich auf "🤖 KI (Hoch)" nach erfolgreicher Analyse
        │
        └── [NEU] "✨ KI-Analyse"-Button (nur sichtbar wenn confidence < 50% oder "Nicht zugeordnet")
            ├── Ladespinner während Anfrage läuft
            ├── Ausgegraut + Tooltip "Nicht lesbar" wenn Datei kein Text enthält
            └── Ausgegraut + Tooltip "Bereits analysiert" wenn Cache-Treffer angezeigt wird
```

---

### Anfrage-Ablauf (Einzeldatei)

```
User klickt "✨ KI-Analyse" auf Datei "rechnung_jan.pdf"
  │
  ├─ Frontend sendet: POST /deep-sort/analyse/rechnung_jan.pdf
  │   Body: { source_path: "/Users/.../Downloads/rechnung_jan.pdf", batch_id: "abc123" }
  │
  └─ Backend (api/deep_sort.py):
      │
      ├─ 1. SafePath-Validierung auf source_path (Pfad-Traversal-Schutz)
      │
      ├─ 2. SHA-256 des Dateiinhalts berechnen → Cache-Lookup in ai_cache
      │   └─ Cache-Hit? → DeepSortResult(from_cache=True) sofort zurückgeben ✓
      │
      ├─ 3. text, readable = await text_extractor.extract_text(path)
      │   └─ readable=False? → DeepSortResult(readable=False, suggested_folder=None) ✓
      │
      ├─ 4. folder_candidates = core/triage.fuzzy_match(filename) → Top-20 Ordner
      │   (verhindert Token-Overflow bei großem Ordner-Index)
      │
      ├─ 5. prompt = build_prompt(text, folder_candidates)
      │   └─ Format: "Dateiinhalt: ...\nMögliche Ordner: ...\nJSON: {zielordner, begruendung}"
      │
      ├─ 6. result = await ai_service.ask_json(prompt, AIFolderSuggestion)
      │   (nutzt bestehenden Semaphore, Retry, Pydantic-Validierung aus PROJ-6)
      │
      ├─ 7. Halluzinations-Check:
      │   └─ result.zielordner in echten folder_profiles?
      │       ├─ Nein → suggested_folder = None, reasoning = "KI-Vorschlag nicht validierbar"
      │       └─ Ja  → weiter
      │
      ├─ 8. Cache-Eintrag in ai_cache schreiben (file_hash, suggested_folder, reasoning, model)
      │
      └─ 9. DeepSortResult zurückgeben → Frontend aktualisiert Zeile inline
```

---

### Randfälle und Verhalten

| Situation | Verhalten Backend | Verhalten UI |
|-----------|------------------|--------------|
| Datei nicht lesbar (Video, Binary) | `readable=False`, kein LLM-Aufruf | Button ausgegraut, Tooltip "Nur Dateiname-Analyse möglich" |
| KI findet keinen passenden Ordner | `AIFolderSuggestion.zielordner = "KEIN_ORDNER"`, Begründung erhalten | UI schlägt vor: `[Dateityp]/Unsortiert` im Dropdown |
| Vorgeschlagener Ordner existiert nicht (Halluzination) | `suggested_folder = None`, Log-Eintrag | Zeigt Begründung an, Dropdown bleibt bei "Nicht zugeordnet" |
| Cache-Treffer | Kein LLM-Aufruf, sofortige Antwort | Badge zeigt "🤖 KI (Cache)" |
| Ollama nicht gestartet | `AIServiceError` → HTTP 503 mit Fehlermeldung | Rote Inline-Meldung "Ollama nicht erreichbar" |
| Batch: >50 Dateien | Läuft als BackgroundTask | Fortschrittsbalken, Polling via bestehenden Batch-Status-Mechanismus |

---

### Abhängigkeiten

Keine neuen Python-Packages nötig. Alle Bausteine sind bereits installiert:

| Baustein | Kommt aus | Genutzt für |
|----------|-----------|-------------|
| `core/ai_service.ask_json()` | PROJ-6 | LLM-Aufruf |
| `utils/text_extractor.extract_text()` | PROJ-3 | Dateiinhalt lesen |
| `core/triage` fuzzy-match | PROJ-5 | Top-20 Ordner-Vorfilterung |
| `utils/paths.SafePath` | PROJ-1 | Pfad-Validierung |
| `aiosqlite` | vorhanden | ai_cache-Tabelle |
| `hashlib` (stdlib) | Python | SHA-256 für Cache-Key |