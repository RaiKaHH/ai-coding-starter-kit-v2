# PROJ-2: Struktur-basierter Datei-Verschieber (Auto-Organizer)

## Status: Fertig
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-24

## Abhängigkeiten
- Benötigt: PROJ-1 (Verzeichnis-Scanner) – liefert die zu sortierenden Dateien.

## User Stories

- Als Nutzer möchte ich nicht jede Regel mühsam einzeln anklicken, sondern dem Tool eine fertige Ziel-Struktur vorgeben (z. B. via Konfigurationsdatei oder durch das Einlesen eines "sauberen" Muster-Ordners), damit das Tool die Logik selbst ableitet.
- Als Nutzer möchte ich eine statische Konfigurationsdatei (z. B. YAML oder JSON) nutzen können, in der Ordnerstrukturen und einfache Zuordnungsregeln (Dateiendungen, Namensmuster) definiert sind. Diese Datei kann ich idealerweise von einer KI generieren lassen.
- Als Nutzer möchte ich *zwingend* eine Vorschau ("Dry-Run") sehen, bevor auch nur eine einzige Datei verschoben wird, damit ich sicher bin, dass die abgeleiteten Regeln das tun, was ich erwarte.
- Als Nutzer möchte ich Ausnahmen definieren können (z.B. Dateien aus der Vorschau abwählen), bevor ich den finalen "Verschieben"-Button drücke.
- Als Nutzer möchte ich, dass Dateien, die in keine Regel/Struktur passen, in einem definierten "Unsortiert"-Ordner landen oder an ihrem Platz bleiben, damit nichts blind verschoben wird.

## Akzeptanzkriterien

- [ ] Das System akzeptiert eine Konfigurationsdatei (z.B. `structure_rules.yaml`), die Zielordner und deren Kriterien (Endungen, Regex-Muster im Namen, Altersvorgaben) definiert.
- [ ] Alternativ kann der Nutzer einen bestehenden "Muster-Ordner" angeben, dessen Struktur (Unterordner und darin liegende Dateitypen) vom Backend analysiert und in temporäre Regeln übersetzt wird.
- [ ] Es gibt einen "Vorschau generieren"-Button. Dieser mappt die gescannten Dateien (aus PROJ-1) gegen die Regeln.
- [ ] Die UI zeigt eine übersichtliche Vorher/Nachher-Tabelle: `Dateiname | Aktueller Pfad | Neuer Pfad (gemäß Regel)`.
- [ ] In der Vorschau-Tabelle gibt es Checkboxen, um einzelne Dateien vom Verschieben auszuschließen (Opt-out).
- [ ] Fehlende Zielordner werden vom System beim Verschieben automatisch erstellt.
- [ ] Alle durchgeführten Verschiebungen werden in der SQLite-Tabelle `operation_log` geloggt (batch_id, Typ `MOVE`, source_path, target_path, Zeitstempel), um spätere "Undo"-Funktionen zu ermöglichen (PROJ-9).
- [ ] **Top-Down Priorität:** Die Regeln in der YAML-Datei werden strikt von oben nach unten abgearbeitet. Die erste Regel, die auf eine Datei zutrifft, gewinnt. Danach wird die Datei für nachfolgende Regeln übersprungen (verhindert zirkuläre Konflikte).

## Randfälle

- **Namenskonflikte:** Wenn im Zielordner schon eine Datei mit gleichem Namen liegt, wird die neue Datei automatisch umbenannt (z.B. `rechnung_1.pdf`) anstatt sie zu überschreiben.
- **Fehlerhaftes YAML:** Wenn die Konfigurationsdatei Syntaxfehler enthält, wirft das Backend einen sauberen Fehler, der in der UI verständlich angezeigt wird.
- **Berechtigungen:** Zielordner ist schreibgeschützt → Die spezifische Datei schlägt fehl, wird in der UI rot markiert, aber der restliche Batch-Vorgang läuft weiter.
- **Leere Treffer:** Keine Datei passt zur Struktur → UI zeigt "0 Dateien zu verschieben".
- **Zirkuläre Pfade:** Quellordner ist identisch mit Zielordner → Datei wird in der Vorschau ignoriert.
- **Datei extern verändert/gelöscht:** Wenn eine Datei während des asynchronen Batch-Vorgangs im Finder verschoben oder gelöscht wird, wird dies per `try/except FileNotFoundError` abgefangen. Die Datei wird in der UI als Fehler markiert, aber der Rest des Batches läuft ungestört weiter.

