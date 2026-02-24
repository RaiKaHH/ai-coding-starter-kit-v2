# Feature Index

> Zentrale Übersicht aller Features. Wird von Skills automatisch aktualisiert.

## Status-Legende
- **Geplant** – Anforderungen dokumentiert, bereit für Entwicklung
- **In Bearbeitung** – Wird aktuell gebaut
- **In Review** – QA-Tests laufen
- **Fertig** – Live im Einsatz

## Features

| ID | Feature | Status | Spec | Erstellt |
|----|---------|--------|------|---------|
| PROJ-1 | Verzeichnis-Scanner | Fertig | [PROJ-1-verzeichnis-scanner.md](PROJ-1-verzeichnis-scanner.md) | 2026-02-23 |
| PROJ-2 | Struktur-basierter Datei-Verschieber | Fertig | [PROJ-2-struktur-verschieber.md](PROJ-2-struktur-verschieber.md) | 2026-02-23 |
| PROJ-3 | AI-gestützter Datei-Umbenenner | Fertig | [PROJ-3-ai-datei-umbenenner.md](PROJ-3-ai-datei-umbenenner.md) | 2026-02-23 |
| PROJ-4 | Semantischer Struktur-Lerner | Fertig | [PROJ-4-semantischer-lerner.md](PROJ-4-semantischer-lerner.md) | 2026-02-23 |
| PROJ-5 | Smart Inbox Triage | Fertig | [PROJ-5-smart-inbox-triage.md](PROJ-5-smart-inbox-triage.md) | 2026-02-23 |
| PROJ-6 | KI-Integrations-Schicht (Gateway) | Fertig | [PROJ-6-ki-gateway.md](PROJ-6-ki-gateway.md) | 2026-02-23 |
| PROJ-8 | Deep-AI Smart Sorting | Geplant | [PROJ-8-deep-ai-sorting.md](PROJ-8-deep-ai-sorting.md) | 2026-02-23 |
| PROJ-9 | Undo / Rollback für Verschiebe- und Umbenenn-Aktionen | Geplant | [PROJ-9-undo-rollback.md](PROJ-9-undo-rollback.md) | 2026-02-23 |

*(Hinweis: PROJ-7 wurde absichtlich entfernt, da die Funktionalität in das verbesserte PROJ-3 integriert wurde)*

<!-- Neue Features oberhalb dieser Zeile einfügen -->

## Empfohlene Build-Reihenfolge

1. **PROJ-1 – Verzeichnis-Scanner**
   *Das Fundament. Muss stehen, um überhaupt Dateien einlesen zu können.*
2. **PROJ-6 – KI-Integrations-Schicht (Gateway)**
   *Die Engine. Muss früh gebaut werden, damit die nachfolgenden KI-Features dieses Modul nutzen können, ohne eigenen API-Code zu schreiben.*
3. **PROJ-3 – AI-gestützter Datei-Umbenenner**
   *Nutzt PROJ-1 und PROJ-6. Macht unleserliche Dateien sauber. Schreibt als erstes Modul in `operation_log` (Schema wird hier angelegt).*
4. **PROJ-4 – Semantischer Struktur-Lerner**
   *Nutzt PROJ-1 und PROJ-6. Lernt aus deinen "sauberen" Ordnern, wie deine ideale Struktur aussieht.*
5. **PROJ-2 – Struktur-basierter Datei-Verschieber (Mover)**
   *Die reine Ausführungs-Logik. Schreibt MOVE-Operationen in `operation_log`.*
6. **PROJ-5 – Smart Inbox Triage (Lokales Matching)**
   *Das UI-Dashboard. Nutzt das Wissen aus PROJ-4 und die Ausführungslogik aus PROJ-2 für blitzschnelles, lokales Vorsortieren.*
7. **PROJ-8 – Deep-AI Smart Sorting**
   *Das Upgrade für PROJ-5. Wenn das lokale Matching unsicher ist, wird die Datei an PROJ-6 (KI) geschickt.*
8. **PROJ-9 – Undo / Rollback**
   *Sicherheitsnetz. Liest `operation_log` aus PROJ-2/PROJ-3 und macht jede Aktion per LIFO-Rollback rückgängig.*

## Nächste verfügbare ID: PROJ-10