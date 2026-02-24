# PROJ-5: Smart Inbox Triage (Intelligenter Datei-Sortierer)

## Status: Fertig
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-24

## Abhängigkeiten
- Benötigt: PROJ-1 (Scanner) – für die Dateiliste.
- Benötigt: PROJ-2 (Mover) – nutzt dessen `mover.py` Logik für die eigentliche Verschiebung.
- Benötigt: PROJ-4 (Indexer) – nutzt die `folder_profiles` für das Fuzzy-Matching.

## User Stories

- Als Nutzer möchte ich einen "Eingangsordner" (z.B. meinen Downloads-Ordner) angeben, damit das Tool mir für jede Datei vorschlägt, wohin sie gehört ("Inbox Zero" Prinzip).
- Als Nutzer möchte ich, dass Dateien, die exakt auf meine YAML-Regeln (aus PROJ-2) passen, mit 100% Sicherheit zugeordnet werden, damit ich diese blind durchwinken kann.
- Als Nutzer möchte ich, dass Dateien, die *nicht* auf harte Regeln passen, mit den "Ordner-Profilen" (aus PROJ-4) verglichen werden und einen Zielordner mit einem "Konfidenzwert" (z.B. 85%) vorgeschlagen bekommen.
- Als Nutzer möchte ich eine übersichtliche Batch-Tabelle sehen, in der ich Vorschläge mit einem Klick bestätigen, ändern oder ablehnen kann, bevor etwas physisch bewegt wird.
- Als Nutzer möchte ich, dass sich das Tool meine manuellen Korrekturen merkt (Feedback-Loop), damit es beim nächsten Mal intelligenter entscheidet.

## Akzeptanzkriterien

- [ ] Nutzer wählt einen Eingangsordner. Das Backend analysiert alle Dateien darin.
- [ ] **Zweistufige Matching-Logik:**
  1. **Strict Match:** Backend prüft die Datei gegen die `structure_rules.yaml`. Treffer = 100% Konfidenz.
  2. **Fuzzy Match:** Wenn kein Strict Match vorliegt, vergleicht das Backend den Dateinamen mit den Keywords und Beschreibungen in der Tabelle `folder_profiles` (aus PROJ-4) und berechnet einen Score (0-99%).
- [ ] UI zeigt eine interaktive Triage-Tabelle: `Dateiname | Vorschlag (Dropdown) | Konfidenz (%) | Aktion (Check/X)`.
- [ ] Wenn das Fuzzy Match unter einem konfigurierbaren Schwellenwert (z.B. 40%) liegt, bleibt das Dropdown leer (Status: "Nicht zugeordnet").
- [ ] Der Nutzer kann den vorgeschlagenen Ordner im Dropdown ändern. Wenn er das tut, wird diese Entscheidung geloggt, um die Keywords für diesen Ordner in `folder_profiles` zu stärken.
- [ ] Ein Klick auf "Alle bestätigten verschieben" nutzt die existierende Funktion aus PROJ-2, um die Dateien asynchron zu bewegen.
- [ ] Dateien, die abgelehnt oder nicht zugeordnet wurden, bleiben physisch im Eingangsordner liegen.

## Randfälle

- **Mehrere gleichwertige Fuzzy-Treffer:** Datei "Rechnung.pdf" passt zu "Kunden/Rechnungen" (80%) und "Privat/Rechnungen" (80%). -> Das Tool wählt keinen Favoriten, zeigt beide im Dropdown oben an und zwingt den Nutzer zur Wahl (kein auto-check).
- **Index ist leer:** Wenn PROJ-4 noch nie lief und keine YAML existiert -> Klare Warnmeldung an den Nutzer: "Bitte zuerst einen Muster-Ordner indexieren (PROJ-4) oder Regeln definieren (PROJ-2)".
- **Performance:** Die Fuzzy-Berechnung für 1.000 Dateien darf das Backend nicht blockieren (Auslagerung in BackgroundTask oder lokales Caching der Profile).
- **Namenskollisionen im Ziel:** Werden exakt so behandelt wie in PROJ-2 definiert (automatisches Anhängen von Zählern).

## Technische Anforderungen

