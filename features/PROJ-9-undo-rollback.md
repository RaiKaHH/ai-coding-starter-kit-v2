# PROJ-9: Undo / Rollback-System (History & Revert)

## Status: In Bearbeitung
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-23

## Abhängigkeiten
- Benötigt: PROJ-2 (Mover) und PROJ-3 (Renamer) – Diese Module müssen ihre Aktionen in das zentrale `operation_log` schreiben.

## User Stories

- Als Nutzer möchte ich eine globale Historie aller Datei-Operationen (Verschiebungen, Umbenennungen) sehen, damit ich nachvollziehen kann, was das Tool (oder die KI) automatisiert getan hat.
- Als Nutzer möchte ich einen "Undo"-Button neben jeder Aktion haben, um einen Fehler mit einem Klick rückgängig zu machen (z.B. Datei wandert an ihren Ursprungsort/Ursprungsnamen zurück).
- Als Nutzer möchte ich einen ganzen "Batch" (z.B. 50 Dateien, die durch den Smart Sorter verschoben wurden) auf einmal rückgängig machen können, falls die KI-Regel falsch war.
- Als Nutzer möchte ich vor Datenverlust geschützt werden: Wenn das Rückgängigmachen nicht sicher ist (z.B. weil ich die Datei im Finder schon gelöscht habe), soll das Tool abbrechen und mich warnen.

## Akzeptanzkriterien

- [ ] UI zeigt eine paginierte Historien-Tabelle: `Zeitstempel` | `Aktion (Move/Rename)` | `Dateiname` | `Von` | `Nach` | `Status` | `Undo-Button`.
- [ ] Oben in der UI gibt es eine gruppierte "Batch-Ansicht" (z.B. "Batch #412: 50 Dateien verschoben -> [Ganzen Batch rückgängig machen]").
- [ ] **LIFO-Prinzip:** Ein Batch-Undo muss zwingend in *umgekehrter chronologischer Reihenfolge* (Last-In-First-Out) ausgeführt werden, damit Kaskaden (Datei A wurde zu B, dann zu C) fehlerfrei abgewickelt werden.
- [ ] **Sicherheits-Check vor jedem Undo:**
  1. Liegt die Datei noch am `Nach`-Pfad? (Wenn nein -> Abbruch).
  2. Ist der `Von`-Pfad frei? (Wenn belegt -> Nutzeraktion anfordern: "Überschreiben" oder "Abbrechen").
- [ ] Nach einem erfolgreichen Undo wird der Datenbank-Eintrag nicht gelöscht, sondern das Feld `status` wechselt von `completed` auf `reverted`.
- [ ] Wenn der ursprüngliche Ursprungs-Ordner (`Von`-Pfad) nicht mehr existiert, wird er vom Backend automatisch neu angelegt (`os.makedirs`).
- [ ] UI aktualisiert sich nach einem Batch-Undo dynamisch (via Alpine.js Polling).

## Randfälle

- **Datei manuell verändert:** Datei ist am Zielort noch da, aber wurde im Finder geändert (anderer Hash/Größe) → Das Tool ignoriert den Hash und verschiebt/umbenennt rein basierend auf dem Pfad (Keep it simple).
- **Teilweiser Batch-Fehler:** Wenn bei einem Batch-Undo (50 Dateien) Datei Nr. 12 fehlschlägt (weil gelöscht), wird diese übersprungen (Status `revert_failed`), aber der Rest des Batches wird weiter rückgängig gemacht.
- **Doppeltes Undo:** Backend ignoriert Undo-Requests für IDs, die bereits den Status `reverted` haben.
- **Undo eines Undos (Redo):** Wird in Version 1 *nicht* unterstützt (zu komplex). Ein reverted Eintrag bleibt reverted.

## Technische Anforderungen

- **Zentrales Datenbank-Schema (`operation_log`):**
  - `id` (PK)
  - `batch_id` (String/UUID, alle Aktionen eines Klicks bekommen dieselbe ID)
  - `operation_type` (Enum: `MOVE`, `RENAME`)
  - `source_path` (Absoluter Pfad vorher)
  - `target_path` (Absoluter Pfad nachher)
  - `timestamp` (DateTime)
  - `status` (Enum: `completed`, `reverted`, `revert_failed`)
