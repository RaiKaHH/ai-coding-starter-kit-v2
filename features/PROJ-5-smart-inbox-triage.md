# PROJ-5: Smart Inbox Triage (Intelligenter Datei-Sortierer)

## Status: Geplant
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-23

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
_Wird durch /qa ergänzt_

## Deployment
_Wird durch /deploy ergänzt_