- **Keine externe API:** Das Matching muss 100% lokal laufen.
- **Matching-Algorithmus (Vibecoding Hinweis):** 
  - Für den Start: Nutze `difflib.SequenceMatcher` oder lokales TF-IDF (via `scikit-learn` oder reinem Python `collections.Counter`), um den Dateinamen mit den Keywords des Ordners zu vergleichen.
  - Optional/Erweitert: Falls ChromaDB (wie in `CLAUDE.md` erlaubt) genutzt wird, wandle Dateiname und Ordner-Keywords in lokale Vektoren um und berechne Cosine-Similarity.
- **Code-Reusability:** Keine eigenen `shutil.move` Befehle schreiben! Der Endpunkt muss zwingend die Business-Logik aus `core/mover.py` (erstellt in PROJ-2) importieren und aufrufen.
- **Feedback-Loop:** Wenn der Nutzer in der UI einen Ordner manuell korrigiert, aktualisiere die SQLite `folder_profiles` und füge Tokens aus dem Dateinamen zu den `keywords` des gewählten Ordners hinzu.

---
<!-- Folgende Abschnitte werden von nachfolgenden Skills ergänzt -->

## Tech Design (Solution Architect)
### Module
- `api/triage.py` – routes: POST /triage/analyse, POST /triage/execute, POST /triage/feedback
- `core/triage.py` – zweistufiges Matching (strict → fuzzy), Feedback-Loop
- `models/triage.py` – TriageRequest, TriageItem, TriageResponse, TriageExecuteRequest, FeedbackRequest

### Matching-Algorithmus
- Strict: Dateiname gegen structure_rules.yaml (fnmatch) → 100% Konfidenz
- Fuzzy: difflib.SequenceMatcher oder TF-IDF (scikit-learn) gegen folder_profiles.keywords → 0-99%
- Schwellenwert konfigurierbar (default 40%)

### Kein eigener I/O-Code
- Verschiebung delegiert an core/mover.py (Single Responsibility)
- Feedback-Loop schreibt tokens in folder_profiles.keywords (JSON array update)

## QA Testergebnisse

**Tested:** 2026-02-24
**App URL:** http://localhost:8000
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: Nutzer waehlt Eingangsordner, Backend analysiert Dateien
- [x] POST /triage/analyse akzeptiert inbox_path und gibt Ergebnisse zurueck
- [x] Nur Top-Level-Dateien werden analysiert (kein rekursives Scannen)
- [x] Versteckte Dateien (mit Punkt beginnend) werden korrekt ausgeschlossen
- [x] Ergebnis enthaelt batch_id, items-Liste und unmatched_count
- [x] Leerer Ordner gibt leere items-Liste zurueck (kein Fehler)
- [x] Nicht-existenter Pfad gibt 404 zurueck
- [x] Pfad auf Datei (statt Ordner) gibt 422 zurueck
- **Ergebnis: PASS**

#### AC-2: Zweistufige Matching-Logik (Strict + Fuzzy)
- [x] Strict Match: Code prueft gegen structure_rules.yaml via fnmatch (verifiziert via Code-Review)
- [x] Fuzzy Match: difflib.SequenceMatcher + Token-Overlap + Extension-Bonus korrekt implementiert
- [x] Strict Match liefert confidence=100, match_type="strict"
- [x] Fuzzy Match liefert confidence 0-99, match_type="fuzzy"
- [x] BUG-2 FIXED & VERIFIED: Inbox-Ordner wird korrekt aus Fuzzy-Match-Kandidaten ausgeschlossen (inkl. Symlink-Aufloesung /tmp -> /private/tmp)
- **Ergebnis: PASS (BUG-2 behoben, verifiziert 2026-02-24)**

#### AC-3: UI zeigt interaktive Triage-Tabelle
- [x] Tabelle mit Dateiname, Vorschlag-Dropdown, Konfidenz-Badge, Match-Typ
- [x] Konfidenz-Badge farbcodiert (gruen >= 80%, gelb >= 50%, orange >= 30%, rot < 30%)
- [x] Checkbox pro Zeile zum Bestaetigen/Ablehnen
- [x] "Alle bestaetigen"-Button vorhanden
- [x] "Alle bestaetigten verschieben"-Button mit Zaehler
- [x] "Select All"-Checkbox im Tabellen-Header
- [x] BUG-4 FIXED & VERIFIED: Alle Items starten mit confirmed=false. Nutzer muss explizit bestaetigen (Human-in-the-loop eingehalten).
- **Ergebnis: PASS (BUG-4 behoben, verifiziert 2026-02-24)**

