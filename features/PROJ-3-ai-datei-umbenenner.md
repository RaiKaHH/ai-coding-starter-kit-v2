# PROJ-3: AI-gestützter & Inhaltsbasierter Datei-Umbenenner

## Status: Fertig
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-24

## Abhängigkeiten
- Benötigt: PROJ-1 (Verzeichnis-Scanner) – liefert die zu verarbeitenden Dateien.
- Benötigt: PROJ-6 (KI-Integrations-Schicht / AI Gateway) – stellt die einheitliche `ai_service.py` Schnittstelle für Ollama/Mistral bereit. Kein eigener API-Code in diesem Modul.

## User Stories

- Als Nutzer möchte ich, dass *jede* umbenannte Datei zwingend mit einem Datum beginnt (`YYYY-MM-DD_...`), damit eine chronologische Sortierung auf Dateisystem-Ebene garantiert ist.
- Als Nutzer möchte ich, dass das Tool den *Inhalt* der Datei (z.B. Rechnungen, Verträge, Briefe) selbstständig liest und das tatsächliche "Dokumentendatum" sowie einen stark beschreibenden Dateinamen extrahiert, anstatt sich nur auf dumme Metadaten zu verlassen.
- Als Nutzer brauche ich zwei Modi: 
  1. **"Fast Mode" (Metadaten):** Nutzt nur Erstellungs-/EXIF-Datum und behält den alten Namen (für tausende Urlaubsfotos).
  2. **"Smart Mode" (AI-Analyse):** Liest den Dateiinhalt und generiert den Namen via KI (für Dokumente, Scans, Rechnungen).
- Als Nutzer möchte ich für den "Smart Mode" primär eine lokale KI (z.B. Ollama) nutzen, um maximale Privatsphäre zu haben. Falls diese nicht ausreicht oder zu langsam ist, möchte ich optional einen API-Key (z.B. Mistral) hinterlegen können.
- Als Nutzer möchte ich vor dem eigentlichen Umbenennen zwingend eine Vorschau-Tabelle (Alter Name -> Neuer Name) sehen, um KI-Halluzinationen auszuschließen.

## Akzeptanzkriterien

- [ ] UI bietet einen Toggle/Dropdown für den Modus: `Metadaten (Schnell)` vs. `KI-Inhaltsanalyse (Intelligent)`.
- [ ] Jede resultierende Datei folgt strikt dem Muster: `YYYY-MM-DD_beschreibender_text.ext`.
- [ ] **Smart Mode Logik:**
  - Extrahiert Text aus der Datei via `utils/text_extractor.py` (PDF-Text, Txt, oder via OCR bei Bildern/Scans). **Wichtig:** Liest maximal die ersten 2.000 Zeichen (oder die ersten 2 Seiten bei PDFs), um das Token-Limit des LLMs und RAM-Overflows zu verhindern.
  - Sendet den Text an das ausgewählte LLM (Ollama lokal oder Mistral API) mit dem Prompt, das Dokumentendatum und einen passenden, kurzen Dateinamen (max. 5 Wörter, snake_case) zu finden.
- [ ] **Fallback-Kette für das Datum:** 
  1. KI-gefundenes Dokumentendatum (z.B. Rechnungsdatum) -> 2. EXIF-Datum (bei Fotos) -> 3. Datei-Erstellungsdatum (OS-Level).
- [ ] Vorschau-Tabelle zeigt: `Aktueller Name` | `Gefundenes Datum` | `KI-Namensvorschlag` | `Neuer Ziel-Dateiname`.
- [ ] Nutzer kann in der Vorschau den KI-Vorschlag manuell überschreiben/korrigieren, bevor er das Umbenennen bestätigt.
- [ ] Jede Umbenennung wird in der SQLite-Datenbank protokolliert (Alter Pfad, Neuer Pfad, Modus, Zeitstempel), um spätere "Undo"-Funktionen zu ermöglichen.

## Randfälle

