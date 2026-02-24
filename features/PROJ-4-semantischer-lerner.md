# PROJ-4: Semantischer Struktur-Lerner & Regel-Generator

## Status: Fertig
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-24

## Abhängigkeiten
- Benötigt: PROJ-1 (Verzeichnis-Scanner) – für das schnelle Einlesen.
- Benötigt: PROJ-6 (KI-Integrations-Schicht / AI Gateway) – stellt die einheitliche `ai_service.py` Schnittstelle für Ollama/Mistral bereit. Kein eigener API-Code in diesem Modul.
- Bereitet vor: PROJ-2 (Datei-Verschieber) – liefert die Konfigurationsdaten (YAML) für das spätere automatische Einsortieren.

## User Stories

- Als Nutzer möchte ich das Tool auf einen bereits perfekt organisierten "Muster-Ordner" (z.B. mein altes Steuer- oder Rechnungs-Archiv) richten, damit das Tool die Logik dahinter automatisch "lernt".
- Als Nutzer möchte ich, dass das Tool nicht einfach nur Dateinamen speichert, sondern **"Ordner-Profile"** erstellt (z.B. erkennt: "Ah, im Ordner `/Rechnungen/2023` liegen zu 95% PDFs, die oft 'RE-' im Namen haben").
- Als Nutzer möchte ich, dass die KI aus diesen gelernten Profilen automatisch eine `structure_rules.yaml` (für PROJ-2) generiert, damit ich die Regeln nicht von Hand tippen muss.
- Als Nutzer möchte ich in der UI sehen, welchen "Zweck" das Tool für einen bestimmten Ordner gelernt hat (z.B. KI-Zusammenfassung: *Dieser Ordner enthält primär Telekom-Rechnungen und Verträge*).
- Als Nutzer möchte ich gelerntes Wissen per Knopfdruck aktualisieren oder Ordner aus dem "Gedächtnis" löschen.

## Akzeptanzkriterien

- [ ] Nutzer wählt einen Quellordner als "Trainingsdaten" aus.
- [ ] Backend scannt den Ordner rekursiv und aggregiert Statistiken **pro Unterordner**: Häufigste Dateiendungen, häufigste Wörter in den Dateinamen.
- [ ] **AI-Folder-Profiling:** Das Backend sendet die aggregierten Statistiken (z.B. eine Liste von 20 typischen Dateinamen eines Ordners) an das LLM (Ollama/Mistral) mit dem Prompt: *"Analysiere diese Dateinamen. Welchem Zweck dient dieser Ordner? Nenne 3 Keywords und eine Regel, wie Dateien hier heißen."*
- [ ] Speicherung in SQLite (Tabelle `folder_profiles`): `Ordnerpfad`, `Haupt-Dateityp`, `KI_Beschreibung`, `Keywords`.
- [ ] UI zeigt eine Übersicht aller gelernten Ordner in Form von "Karten" mit der KI-Beschreibung und den Keywords an.
- [ ] **Killer-Feature (YAML-Export):** Ein Button "Regeln für PROJ-2 generieren". Das Backend nimmt alle `folder_profiles`, übersetzt sie in das in PROJ-2 definierte YAML-Format und speichert/downloadet die Datei.
- [ ] Der Indexierungsprozess läuft asynchron mit einer sauberen Lade-Anzeige (Short-Polling wie in PROJ-1).

## Randfälle

- **Ordner ohne klare Struktur (Chaos-Ordner):** Wenn ein Ordner MP3s, PDFs, JPEGs und Word-Dateien wild gemischt enthält → KI markiert den Ordner als "Gemischt/Unsortiert", es werden keine harten Regeln dafür generiert.
- **Ordner ist leer:** Wird beim Lernen ignoriert.
- **Token-Limit des LLM:** Wenn ein Ordner 5.000 Dateien hat, dürfen nicht alle Namen an die KI gesendet werden. Backend wählt ein repräsentatives Sample (z.B. zufällig 50 Dateinamen) für den KI-Prompt.
- **KI nicht verfügbar (Offline-Modus ohne Ollama):** Backend nutzt heuristischen Fallback (speichert nur Dateiendungen und Regex-Muster der häufigsten Namen, ohne KI-Text-Zusammenfassung).

## Technische Anforderungen