## Technische Anforderungen

- **Konfiguration:** Nutzung von `PyYAML` im Backend zum Parsen der Struktur-Regeln.
- **Mustererkennung:** Nutzung von Pythons Standard-Bibliotheken (`fnmatch` für Wildcards, `re` für Regex), um Dateinamen gegen die YAML-Regeln zu prüfen.
- **Sicherheit & Dry-Run:** Strenge Trennung von Analyse-Logik (Dry-Run) und Ausführungs-Logik (I/O-Operationen `shutil.move`).
- **Asynchron:** Der finale Verschiebe-Vorgang (bei Tausenden Dateien) läuft als FastAPI `BackgroundTask`.
- **Datenbank:** Die `operation_log` Tabelle in SQLite muss zwingend den absoluten Originalpfad speichern, damit PROJ-9 (Undo/Rollback) darauf aufbauen kann.

---
<!-- Folgende Abschnitte werden von nachfolgenden Skills ergänzt -->

## Tech Design (Solution Architect)

### Komponenten-Struktur (UI)

```
/move
├── Modus-Tabs (Alpine.js: "Nach Regeln" | "Nach Muster-Ordner")
│
├── [Tab 1: Nach YAML-Regeln]
│   ├── Scan-Auswahl Dropdown  (welchen Scan-Datensatz verwenden)
│   ├── YAML-Pfad Input        (Pfad zu structure_rules.yaml)
│   └── Button: "Vorschau generieren"
│
├── [Tab 2: Nach Muster-Ordner]
│   ├── Scan-Auswahl Dropdown
│   ├── Referenzordner-Input   (Pfad zu gut-sortiertem Ordner)
│   └── Button: "Vorschau generieren"
│
├── Vorschau-Tabelle (Alpine.js, erscheint nach API-Antwort)
│   ├── Kopfzeile: ☑ | Dateiname | Aktueller Pfad | Neuer Pfad | Gematchte Regel
│   ├── Tabellenzeilen (alle ✓ vorausgewählt; Nutzer kann einzelne abwählen)
│   ├── Fußzeile: "X von Y Dateien ausgewählt | Z nicht zugeordnet"
│   └── Button: "X Dateien jetzt verschieben" (gesperrt, wenn 0 ausgewählt)
│
└── Fortschrittsanzeige (erscheint nach Execute, Polling alle 1s)
    ├── Progress Bar (verschoben / gesamt)
    ├── Fehlerliste (rot markierte Fehler-Dateien)
    └── Button: "Zur Operationshistorie" → /history
```

### Datenfluss

```
Nutzer-Input (Scan-ID + YAML-Pfad  ODER  Scan-ID + Referenzordner)
        ↓
POST /move/preview/by-rules  oder  POST /move/preview/by-pattern
        ↓
core/mover.py:
  1. parse_yaml_rules(path)   oder  infer_rules_from_folder(path)
  2. Lädt scan_files aus DB   (nur Dateien des gewählten scan_id)
  3. match_files_to_rules()   Top-Down: erste passende Regel gewinnt
        ↓
MovePreviewResponse (batch_id + MovePreviewItem-Liste)
  → Preview-Daten werden im Server-Memory (Dict[batch_id → items]) gecacht
        ↓
Nutzer überprüft Tabelle, entfernt unerwünschte Häkchen
        ↓
POST /move/execute  {batch_id, selected_ids: [1,3,5,...]}
        ↓
BackgroundTask: core/mover.py.execute_batch()
  - shutil.move() pro Datei
  - Namenskonflikt → automatische Nummerierung (_1, _2 …)
  - Fehlende Zielordner → mkdir(parents=True)
  - Schreibfehler → Datei als failed markieren, Rest läuft weiter
  - INSERT in operation_log pro Datei (batch_id, MOVE, source, target)
        ↓
GET /move/batch/{batch_id}/status  (Client pollt jede Sekunde)
  → Liefert {moved, failed, total, done: bool, errors: [...]}
```