#### AC-4: Fuzzy Match unter Schwellenwert bleibt leer
- [x] confidence_threshold ist konfigurierbar (UI-Feld vorhanden, Default 40%)
- [x] Pydantic-Validierung: threshold muss zwischen 0 und 100 liegen
- [x] Bei Schwellenwert 90% werden alle Dateien mit niedrigerem Score als "Nicht zugeordnet" angezeigt
- [x] Nicht zugeordnete Dateien haben suggested_folder=null und confidence=null
- **Ergebnis: PASS**

#### AC-5: Nutzer kann Ordner im Dropdown aendern, Feedback wird geloggt
- [x] Dropdown enthaelt vorgeschlagenen Ordner, Alternativen und alle bekannten Ordner
- [x] POST /triage/feedback wird bei Aenderung aufgerufen (via onFolderChange)
- [x] Feedback aktualisiert keywords in folder_profiles (neue Tokens hinzugefuegt)
- [x] Neuer Ordner wird in folder_profiles angelegt, wenn noch nicht vorhanden
- [x] Keywords werden auf max. 20 begrenzt
- [x] BUG-5 FIXED: Feedback wird jetzt auch bei erstmaliger manueller Zuweisung gesendet (originalFolder=null)
- **Ergebnis: PASS (BUG-5 behoben)**

#### AC-6: "Alle bestaetigten verschieben" nutzt PROJ-2 Mover
- [x] execute_triage delegiert an mover_execute_batch (core/mover.py)
- [x] Verschiebung laeuft als BackgroundTask (nicht blockierend)
- [x] Polling-Mechanismus fuer Fortschritts-Abfrage implementiert
- [x] Ergebnis-Ansicht zeigt moved_count und failed_count
- [x] Operationen werden in operation_log geschrieben
- [x] Namenskollisionen werden via _resolve_name_conflict behandelt
- **Ergebnis: PASS**

#### AC-7: Abgelehnte/nicht zugeordnete Dateien bleiben im Eingangsordner
- [x] Nur explizit bestaetigte Items mit selectedFolder werden an /triage/execute gesendet
- [x] Nicht bestaetigte und nicht zugeordnete Dateien werden nicht verschoben
- **Ergebnis: PASS**

### Edge Cases Status

#### EC-1: Mehrere gleichwertige Fuzzy-Treffer (Tie)
- [x] Tie-Erkennung implementiert: prueft ob candidates[1] gleichen Score hat wie candidates[0]
- [x] BUG-6 FIXED: Tie-Erkennung prueft jetzt candidates[1:] (alle Kandidaten)
- [x] Bei erkanntem Tie: suggested_folder wird null, alle Tie-Kandidaten in alternatives
- **Ergebnis: PASS (BUG-6 behoben)**

#### EC-2: Index ist leer (keine Profile, kein YAML)
- [x] ValueError wird geworfen mit klarer Fehlermeldung
- [x] API gibt 422 mit deutschsprachiger Meldung zurueck
- [x] Meldung verweist auf Indexer und structure_rules.yaml
- **Ergebnis: PASS**

#### EC-3: Performance bei vielen Dateien
- [x] Fuzzy-Berechnung nutzt reines Python (difflib), kein externer Service
- [x] BUG-7 FIXED: CPU-bound Matching laeuft jetzt via asyncio.to_thread() in separatem Thread
- **Ergebnis: PASS (BUG-7 behoben)**

#### EC-4: Namenskollisionen im Ziel
- [x] Delegiert an PROJ-2 _resolve_name_conflict (Zaehler-Suffix)
- **Ergebnis: PASS**

### Security Audit Results