- **Aggregation:** Nutzung von `collections.Counter` im Python-Backend, um rasend schnell die häufigsten Dateiendungen und n-Gramme (Wortbausteine) in Dateinamen zu zählen.
- **KI-Integration:** Strukturierter JSON-Output für das Ordner-Profil erzwingen (via Pydantic Validierung), z.B. `{"zweck": "Steuerdokumente", "keywords": ["steuer", "elster", "finanzamt"], "empfohlene_regel": "*.pdf"}`.
- **Asynchron & Batching:** Da jeder Ordner einen KI-Aufruf bedeutet, laufen die Aufrufe als `BackgroundTask`. Die Concurrency-Steuerung (max. 3 gleichzeitige KI-Anfragen, app-weit) wird von `core/ai_service.py` (PROJ-6) übernommen — kein eigenes asyncio.Queue in diesem Modul.
- **YAML-Generierung:** Nutzung von `PyYAML`, um aus den Datenbank-Einträgen dynamisch ein valides YAML-Dokument zu rendern.
- **Datenschutz:** Auch hier werden *keine* Dateiinhalte ans LLM geschickt, sondern ausschließlich Datei*namen* und Verzeichnisnamen.

---
<!-- Folgende Abschnitte werden von nachfolgenden Skills ergänzt -->

## Tech Design (Solution Architect)

### Komponenten-Struktur (UI — `templates/index.html`)

```
/index  →  "Indexer – Ordner lernen"
│
├── [Abschnitt 1: Trainings-Ordner wählen]
│   ├── Ordnerpfad-Eingabe (Texteingabe)
│   ├── "Ordner auswählen"-Button  (öffnet macOS Finder-Dialog)
│   └── "Indexierung starten"-Button  (primär, löst POST /index/start aus)
│
├── [Abschnitt 2: Fortschritts-Anzeige]  (x-show: indexing === true)
│   ├── Scan-Pulse-Animation  (wie in PROJ-1 / PROJ-3)
│   ├── Fortschrittsbalken  (processed_count / total_count)
│   └── Status-Text  "Analysiere Ordner 12 / 47…"
│
├── [Abschnitt 3: Gelernte Ordner-Profile]  (x-show: profiles.length > 0)
│   ├── Abschnitt-Header + Anzahl-Badge
│   ├── Profil-Karten-Grid  (2–3 Spalten, x-for: profile in profiles)
│   │   └── [Ordner-Karte]
│   │       ├── Ordnerpfad  (fett, abgekürzt mit title-Tooltip)
│   │       ├── KI-Beschreibung  (kursiv, grau)
│   │       ├── Keywords  (Badge-Tags, blau)
│   │       ├── Metadaten-Zeile  (Dateianzahl · Haupt-Extension · Datum)
│   │       └── "Löschen"-Button  (Papierkorb-Icon, Bestätigungs-Dialog)
│   │
│   └── Aktions-Leiste (unten)
│       └── "Regeln für PROJ-2 generieren"-Button  (lädt structure_rules.yaml herunter)
│
└── [Leer-Zustand]  (x-show: profiles.length === 0 && !indexing)
    └── Erklärungstext + Illustration  "Kein Wissen vorhanden. Wähle einen Muster-Ordner..."
```

### Daten-Modell

**SQLite-Tabelle `folder_profiles`** (wird beim App-Start via `init_db()` angelegt)

| Spalte | Typ | Beschreibung |
|---|---|---|
| `id` | INTEGER PK | Auto-Increment |
| `folder_path` | TEXT UNIQUE | Absoluter Pfad des Unterordners |
| `primary_extension` | TEXT \| NULL | Häufigste Dateiendung (z.B. `.pdf`) |
| `ai_description` | TEXT \| NULL | Ein-Satz-Zusammenfassung vom LLM; NULL im Offline-Modus |
| `keywords` | TEXT | JSON-Array, z.B. `["steuer", "elster", "finanzamt"]` |
| `file_count` | INTEGER | Anzahl Dateien in diesem Unterordner |
| `indexed_at` | TEXT | ISO-8601-Zeitstempel der letzten Indexierung |

`UNIQUE` auf `folder_path`: Re-Indexierung desselben Ordners überschreibt den alten Eintrag (INSERT OR REPLACE).

**In-Memory-Status (nur während Laufzeit, kein DB-Eintrag)**

| Feld | Beschreibung |
|---|---|
| `status` | `running \| completed \| failed` |
| `processed_count` | Bisher fertig analysierte Unterordner |
| `total_count` | Gesamtzahl zu analysierender Unterordner |

**LLM-Antwort-Schema (erzwungenes JSON via Pydantic)**

```
AIFolderProfile:
  zweck:             string   – z.B. "Steuerdokumente 2023"
  keywords:          list[str] – max. 5 Schlüsselwörter
  empfohlene_regel:  string   – z.B. "*.pdf" oder "RE-*.pdf"
```

**YAML-Export-Beispiel** (generiert für PROJ-2)