### Datenmodell

**In-Memory Batch-Cache** — `Dict[batch_id → List[MovePreviewItem]]`
- Wird bei `POST /preview` erzeugt, bei `POST /execute` konsumiert
- Akzeptabel für Single-User-Tool (kein Server-Restart während Vorschau nötig)

**`operation_log` (SQLite)** — eine Zeile pro verschobener Datei:
- `batch_id` → UUID des gesamten Vorgangs (für PROJ-9 Undo/Rollback)
- `operation_type` → `'MOVE'`
- `source_path` → absoluter Pfad vor der Verschiebung
- `target_path` → absoluter Pfad nach der Verschiebung (inkl. Umbenennung bei Konflikt)
- `status` → `'completed'` | `'failed'`
- Keine neuen Tabellen nötig — Schema ist in `utils/db.py` bereits vollständig vorhanden.

### YAML-Regelformat (structure_rules.yaml)

```yaml
rules:
  - name: "PDFs → Dokumente/PDFs"
    target: "~/Dokumente/PDFs"
    match:
      extensions: [".pdf"]

  - name: "Screenshots → Bilder/Screenshots"
    target: "~/Bilder/Screenshots"
    match:
      name_pattern: "Screenshot*"    # fnmatch-Wildcard

  - name: "Videos"
    target: "~/Videos"
    match:
      extensions: [".mp4", ".mov", ".mkv"]

unmatched: "skip"   # Alternativen: 'skip' | 'move_to: ~/Unsortiert'
```

### Modulverantwortlichkeiten

| Modul | Aufgabe | Status |
|---|---|---|
| `api/move.py` | HTTP-Routing (6 Endpoints) | Fertig |
| `core/mover.py` | Geschäftslogik: YAML-Parsing, Matching, Execute | Fertig |
| `models/move.py` | Pydantic-Modelle | Fertig |
| `utils/db.py` | `operation_log`-Schema | Fertig |
| `utils/paths.py` | SafePath-Validation | Fertig |
| `templates/move.html` | Alpine.js UI | Fertig |

Interne Funktionen in `core/mover.py`:
- `parse_yaml_rules(path)` → YAML lesen und validieren
- `infer_rules_from_folder(path)` → Referenzordner analysieren → Regeln ableiten
- `match_files_to_rules(scan_id, rules, db)` → DB-Dateien gegen Regeln matchen
- `execute_batch(batch_id, items, db)` → `shutil.move` + `operation_log`

### Schlüssel-Entscheidungen

- **Dry-Run und Execute** sind strikt getrennte Codepfade in `core/mover.py`
- **Top-Down Priorität:** Erste Regel, die auf eine Datei passt, gewinnt
- **Fehlertoleranz:** Ein Fehler bei einer Datei stoppt nicht den gesamten Batch
- **Keine neuen Dependencies** — PyYAML, aiosqlite, pathlib, shutil, fnmatch, re sind alle vorhanden

## QA Testergebnisse

**Datum:** 2026-02-24
**Status:** ✅ BESTANDEN (mit Minor-Findings)

### Akzeptanzkriterien