- **Architektur-Hinweis für Vibecoding:** Das Schema der `operation_log` Tabelle ist zwar hier (PROJ-9) definiert, **muss aber technisch bereits in PROJ-2 und PROJ-3 angelegt und befüllt werden**. PROJ-9 baut am Ende nur noch die Lese-Logik (UI) und die Ausführungs-Logik (`revert`) auf dieser existierenden Tabelle auf.
- **Volume-Check:** Vor einem Undo prüft das Backend via `os.path.exists` oder `Path.mount`, ob das Ziellaufwerk (z.B. USB-Stick) überhaupt noch gemountet und erreichbar ist, bevor Datei-Operationen starten.
- **File Operations:** Zwingend `shutil.move()` nutzen (auch für Renames), da dies Partitions-übergreifend funktioniert.
- **Asynchron:** Batch-Undos laufen als FastAPI `BackgroundTask`.

---

## Tech Design (Solution Architect)

**Erstellt:** 2026-02-24
**Status nach Design:** In Bearbeitung

---

### Architektur-Überblick

PROJ-9 ist ein **reines Lese- und Revert-Feature** – es schreibt keine neuen Operationen, sondern liest ausschließlich aus der `operation_log`-Tabelle, die PROJ-2 (Mover) und PROJ-3 (Renamer) bereits befüllen.

Das Design ist absichtlich schlank gehalten:

```
PROJ-2 (core/mover.py)   ──┐
PROJ-3 (core/renamer.py) ──┤──► operation_log (SQLite) ──► api/history.py ──► Historien-UI
Triage-Bestätigung        ──┘                                      │
                                                            core/undo.py
                                                          (Revert-Logik)
```

---

### Modul-Struktur

| Datei | Status | Verantwortlichkeit |
|-------|--------|--------------------|
| `api/history.py` | **Stub** – Endpunkte definiert, Körper leer | HTTP-Routen: Lesen + Undo-Trigger |
| `core/undo.py` | **Stub** – nur Kommentare | Business Logic: LIFO, Pre-Flight-Checks, shutil.move |
| `models/history.py` | **Fertig** – keine Änderung nötig | Pydantic-Modelle für alle Request/Response-Typen |
| `templates/history.html` | **Stub** – leeres Skeleton | Vollständige UI: Tabelle, Batch-View, Polling |
| `utils/db.py` | **Fertig** – `operation_log` Tabelle angelegt | Schema + Indizes auf `batch_id` und `status` |

---

### Datenmodell (Plain Language)

#### Vorhandene SQLite-Tabelle: `operation_log`

Jede Verschiebe- oder Umbenenn-Aktion hinterlässt eine Zeile. PROJ-9 liest und ändert Status-Felder, löscht aber **niemals** Einträge.

| Feld | Typ | Beispiel | Beschreibung |
|------|-----|---------|--------------|
| `id` | Integer (PK) | `42` | Eindeutige ID der Aktion |
| `batch_id` | Text (UUID) | `"f3a9-..."` | Gruppiert alle Dateien eines Klicks |
| `operation_type` | Text | `"MOVE"` oder `"RENAME"` | Art der Aktion |
| `source_path` | Text | `"/Downloads/rechnung.pdf"` | Pfad **vor** der Aktion |
| `target_path` | Text | `"/Finanzen/rechnung.pdf"` | Pfad **nach** der Aktion |
| `timestamp` | Text | `"2026-02-24T10:00:00Z"` | Wann die Aktion stattfand |
| `status` | Text | `"completed"` | Aktueller Zustand (siehe unten) |
| `mode` | Text | `"smart"` | Woher kam die Regel (optional) |

**Status-Übergänge:**
```
completed ──► reverted        (Undo erfolgreich)
completed ──► revert_failed   (Undo fehlgeschlagen, Datei nicht mehr vorhanden)
```
→ Kein DELETE. Der Audit-Trail bleibt immer erhalten.

#### Vorhandene Pydantic-Modelle: `models/history.py` (fertig)

| Modell | Richtung | Felder |
|--------|----------|--------|
| `OperationLog` | Backend → Frontend | Alle Felder aus der DB-Tabelle |
| `BatchSummary` | Backend → Frontend | `batch_id`, `operation_type`, `file_count`, `timestamp`, `status` |
| `UndoSingleRequest` | Frontend → Backend | `operation_id` |
| `UndoBatchRequest` | Frontend → Backend | `batch_id` |
| `UndoResult` | Backend → Frontend | `success`, `message`, `reverted_count`, `failed_count`, `errors` |

