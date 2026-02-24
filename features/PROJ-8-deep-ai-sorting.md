# PROJ-8: Deep-AI Smart Sorting (Inbox Triage Upgrade)

## Status: Geplant
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-23

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
### Module
- `api/deep_sort.py` – routes: POST /deep-sort/analyse/{file}, POST /deep-sort/analyse-batch
- Kein eigenes Core-Modul: Orchestriert core/triage.py (Pre-Filtering) + core/ai_service.py (LLM-Aufruf)
- `models/ai_gateway.py` – AIFolderSuggestion (zielordner, begruendung)

### Datenbank
- Tabelle `ai_cache`: file_hash (SHA-256) → suggested_folder, reasoning, model_used, created_at
- Cache-Hit verhindert wiederholte teure LLM-Anfragen

### Pre-Filtering
- Top-20 Ordner via Fuzzy-Match aus PROJ-5 vor LLM-Aufruf
- Verhindert Token-Overflow bei großen Ordner-Indizes

### Halluzinations-Schutz
- Vorgeschlagener Zielordner wird gegen tatsächliche folder_profiles validiert
- Ungültige Ordner → Fehlermeldung statt stiller Fehler