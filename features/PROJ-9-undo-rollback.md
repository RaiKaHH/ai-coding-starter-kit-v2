# PROJ-9: Undo / Rollback-System (History & Revert)

## Status: Geplant
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
### Module
- `api/history.py` – routes: GET /history/operations, GET /history/batches, POST /history/undo/{id}, POST /history/undo/batch/{batch_id}
- `core/undo.py` – LIFO-Batch-Undo, Pre-Flight-Checks, shutil.move für Revert
- `models/history.py` – OperationLog, BatchSummary, UndoSingleRequest, UndoBatchRequest, UndoResult

### Datenbank
- Zentrale Tabelle `operation_log` (definiert in utils/db.py):
  batch_id, operation_type (MOVE/RENAME), source_path, target_path, timestamp, status, mode
- Index auf batch_id und status für schnelle Abfragen

### Schema-Hinweis
- operation_log wird bereits von PROJ-2 (mover.py) und PROJ-3 (renamer.py) befüllt
- PROJ-9 fügt nur Lese-Logik und Revert-Logik hinzu
- Status-Feld: completed → reverted oder revert_failed (kein DELETE)