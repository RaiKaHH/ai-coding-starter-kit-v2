# PROJ-2: Struktur-basierter Datei-Verschieber (Auto-Organizer)

## Status: Geplant
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-23

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
### Module
- `api/move.py` – routes: POST /move/preview/by-rules, POST /move/preview/by-pattern, POST /move/execute
- `core/mover.py` – YAML parsing (PyYAML), rule matching (fnmatch/re), shutil.move execution
- `models/move.py` – MoveByRulesRequest, MovePreviewItem, MovePreviewResponse, MoveExecuteRequest, MoveExecuteResult

### Datenbank
- Schreibt jede Verschiebung in `operation_log` (batch_id, MOVE, source_path, target_path)
- batch_id = UUID der gesamten Ausführungsaktion

### Wichtig
- Dry-Run und Execute sind strikt getrennte Codepfade in core/mover.py
- Regel-Priorität: Top-Down, erste Treffer gewinnt (kein Fallthrough)

## QA Testergebnisse
_Wird durch /qa ergänzt_

## Deployment
_Wird durch /deploy ergänzt_