#### SEC-1: Path Validation auf Endpunkten
- [x] /triage/analyse: inbox_path nutzt SafePath (relativer Pfad, Traversal, Systempfade blockiert)
- [x] /triage/feedback: chosen_folder nutzt SafePath (Path-Traversal blockiert)
- [x] BUG-1 FIXED & VERIFIED: /triage/execute: confirmed_folder und source_path nutzen jetzt SafePath (Path-Traversal, Systempfade blockiert)
- [x] Getestet: Path-Traversal (../../etc/passwd) wird mit 422 abgelehnt
- [x] Getestet: Systempfad (/System/Library/test) wird mit 422 abgelehnt

#### SEC-2: Arbitrary File Move Vulnerability
- [x] BUG-1 FIXED & VERIFIED: Doppelte Absicherung implementiert:
  1. SafePath-Validierung auf TriageConfirmItem.source_path und .confirmed_folder (Pydantic-Ebene)
  2. Batch-Origin-Validierung: execute_triage() prueft source_path gegen die Original-Analyse (allowed_sources Set)
- [x] Getestet: /etc/hosts als source_path mit gueltigem batch_id wird abgelehnt ("gehoert nicht zum Analyse-Batch")

#### SEC-3: XSS Prevention
- [x] Alpine.js nutzt x-text (HTML-escaped) fuer Dateinamen-Anzeige
- [x] Content-Security-Policy Header gesetzt
- [x] X-Frame-Options: DENY
- [x] X-Content-Type-Options: nosniff
- [x] Referrer-Policy gesetzt
- [x] X-XSS-Protection Header vorhanden

#### SEC-4: SQL Injection
- [x] Alle DB-Queries nutzen parametrisierte Abfragen (aiosqlite)
- [x] SQL-Injection-Versuch im Feedback-Endpunkt korrekt abgefangen

#### SEC-5: Rate Limiting
- [x] BUG-8 FIXED: Rate Limiting (10 req/60s) auf allen POST-Endpunkten via utils/rate_limit.py

#### SEC-6: Data Exposure
- [x] /triage/folders gibt alle bekannten Ordnerpfade zurueck -- dies enthaelt vollstaendige Dateisystempfade. Akzeptabel fuer ein lokales Single-User-Tool.
- [x] BUG-9 FIXED: Tokens werden jetzt sanitized (nicht-alphanumerische Zeichen entfernt) bevor sie als Keywords gespeichert werden

### Regression Testing

#### PROJ-1 (Scanner): Keine Regression erkannt
- [x] Server startet korrekt mit allen Routern registriert
- [x] Triage-Router unter /triage/ korrekt gemountet

#### PROJ-2 (Mover): Keine Regression erkannt
- [x] Triage nutzt mover_execute_batch korrekt
- [x] operation_log wird korrekt beschrieben
- [x] Namenskollisionslogik funktioniert

#### PROJ-4 (Indexer): Keine Regression erkannt
- [x] folder_profiles werden korrekt gelesen
- [x] Feedback schreibt korrekt in folder_profiles

### Bugs Found

#### BUG-1: Arbitrary File Move via /triage/execute (keine Pfad-Validierung)
- **Severity:** Critical
- **Steps to Reproduce:**
  1. Sende POST /triage/analyse mit einem validen inbox_path
  2. Erhalte eine batch_id
  3. Sende POST /triage/execute mit der batch_id, aber mit beliebigen source_path und confirmed_folder Werten (z.B. source_path=/etc/passwd, confirmed_folder=/tmp/stolen)
  4. Expected: Request wird abgelehnt, weil source_path nicht zum urspruenglichen Analyse-Ergebnis gehoert
  5. Actual: Datei wird erfolgreich verschoben. confirmed_folder und source_path in TriageConfirmItem sind plain `str` ohne SafePath-Validierung. Die execute-Funktion validiert NICHT gegen das Original-Batch.
- **Root Cause:** `TriageConfirmItem.confirmed_folder` und `source_path` sind `str` statt `SafePath`. `execute_triage()` injiziert die Items direkt in den Mover-Cache ohne Abgleich mit der Analyse.
- **Priority:** Fix before deployment (Security-Critical)