| # | Kriterium | Ergebnis | Anmerkung |
|---|-----------|----------|-----------|
| AC1 | YAML-Konfigurationsdatei mit Zielordnern/Kriterien | ✅ PASS | `parse_yaml_rules()` unterstützt extensions, name_pattern (fnmatch), name_regex |
| AC2 | Muster-Ordner als Alternative | ✅ PASS | `infer_rules_from_folder()` leitet Extension-basierte Regeln aus Unterordnern ab |
| AC3 | "Vorschau generieren"-Button | ✅ PASS | Beide Endpoints (`/preview/by-rules`, `/preview/by-pattern`) implementiert; Lade-Spinner vorhanden |
| AC4 | Vorher/Nachher-Tabelle | ✅ PASS | Desktop-Tabelle + Mobile-Kartenansicht; alle Spalten (Dateiname, Quelle, Ziel, Regel) vorhanden |
| AC5 | Checkboxen für Opt-out | ✅ PASS | Alle Items standardmäßig vorausgewählt; Einzel-Toggle und "Alle"-Checkbox funktional |
| AC6 | Fehlende Zielordner werden erstellt | ✅ PASS | `target.parent.mkdir(parents=True, exist_ok=True)` in `execute_batch()` |
| AC7 | `operation_log` Logging | ✅ PASS | Jede Verschiebung (erfolgreich + fehlgeschlagen) mit batch_id, source_path, target_path, timestamp, status geloggt |
| AC8 | Top-Down Priorität | ✅ PASS | `break` nach erstem Regeltreff in `match_files_to_rules()` – erste Regel gewinnt |

### Randfälle

| Randfall | Ergebnis | Code-Fundstelle |
|----------|----------|-----------------|
| Namenskonflikte (automatische Nummerierung) | ✅ PASS | `_resolve_name_conflict()`: `rechnung.pdf → rechnung_1.pdf`; Safety-Cap bei 9999 |
| Fehlerhaftes YAML (Syntaxfehler) | ✅ PASS | `yaml.safe_load()` + `RuleParseError` → HTTP 422 mit lesbarer Meldung |
| Berechtigungsfehler (Zielordner schreibgeschützt) | ✅ PASS | `PermissionError` per Datei abgefangen; Batch läuft weiter; UI zeigt Fehlerdetails |
| Leere Treffer (0 Dateien passen zu Regeln) | ✅ PASS | `unmatched_count` in Response; UI zeigt "0 nicht zugeordnet" |
| Zirkuläre Pfade (Quelle = Ziel) | ✅ PASS | `source_path.parent == target_dir`-Check in `match_files_to_rules()` |
| Datei extern gelöscht während Batch | ✅ PASS | `FileNotFoundError` abgefangen; Datei als failed markiert; Rest läuft weiter |

### Security Audit

| Prüfpunkt | Ergebnis | Detail |
|-----------|----------|--------|
| Path Traversal (Eingabepfade) | ✅ PASS | `SafePath` blockiert `..`-Traversal, relative Pfade und Systemverzeichnisse |
| YAML Safe Load | ✅ PASS | `yaml.safe_load()` (nicht das unsichere `yaml.load()`) |
| SQL Injection | ✅ PASS | Ausschließlich parametrisierte Queries via `aiosqlite` |
| Async-Compliance | ✅ PASS | Alle DB-Operationen via `aiosqlite`; `execute_batch` läuft als `BackgroundTask` |
| `selected_ids`-Validierung | ✅ PASS | IDs werden gegen Cache-Inhalt validiert; unbekannte IDs → HTTP 422 |
| YAML-Rule-Targets (fehlende SafePath-Prüfung) | ⚠️ LOW | `target`-Felder im YAML-Inhalt werden nicht gegen BLOCKED_PREFIXES geprüft. Kein praktisches Risiko im Single-User-Betrieb (PermissionError würde Schreibzugriff auf Systemordner blockieren). |

### Gefundene Bugs / Minor Issues