- **Kein Text extrahierbar:** Datei ist verschlüsselt oder OCR schlägt fehl → Fallback auf "Fast Mode" für diese spezifische Datei, Warnung in der UI.
- **KI halluziniert falsches Datum:** (z.B. 1.1.1970 oder ein Datum in der Zukunft) → Backend validiert das Datum (darf nicht in der Zukunft liegen). Bei Fehlschlag greift der Fallback auf das Erstellungsdatum.
- **Namenskollision:** Der neue Name `2024-03-15_telekom_rechnung.pdf` existiert bereits → Automatisches Anhängen von `_01`, `_02`.
- **Sonderzeichen im KI-Namen:** KI schlägt Namen mit `/`, `:`, `\` oder Emojis vor → Backend bereinigt den String strikt (nur `a-z`, `0-9`, `-`, `_` erlaubt).
- **Ollama nicht erreichbar:** Wenn der Nutzer lokalen KI-Modus wählt, aber Ollama nicht läuft → Klare Fehlermeldung in der UI, bevor der Batch startet.

## Technische Anforderungen

- **Textextraktion:** Nutzung von `utils/text_extractor.py` (gemeinsam mit PROJ-8), das intern `pypdf` (native PDFs) und `pytesseract` (OCR für Bilder/gescannte PDFs) kapselt. Max. 2.000 Zeichen pro Datei.
- **KI-Integration:** Strukturierter JSON-Output (`response_format={"type": "json_object"}`) muss vom LLM erzwungen werden, z.B.: `{"datum": "2024-03-15", "dateiname": "rechnung_telekom_internet"}`.
- **Validierung:** Pydantic v2 nutzen, um die JSON-Antwort der KI strikt zu validieren und abzufangen, wenn die KI Quatsch antwortet.
- **Asynchron & Queues:** KI-Anfragen dauern lange. Der Scan muss als `BackgroundTask` laufen. Die Concurrency-Steuerung (max. 3 gleichzeitige KI-Anfragen) wird vollständig von `core/ai_service.py` (PROJ-6) verwaltet — kein eigenes Semaphore in diesem Modul.
- **Abhängigkeiten:** Das Tool darf weiterhin keine Cloud-Abhängigkeiten haben, es sei denn, der Nutzer gibt explizit einen API-Key in einer Settings-UI ein.

---
<!-- Folgende Abschnitte werden von nachfolgenden Skills ergänzt -->

## Tech Design (Solution Architect)
### Module
- `api/rename.py` – routes: POST /rename/preview, POST /rename/execute
- `core/renamer.py` – Textextraktion (pypdf, pytesseract), AI-Aufruf via ai_service.py, Datumsfallback-Kette
- `models/rename.py` – RenameRequest, RenamePreviewItem, RenamePreviewResponse, RenameExecuteRequest, AIRenameResult

### Datenbank
- Schreibt jede Umbenennung in `operation_log` (batch_id, RENAME, source_path, target_path, mode)

### Concurrency
- asyncio.Semaphore(3) in core/renamer.py für AI-Aufrufe
- Kein eigener HTTP-Code: Delegiert an core/ai_service.py

## QA Testergebnisse
**Getestet am:** 2026-02-24
**Ergebnis:** BESTANDEN (1 Bug gefunden und behoben)

### Akzeptanzkriterien

- [x] UI bietet Toggle für `Metadaten (Schnell)` vs. `KI-Inhaltsanalyse (Intelligent)` — `templates/rename.html` Step 2
- [x] Jede Datei folgt strikt `YYYY-MM-DD_beschreibender_text.ext` — `_build_target_filename()` verifiziert
- [x] Smart Mode: Text-Extraktion via `utils/text_extractor.py`, max. 2.000 Zeichen (`MAX_CHARS = 2000`) — verifiziert
- [x] Fallback-Kette AI → EXIF → OS — `_generate_smart_preview()` implementiert und korrekt
- [x] Vorschau-Tabelle mit 4 Spalten (Aktueller Name, Datum, KI-Vorschlag, Ziel-Dateiname) — `RenamePreviewItem` vollständig
- [x] Nutzer kann Vorschlag in der Tabelle überschreiben (`editable=True`, `new_filename` editierbar)
- [x] Umbenennung in `operation_log` mit `batch_id`, `operation_type='RENAME'`, `mode`, `timestamp` protokolliert

### Tests & Ergebnisse

| Test | Ergebnis |
|------|----------|
| Alle Module importieren ohne Fehler | ✓ |
| `text_extractor`: Klartext-Extraktion | ✓ |
| `text_extractor`: Fehlende Datei → `("", False)` | ✓ |
| `text_extractor`: Nicht unterstützte Endung → `("", False)` | ✓ |
| `text_extractor`: 2000-Zeichen-Cap korrekt | ✓ |
| `_sanitize_filename`: Leerzeichen → `_`, Kleinschreibung | ✓ |
| `_sanitize_filename`: Maximale Länge 60 Zeichen | ✓ |
| `_sanitize_filename`: Leerer String → `"unnamed"` | ✓ |
| `_validate_date`: Zukunftsdaten rejected | ✓ |
| `_validate_date`: Vor-1900-Daten rejected | ✓ |
| `_validate_date`: Ungültige Strings rejected | ✓ |
| `_build_target_filename`: Korrekte `YYYY-MM-DD_name.ext` Ausgabe | ✓ |
| `_resolve_name_conflict`: Anhängen von `_01`, `_02` | ✓ |
| Pydantic: Pfad-Traversal (`../etc/passwd`) blockiert | ✓ |
| Pydantic: Null-Byte-Injection blockiert | ✓ |
| Pydantic: Leerer Dateiname blockiert | ✓ |
| Pydantic: >500 Datei-IDs blockiert | ✓ |

### Behobene Bugs

- **BUG-QA-1 (behoben):** `_sanitize_filename()` entfernte `/`, `:` und `\` lautlos anstatt sie in `_` umzuwandeln. Resultat: `rechnung/telekom:internet` wurde zu `rechnungtelekominternet` statt `rechnung_telekom_internet`. Fix: Explizite Ersetzung dieser Zeichen vor dem Regex-Cleanup in `core/renamer.py:135`.

## Deployment
**Deployed am:** 2026-02-24
**Typ:** Lokal (macOS, uvicorn)

### Lokaler Deployment-Check (2026-02-24)
- [x] `python -c "import main"` – App startet ohne Fehler
- [x] Alle PROJ-3-Module laden korrekt (`utils/text_extractor`, `core/renamer`, `api/rename`)
- [x] Alle Python-Abhängigkeiten in `requirements.txt` eingetragen (`pypdf`, `pytesseract`, `Pillow`, `exifread`)
- [x] `tesseract` (v5.5.1) als System-Binary vorhanden – OCR funktionsfähig
- [x] Keine hardcodierten Absolut-Pfade im Code
- [x] Keine Secrets im Code – API-Keys nur via `.env`-Datei
- [x] Destructive Operation (Umbenennen) erfordert explizite UI-Bestätigung (Preview-Schritt)
- [x] SQLite-Datenbank liegt in `/data/` – nicht im Source-Verzeichnis

### Start-Kommando
```bash
source venv/bin/activate
uvicorn main:app --reload --port 8000
# Rename-UI: http://localhost:8000/rename
```

### Systemvoraussetzung: tesseract (nur für OCR)
```bash
# macOS (einmalig, falls nicht vorhanden)
brew install tesseract
```