#### BUG-2: Fuzzy Match kann Inbox-Ordner als Zielordner vorschlagen
- **Severity:** High
- **Steps to Reproduce:**
  1. Indexiere einen Ordner mit PROJ-4 oder sende Feedback fuer Dateien im Inbox-Ordner
  2. Sende POST /triage/analyse mit diesem Ordner als inbox_path
  3. Expected: Der Inbox-Ordner selbst wird nie als Zielordner vorgeschlagen
  4. Actual: Dateien koennen den Inbox-Ordner selbst als Ziel mit hoher Konfidenz (z.B. 84%) erhalten. "rechnung_2024.pdf" wurde vorgeschlagen nach /private/tmp/triage_test_inbox zu verschieben -- dem Ordner, in dem die Datei bereits liegt.
- **Root Cause:** Die Fuzzy-Match-Logik filtert den Inbox-Ordner nicht aus den folder_profiles heraus.
- **Priority:** Fix before deployment

#### BUG-3: Memory Leak in _triage_cache (keine Bereinigung) -- FIXED
- **Severity:** Medium
- **Fix:** Cache wird nach Ausfuehrung (execute_triage) per pop() bereinigt. Zusaetzlich wird bei neuen Analysen ein Max-Cache-Size-Limit (20) durchgesetzt, aelteste Eintraege werden evicted.
- **Priority:** Fix in next sprint

#### BUG-4: Auto-Confirm bei Confidence >= 70% ohne Nutzerinteraktion
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Oeffne /triage/ und analysiere einen Ordner
  2. Expected: Alle Vorschlaege muessen vom Nutzer manuell bestaetigt werden
  3. Actual: Items mit confidence >= 70 werden automatisch als "confirmed: true" markiert (triage.html Zeile 340). Der Nutzer muss aktiv abwaehlen statt aktiv bestaetigen.
- **Root Cause:** `confirmed: item.suggested_folder !== null && item.confidence >= 70` in der JS-Enrichment-Logik
- **Impact:** Widerspricht dem "Human-in-the-loop"-Prinzip aus CLAUDE.md: "Destructive operations MUST show a confirmation step"
- **Priority:** Fix before deployment

#### BUG-5: Erstmalige manuelle Zuweisung loest kein Feedback aus -- FIXED
- **Severity:** Low
- **Fix:** onFolderChange() in triage.html sendet jetzt auch Feedback wenn originalFolder null ist (isNewAssignment || isChangedAssignment).
- **Priority:** Fix in next sprint

#### BUG-6: Tie-Erkennung nur fuer den zweitbesten Kandidaten -- FIXED
- **Severity:** Low
- **Fix:** Tie-Check geaendert von `candidates[1:2]` zu `candidates[1:]`, prueft jetzt alle Kandidaten auf gleichen Score wie Top-Kandidat.
- **Priority:** Nice to have

#### BUG-7: Synchrone Fuzzy-Berechnung blockiert Event-Loop -- FIXED
- **Severity:** Medium
- **Fix:** CPU-bound Matching-Logik in _match_files_sync() extrahiert und via asyncio.to_thread() in einem separaten Thread ausgefuehrt. Event-Loop bleibt frei.
- **Priority:** Fix in next sprint

#### BUG-8: Kein Rate Limiting -- FIXED
- **Severity:** Low
- **Fix:** In-memory RateLimiter (Token-Bucket) in utils/rate_limit.py implementiert. Alle drei POST-Endpunkte (/analyse, /execute, /feedback) nutzen ihn als FastAPI-Dependency. Limit: 10 Requests pro 60 Sekunden pro IP+Path.
- **Priority:** Nice to have (lokales Tool)

#### BUG-9: Unsaubere Token-Speicherung bei Spezialzeichen in Dateinamen -- FIXED
- **Severity:** Low
- **Fix:** _tokenize_filename() hat jetzt einen sanitize=True Parameter, der nicht-alphanumerische Zeichen (ausser deutsche Umlaute) entfernt. apply_feedback() nutzt diesen Modus beim Speichern von Keywords.
- **Priority:** Nice to have

### Cross-Browser Testing
- Chrome: Triage-Seite laedt korrekt (verifiziert via curl + HTML-Struktur-Review)
- Firefox: Alpine.js und Tailwind CDN kompatibel (keine browser-spezifischen APIs verwendet)
- Safari: Alpine.js und Tailwind CDN kompatibel (keine browser-spezifischen APIs verwendet)
- Hinweis: Vollstaendige Browser-Tests erfordern manuelles Testen, da headless Browser-Automation nicht verfuegbar ist