```yaml
rules:
  - name: "Steuerdokumente"
    target: "/Archiv/Steuer/2023"
    match:
      extensions: [".pdf"]
      keywords: ["steuer", "elster", "finanzamt"]
  - name: "Telekom-Rechnungen"
    target: "/Rechnungen/Telekom"
    match:
      extensions: [".pdf"]
      keywords: ["telekom", "rechnung"]
```

### Modul-Übersicht

**`api/index.py`** – HTTP-Routen

| Route | Methode | Funktion |
|---|---|---|
| `/index/` | GET | Rendert `templates/index.html` |
| `/index/start` | POST | Startet Hintergrund-Task; gibt sofort `IndexStatus` zurück |
| `/index/status` | GET | Short-Polling alle 2 s (Alpine.js) → `IndexStatus` |
| `/index/profiles` | GET | Alle gespeicherten Profile → `list[FolderProfile]` |
| `/index/profiles/{id}` | DELETE | Entfernt Eintrag aus DB |
| `/index/export-yaml` | GET | Gibt YAML als Plaintext zurück (Browser-Download) |

**`core/lerner.py`** – Business-Logik

Ablauf des BackgroundTask `scan_and_profile(folder_path)`:

```
1. Alle Unterordner rekursiv einlesen  (pathlib.Path.rglob)
2. total_count setzen  (für Fortschritts-Anzeige)
3. Pro Unterordner:
   a. collections.Counter für Dateiendungen + n-Gramme in Dateinamen
   b. Leer-Ordner überspringen
   c. Sample: max. 50 zufällige Dateinamen auswählen  (random.sample)
   d. ai_service.ask_json(prompt, AIFolderProfile) aufrufen
      → Concurrency-Limit (Semaphore 3) wird zentral von PROJ-6 verwaltet
   e. Offline-Fallback: AIServiceError → nur Statistiken speichern, kein ai_description
   f. Chaos-Ordner-Erkennung: >3 verschiedene Extensions → Keywords = ["gemischt"]
   g. INSERT OR REPLACE INTO folder_profiles …
   h. processed_count += 1
4. Status auf "completed" setzen
```

`generate_yaml_from_profiles()` – liest alle Profile aus DB → baut YAML-String mit `PyYAML`

**`models/index.py`** – Pydantic-Modelle (bereits angelegt)

| Modell | Verwendung |
|---|---|
| `IndexRequest` | POST /start Eingabe (folder_path als SafePath) |
| `IndexStatus` | Polling-Antwort (status, processed_count, total_count) |
| `FolderProfile` | Einzelnes Profil aus der DB |
| `YamlExportResponse` | YAML-Inhalt + vorgeschlagener Dateiname |
| `AIFolderProfile` (neu) | Pydantic-Modell für strukturierten LLM-Output |

### Tech-Entscheidungen

| Entscheidung | Begründung |
|---|---|
| `collections.Counter` für Statistiken | Extrem schnell, keine Abhängigkeiten, ideal für Häufigkeitsanalysen |
| Max. 50 Dateinamen-Sample | Verhindert Token-Limit-Überschreitung; repräsentatives Bild reicht für Profiling |
| Concurrency via `_semaphore` in `ai_service.py` (PROJ-6) | Zentrales Rate-Limiting, kein doppelter Code in diesem Modul |
| Short-Polling alle 2 s statt WebSocket | Konsistent mit PROJ-1 und PROJ-3; kein Infrastruktur-Overhead |
| Offline-Fallback (nur Statistiken) | Ordner werden nie ignoriert; Tool ist auch ohne KI nützlich |
| `folder_path UNIQUE` + INSERT OR REPLACE | Re-Indexierung überschreibt alten Eintrag, keine Duplikate |
| YAML-Export via `PyYAML` | Direkte PROJ-2-Kompatibilität ohne Dateiformat-Konvertierung |
| Keine Dateiinhalte ans LLM | Datenschutz: nur Datei*namen* werden analysiert, keine Inhalte |

### Abhängigkeiten / Pakete

| Paket | Zweck | Neu? |
|---|---|---|
| `PyYAML` | YAML-Generierung für PROJ-2-Export | Nein (via PROJ-2) |
| `aiosqlite` | Async SQLite für `folder_profiles` | Nein (vorhanden) |
| `httpx` | HTTP-Client für AI-Calls (via ai_service.py) | Nein (vorhanden) |
| `pathlib`, `collections`, `random` | Standard-Library – Scan, Counter, Sampling | Nein |

## QA Testergebnisse
_Wird durch /qa ergänzt_

## Deployment
_Wird durch /deploy ergänzt_