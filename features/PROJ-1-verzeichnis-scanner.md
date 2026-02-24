# PROJ-1: Verzeichnis-Scanner

## Status: In Review
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-23

## Abhängigkeiten
- Keine

## User Stories

- Als Nutzer möchte ich einen beliebigen Ordnerpfad eingeben und eine vollständige Übersicht aller enthaltenen Dateien erhalten, damit ich einen schnellen Überblick über die Struktur bekomme.
- Als Nutzer möchte ich für jede Datei Größe, Dateityp, Erstellungs- und Änderungsdatum sehen, damit ich entscheiden kann, was verschoben oder umbenannt werden soll.
- Als Nutzer möchte ich auch tief verschachtelte Unterordner scannen (rekursiv), damit keine Datei übersehen wird.
- Als Nutzer möchte ich die Ergebnisse nach Dateityp, Größe und Datum filtern, damit ich mich auf relevante Dateien konzentrieren kann.
- Als Nutzer möchte ich den Scan-Fortschritt in Echtzeit sehen, damit ich weiß, dass das Tool arbeitet und nicht hängt.
- Als Nutzer möchte ich den Zielordner idealerweise über einen echten macOS-Finder-Dialog auswählen können (getriggert über einen Button in der UI), damit die Bedienung nativ wirkt. Ein einfaches Textfeld für die manuelle Pfadeingabe (z.B. via "alt+command+c") dient als Fallback.

## Akzeptanzkriterien

- [ ] UI bietet einen Button "Ordner auswählen", der das Backend anweist, einen nativen macOS-Auswahldialog zu öffnen und den gewählten Pfad ins Textfeld zu laden.
- [ ] Nutzer kann alternativ einen Ordnerpfad manuell über die Web-UI eingeben.
- [ ] Die Dateiliste zeigt: Dateiname, relativer Pfad, Größe (human-readable, z.B. "4,2 MB"), MIME-Typ, Erstellungsdatum, letztes Änderungsdatum.
- [ ] Rekursiver Scan erfasst alle Dateien in allen Unterordnern.
- [ ] Scan von 10.000 Dateien wird abgeschlossen ohne UI-Freeze.
- [ ] Fortschrittsanzeige während des Scans (z.B. "4.231 / 10.000 Dateien gescannt …").
- [ ] Ergebnisse können nach Name, Größe, Typ und Datum auf- und absteigend sortiert werden.
- [ ] Filterung nach Dateiendung (z.B. nur `.pdf`) und Zeitraum (Erstellungsdatum von/bis) möglich.
- [ ] Scan-Ergebnis wird in SQLite gespeichert (mit `scan_id` und Zeitstempel, für Wiederverwendung).
- [ ] Ungültige oder nicht zugängliche Pfade zeigen eine verständliche Fehlermeldung.

## Randfälle

- Pfad existiert nicht → klare Fehlermeldung, kein Absturz.
- Pfad zeigt auf eine Datei statt auf einen Ordner → Fehlermeldung mit Hinweis.
- Ordner mit Schreibschutz → Dateien werden gelistet (nur Lesezugriff nötig), kein Fehler.
- Symlinks → werden als Symlinks markiert, nicht rekursiv verfolgt (verhindert Endlosschleifen).
- Sehr tiefe Verschachtelung (>20 Ebenen) → kein Stack Overflow, Performance bleibt stabil.
- Leerer Ordner → leere Liste mit entsprechender Meldung, kein Fehler.
- Dateien ohne Leseberechtigung → werden mit "Zugriff verweigert" markiert, Scan läuft weiter.
- Ordnerpfad mit Sonderzeichen oder Leerzeichen → wird korrekt verarbeitet.

## Technische Anforderungen

- **Leistung:** Scan von 10.000 Dateien in unter 10 Sekunden.
- **Asynchron:** Scan läuft als FastAPI `BackgroundTask`, UI bleibt reaktionsfähig.
- **Fortschrittsanzeige (KISS-Prinzip):** Nutzung von simplem Short-Polling (z.B. Alpine.js fragt alle 500ms `GET /scan/{id}/status` ab) anstelle von komplexen, fehleranfälligen WebSockets.
- **Nativer macOS Dialog:** Das Backend nutzt lokale Bordmittel (z.B. `subprocess` mit `osascript` oder `tkinter`), um den Finder-Dialog zu öffnen, da der Browser dies aus Sandbox-Gründen nicht darf.
- **Caching:** Ergebnisse in SQLite speichern mit `scan_id` und Zeitstempel.
- **Sicherheit:** Pfadeingaben mit Pydantic v2 validieren (Path Traversal verhindern).
- **Pfade:** Ausschließlich `pathlib.Path` verwenden, keine raw Strings.

---
<!-- Folgende Abschnitte werden von nachfolgenden Skills ergänzt -->

## Tech Design (Solution Architect)
### Module
- `api/scan.py` – routes: POST /scan/start, GET /scan/{id}/status, GET /scan/{id}/files, POST /scan/pick-folder
- `core/analyzer.py` – recursive directory walk, metadata collection, symlink detection
- `models/scan.py` – ScanRequest, ScanFile, ScanStatus, ScanResult, ScanFilterRequest

### Datenbank
- Tabelle `scans`: scan_id (UUID), source_path, status, file_count, created_at
- Tabelle `scan_files`: FK → scans.scan_id, name, path, size_bytes, mime_type, created/modified timestamps, is_symlink, access_denied

### UI-Pattern
- Alpine.js `x-data` hält scan_id + polling-Interval
- Short-Polling alle 500 ms gegen `GET /scan/{id}/status`
- Folder-Picker: POST /scan/pick-folder → Backend öffnet osascript-Dialog, gibt Pfad zurück

## QA Testergebnisse
_Wird durch /qa ergänzt_

## Deployment
**Datum:** 2026-02-24
**Umgebung:** Lokal (macOS, uvicorn)
**Startup:** `source venv/bin/activate && uvicorn main:app --reload --port 8000`
**URL:** http://localhost:8000/scan
**Git-Tag:** v1.0.0-PROJ-1