| ID | Schwere | Beschreibung | Fundstelle |
|----|---------|--------------|------------|
| BUG-PROJ2-1 | Low | YAML-Rule-`target`-Pfade werden nicht gegen gesperrte Systemverzeichnisse (`BLOCKED_PREFIXES`) validiert – nur `rules_path` und `pattern_folder` gehen durch `SafePath` | `core/mover.py:103`, `utils/paths.py:13` |
| BUG-PROJ2-2 | Minor | `_batch_status` wird nach Batch-Abschluss nicht bereinigt (nur `_batch_cache` wird geleert). Kein praktisches Problem für das Single-User-Tool, aber potenziell wachsender Memory-Footprint | `core/mover.py:442` |
| BUG-PROJ2-3 | Minor | `aiosqlite.connect()` verwendet kein `timeout=10.0`, wie in CLAUDE.md spezifiziert. WAL-Mode reduziert das Risiko erheblich, aber die Spec-Anforderung ist nicht vollständig erfüllt | `utils/db.py:23` |
| BUG-PROJ2-4 | Minor | `SafePath` gibt ein `Path`-Objekt zurück, obwohl die Typ-Annotation `str` lautet. Die API kompensiert mit `isinstance(body.rules_path, Path)`-Check, aber die Typisierung ist inkonsistent | `models/move.py:16`, `api/move.py:111` |

### Gesamtbewertung

**PROJ-2 besteht QA.** Alle 8 Akzeptanzkriterien sind vollständig erfüllt. Alle 6 spezifizierten Randfälle werden korrekt behandelt. Keine kritischen oder hohen Sicherheitslücken gefunden. Die 4 Minor-Issues sind für ein lokales Single-User-Tool akzeptabel und blockieren keine Produktivnutzung.

## Deployment

**Datum:** 2026-02-24
**Deployment-Typ:** Lokal (macOS, uvicorn) – kein Cloud-Deployment
**Status:** ✅ BEREIT

### Lokaler Deployment-Checklist (CLAUDE.md)

| Prüfpunkt | Ergebnis | Detail |
|-----------|----------|--------|
| App startet via `uvicorn main:app --reload` | ✅ PASS | Server-Log bestätigt: `Application startup complete`, alle PROJ-2-Endpoints antworten korrekt |
| SQLite-Datenbankdatei in `/data` | ✅ PASS | `DB_PATH = Path("data/filemanager.db")` in `utils/db.py:18` – nicht in Source-Ordnern |
| Keine hardcodierten absoluten Pfade | ✅ PASS | Nur `Path(target).expanduser().resolve()` für nutzerseitige Eingaben; keine `/Users/...`-Pfade im Code |
| Destruktive Operationen mit Bestätigungsschritt | ✅ PASS | Die Vorschau-Tabelle mit Opt-out-Checkboxen ist der explizite Bestätigungsschritt; Execute-Button erst nach Review aktiv |
| `.gitignore` deckt `venv/`, `data/`, `__pycache__/`, `*.db` ab | ✅ PASS | Alle vier Kategorien in `.gitignore` vorhanden |
| Keine Secrets im Code | ✅ PASS | API-Keys via `.env` (gitignored); `.env.example` dokumentiert alle benötigten Variablen |
| PyInstaller `.app` | ⏭️ SKIP | Nicht erforderlich für PROJ-2 (optional per CLAUDE.md) |

### Offene Punkte

| # | Priorität | Beschreibung |
|---|-----------|--------------|
| 1 | Low | `.env.example` ist noch nicht committed (`?? .env.example` in `git status`). Sollte eingecheckt werden, damit neue Entwickler alle benötigten Umgebungsvariablen kennen. |
| 2 | Low | Alle PROJ-2-Dateien (`api/move.py`, `core/mover.py`, `templates/move.html`) sind noch uncommitted. Commit ausstehend. |

### Startup-Befehl

```bash
source venv/bin/activate
uvicorn main:app --reload --port 8000
# → http://127.0.0.1:8000/move/
```