---

### API-Endpunkte

| Methode | Pfad | Auslöser | Antwort |
|---------|------|----------|---------|
| `GET` | `/history/` | Seitenaufruf | HTML-Seite |
| `GET` | `/history/operations` | Tabelle laden (mit `?page`, `?page_size`, `?operation_type`) | `list[OperationLog]` |
| `GET` | `/history/batches` | Batch-Übersicht laden | `list[BatchSummary]` |
| `POST` | `/history/undo/{operation_id}` | Nutzer klickt Undo auf Einzelzeile | `UndoResult` |
| `POST` | `/history/undo/batch/{batch_id}` | Nutzer klickt "Ganzen Batch rückgängig" | `UndoResult` (sofort, startet BackgroundTask) |
| `GET` | `/history/batch/{batch_id}/status` | Frontend pollt Batch-Fortschritt | Fortschritts-Objekt |

---

### UI-Komponentenbaum (`templates/history.html`)

```
/history (Historien-Seite)
│
├── [NEU] Batch-Ansicht (oben, gruppiert nach batch_id)
│   ├── Batch-Karte: "Batch vom 24.02.2026, 14:23 – 50 Dateien verschoben"
│   │   ├── Status-Badge: "Erledigt" | "Rückgängig" | "Teilweise fehlgeschlagen"
│   │   └── Button: "Ganzen Batch rückgängig machen" (+ Bestätigungs-Modal)
│   └── [NEU] Fortschrittsleiste (x-show während Batch-Undo läuft)
│       Beispiel: "Mache rückgängig: 12 / 50 Dateien..."
│
└── [NEU] Einzel-Operationen (paginiert)
    ├── Filter-Leiste: [Alle | Nur MOVE | Nur RENAME]
    ├── Tabelle:
    │   ├── Spalten: Zeitstempel | Typ | Dateiname | Von → Nach | Status | Aktion
    │   ├── Zeile (status=completed):     → Button "↩ Rückgängig"
    │   ├── Zeile (status=reverted):      → Badge "✓ Rückgängig gemacht" (grün)
    │   └── Zeile (status=revert_failed): → Badge "✗ Fehlgeschlagen" (rot, mit Tooltip)
    └── Pagination: [← Zurück] Seite 2 / 7 [Weiter →]
```

---

### Ablauf: Einzelnes Undo

```
Nutzer klickt "↩ Rückgängig" auf Zeile 42 (rechnung.pdf wurde nach /Finanzen verschoben)
  │
  ├─ Bestätigungs-Modal: "Datei zurück nach /Downloads/rechnung.pdf verschieben?"
  │
  ├─ Frontend sendet: POST /history/undo/42
  │
  └─ Backend (core/undo.py):
      │
      ├─ 1. Pre-Flight Check: Liegt Datei noch bei target_path (/Finanzen/rechnung.pdf)?
      │   └─ Nein → HTTP 409, UndoResult(success=False, message="Datei nicht mehr vorhanden")
      │
      ├─ 2. Pre-Flight Check: Ist source_path (/Downloads/rechnung.pdf) frei?
      │   └─ Belegt → HTTP 409 mit Hinweis "Datei existiert bereits am Ursprungsort"
      │
      ├─ 3. Pre-Flight Check: Volume / Laufwerk noch gemountet?
      │   └─ Nein → HTTP 503 mit Hinweis "Laufwerk nicht erreichbar"
      │
      ├─ 4. Falls source_path-Ordner nicht mehr existiert → os.makedirs anlegen
      │
      ├─ 5. shutil.move(target_path → source_path) ausführen
      │
      ├─ 6. DB-Update: status = 'reverted'
      │
      └─ 7. UndoResult(success=True, reverted_count=1) zurückgeben
             → UI aktualisiert Zeile: Badge wechselt auf "✓ Rückgängig gemacht"
```

---

### Ablauf: Batch-Undo (LIFO)