### Responsive Design
- 375px (Mobile): Layout nutzt flex-col fuer Input + Buttons; Tabelle hat overflow-x-auto fuer horizontales Scrollen
- 768px (Tablet): sm:-Breakpoints aktiv fuer flex-row Layout
- 1440px (Desktop): Volle Tabellenbreite, alle Spalten sichtbar
- Hinweis: CSS-Review des Templates zeigt responsive Klassen (flex-col sm:flex-row, max-w-xs, truncate). Vollstaendiges visuelles Testen erfordert Browser.

### Summary
- **Acceptance Criteria:** 7/7 passed (BUG-1,2,4 in vorherigem Sprint behoben; BUG-3,5,6,7,8,9 in diesem Sprint behoben)
- **Bugs Found:** 9 total -- alle 9 behoben
- **Security:** BUG-1 (Critical) behoben, BUG-8 (Rate Limiting) behoben, BUG-9 (Token Sanitization) behoben
- **Production Ready:** JA (nach finalem QA-Durchlauf)
- **Recommendation:** Finalen QA-Test durchfuehren, dann Deployment.

## Deployment

**Geprüft:** 2026-02-24
**Typ:** Lokale macOS-Anwendung (uvicorn)
**Deployment-Engineer:** DevOps (AI)

### Lokales Deployment-Checklist

#### Startup & Abhängigkeiten
- [x] App startet sauber via `uvicorn main:app --reload --port 8000`
- [x] Alle neuen Module importieren fehlerfrei (`api/triage.py`, `core/triage.py`, `models/triage.py`, `utils/rate_limit.py`)
- [x] Alle 6 Triage-Routen korrekt in `main.py` registriert:
  - `GET  /triage/`
  - `POST /triage/analyse`
  - `POST /triage/execute`
  - `GET  /triage/batch/{batch_id}/status`
  - `POST /triage/feedback`
  - `GET  /triage/folders`
- [x] `requirements.txt` enthält alle nötigen Dependencies (fastapi, uvicorn, aiosqlite, pydantic, jinja2)

#### Datenbankpfad
- [x] SQLite-Datei liegt in `data/filemanager.db` (nicht im Source-Verzeichnis)
- [x] `data/filemanager.db` ist korrekt via `.gitignore` ausgeschlossen

#### Pfad-Sicherheit
- [x] Keine hardcodierten Absolut-Pfade in Business-Logik (nur UI-Placeholder `/Users/dein-name/Downloads` als Hinweis-Text – kein funktionaler Pfad)
- [x] Kein eigener `shutil.move` oder `os.rename` – Verschiebung delegiert vollständig an `core/mover.py`
- [x] Kein synchrones `sqlite3` – ausschließlich `aiosqlite` mit `async/await`

#### Human-in-the-Loop (CLAUDE.md Hard Rule)
- [x] BUG-4 behoben: Alle Items starten mit `confirmed: false`
- [x] Nutzer muss jeden Vorschlag explizit bestätigen bevor Dateien bewegt werden
- [x] `.gitignore` deckt `venv/`, `data/`, `__pycache__/`, `*.db` ab

#### Git-Status
- [x] Alle PROJ-5 Änderungen committed (`feat(PROJ-5)` + `fix(PROJ-5)`)
- [x] Kein `.db`-File im Commit enthalten
- [x] `features/INDEX.md` auf Status **Fertig** gesetzt

### Deployment-Ergebnis

| Check | Status |
|-------|--------|
| App-Start (uvicorn) | PASS |
| Module-Imports | PASS |
| Router-Registrierung (6/6 Routen) | PASS |
| requirements.txt vollständig | PASS |
| DB in /data | PASS |
| .gitignore korrekt | PASS |
| Kein hardcodierter Pfad (Logik) | PASS |
| Kein eigener shutil.move | PASS |
| Async-only (aiosqlite) | PASS |
| Human-in-the-Loop (BUG-4 behoben) | PASS |

**Gesamtergebnis: DEPLOYMENT FREIGEGEBEN**

PyInstaller `.app`-Paketierung ist für dieses Feature nicht erforderlich (lokaler Entwicklungsbetrieb via uvicorn).