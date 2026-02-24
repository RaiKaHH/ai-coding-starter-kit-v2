# PROJ-4: Semantischer Struktur-Lerner & Regel-Generator

## Status: Geplant
**Erstellt:** 2026-02-23
**Zuletzt aktualisiert:** 2026-02-23

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
### Module
- `api/index.py` – routes: POST /index/start, GET /index/status, GET /index/profiles, GET /index/export-yaml
- `core/lerner.py` – Ordner-Aggregation (collections.Counter), AI-Profiling via ai_service.py, YAML-Export (PyYAML)
- `models/index.py` – IndexRequest, FolderProfile, IndexStatus, YamlExportResponse

### Datenbank
- Tabelle `folder_profiles`: folder_path (UNIQUE), primary_extension, ai_description, keywords (JSON), file_count, indexed_at
- YAML-Export liest folder_profiles und generiert structure_rules.yaml für PROJ-2

### Sampling
- Max 50 Dateinamen pro Ordner an LLM (Token-Limit-Schutz)
- asyncio.Queue mit max 2-3 gleichzeitigen AI-Calls

## QA Testergebnisse
_Wird durch /qa ergänzt_

## Deployment
_Wird durch /deploy ergänzt_