```
Nutzer klickt "Ganzen Batch rückgängig machen" (50 Dateien)
  │
  ├─ Bestätigungs-Modal: "Wirklich alle 50 Dateien rückgängig machen?"
  │
  ├─ Frontend sendet: POST /history/undo/batch/{batch_id}
  │
  └─ Backend:
      ├─ Sofortige Antwort: {"running": true} (BackgroundTask gestartet)
      │
      └─ BackgroundTask (core/undo.py):
          ├─ Lade alle Operationen des Batches, sortiert nach timestamp DESC (LIFO!)
          │   → Warum LIFO? Wenn A→B→C, muss erst C→B, dann B→A rückgängig
          │
          ├─ Für jede Operation (in LIFO-Reihenfolge):
          │   ├─ Pre-Flight Checks (s.o.)
          │   ├─ Erfolg → status = 'reverted', reverted_count++
          │   └─ Fehler → status = 'revert_failed', failed_count++, weiter (kein Abbruch!)
          │
          └─ Status im In-Memory-Dict speichern (für Polling)

Frontend pollt alle 1s: GET /history/batch/{batch_id}/status
  → Fortschrittsleiste: "12 / 50 erledigt"
  → Abschluss: "48 rückgängig gemacht, 2 fehlgeschlagen"
```

---

### Randfälle und Verhalten

| Situation | Backend-Verhalten | UI-Verhalten |
|-----------|------------------|--------------|
| Datei am Zielort nicht mehr vorhanden | `revert_failed`, kein shutil.move | Roter Badge "Fehlgeschlagen", Tooltip "Datei wurde manuell gelöscht" |
| Quelldaten-Ordner existiert nicht mehr | `os.makedirs` anlegen, dann shutil.move | Normaler Ablauf |
| Datei am Ursprungsort bereits vorhanden | HTTP 409, kein Überschreiben | Meldung "Datei existiert bereits am Ursprungsort" |
| Volume nicht gemountet | HTTP 503 vor Dateioperation | Rote Inline-Meldung "Laufwerk nicht erreichbar" |
| Doppelter Undo (status=reverted) | HTTP 400 sofort zurück | Button bereits ausgegraut (reverted-Badge) |
| Redo (Undo eines Undos) | **Nicht unterstützt in v1** | Kein "Wiederherstellen"-Button vorhanden |
| Teilweiser Batch-Fehler | Fehler loggen, Rest weiter abarbeiten | "X fehlgeschlagen" im Abschlussbanner |

---

### Schlüssel-Entscheidungen (Warum so?)

**Warum LIFO statt FIFO?**
Wenn Datei A zuerst nach B, dann nach C verschoben wurde, muss zuerst C→B (die neueste Aktion) rückgängig gemacht werden. Sonst versucht das System, C→A zu machen, obwohl C gerade noch das Ziel von B→C ist.

**Warum kein DELETE der Log-Einträge?**
Der Audit-Trail ist der Kern des Features. Der Nutzer soll jederzeit sehen können, was passiert ist – auch nach einem Undo. Status-Wechsel statt Löschen schützt diese History.

**Warum BackgroundTask für Batch?**
Ein Batch von 50+ Dateien mit je einem shutil.move kann mehrere Sekunden dauern. Ein synchroner HTTP-Request würde in diesem Zeitrahmen timeouten. BackgroundTask + Polling ist das etablierte Muster im Projekt (konsistent mit PROJ-8 und PROJ-5).

**Warum shutil.move statt os.rename?**
`os.rename()` schlägt fehl, wenn Quelle und Ziel auf verschiedenen Partitionen liegen (z.B. Desktop auf Hauptlaufwerk, Backup auf USB-Stick). `shutil.move()` kopiert in diesem Fall und löscht danach – funktioniert partitionsübergreifend.

---

### Abhängigkeiten

Keine neuen Python-Packages. Alle Bausteine sind vorhanden:

| Baustein | Kommt aus | Genutzt für |
|----------|-----------|-------------|
| `operation_log` Tabelle | PROJ-2 + PROJ-3 | Datenquelle für alle Undo-Operationen |
| `aiosqlite` | vorhanden | DB-Zugriff |
| `shutil` (stdlib) | Python | Datei-Move/-Rename beim Revert |
| `os.makedirs` (stdlib) | Python | Fehlende Ordner anlegen |
| `pathlib.Path` (stdlib) | Python | Volume/Mount-Check |
| Alpine.js | vorhanden (CDN) | Polling, UI-Updates ohne Reload |