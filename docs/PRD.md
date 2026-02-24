# Product Requirements Document

## Vision

FileSorter ist ein persönliches macOS-Werkzeug zur lokalen Dateiorganisation.
Es hilft dem Nutzer, Dateien automatisch zu benennen, zu verschieben und zu sortieren –
basierend auf Regeln, Datum und einer lernenden Engine, die bestehende Ordnerstrukturen versteht.
Alle Operationen laufen vollständig lokal, ohne Cloud oder externe Dienste.

## Zielgruppe

**Primärer Nutzer:** Einzelentwickler (Solo-Developer), der das Tool für den eigenen Mac baut und nutzt.

**Probleme:**
- Dateien sammeln sich ungeordnet im Downloads-Ordner und auf dem Desktop an
- Dateien haben nichtssagende Namen wie `IMG_1234.jpg` oder `document(3).pdf`
- Es fehlt ein systematischer Weg, Dateien verlässlich in die richtige Ordnerstruktur zu verschieben

**Bedürfnisse:**
- Schnelle, sichere Sortierung ohne manuelle Arbeit
- Volle Kontrolle über jede Änderung (keine Überraschungen, immer Bestätigung)
- Ein Tool, das mit der Zeit besser wird – je mehr es über die eigene Struktur lernt

## Core Features (Roadmap)

| Priorität | Feature | Status |
|-----------|---------|--------|
| P0 (MVP) | Verzeichnis-Scanner (PROJ-1) | Geplant |
| P0 (MVP) | Struktur-basierter Datei-Verschieber (PROJ-2) | Geplant |
| P0 (MVP) | AI-gestützter Datei-Umbenenner (PROJ-3) | Geplant |
| P0 (MVP) | Semantischer Struktur-Lerner (PROJ-4) | Geplant |
| P0 (MVP) | KI-Integrations-Schicht / Gateway (PROJ-6) | Geplant |
| P0 (MVP) | Smart Inbox Triage (PROJ-5) | Geplant |
| P1 | Undo / Rollback (PROJ-9) | Geplant |
| P2 | Deep-AI Smart Sorting (PROJ-8) | Geplant |

## Erfolgskriterien

- Dateien können in unter 5 Sekunden einem bestehenden Ordner zugeordnet werden
- Keine Datei wird ohne explizite Nutzerbestätigung verschoben oder umbenannt
- Der Smart Sorter erreicht nach dem Indexieren von >100 Dateien eine Trefferquote von >80 %
- Das Tool startet zuverlässig über `uvicorn` auf jedem Mac ohne manuelle Konfiguration
- Scans von 10.000+ Dateien führen zu keinem UI-Freeze

## Einschränkungen

- Solo-Entwickler: kein Team, kein Budget für externe Services (außer optionale Mistral API)
- Keine Infrastruktur: nur uvicorn + SQLite, kein Docker, keine Daemons
- Alle Kern-Funktionen müssen offline funktionieren
- Keine bezahlte Cloud-Abhängigkeit im Pflichtbetrieb

## Non-Goals (bewusst ausgelassen)

- Kein Cloud-Upload oder externe Datenspeicherung
- Kein Multi-User-Support oder Nutzerverwaltung
- Kein Windows- oder Linux-Support (nur macOS)
- Keine Mobile App
- Kein automatisches Hintergrundmonitoring von Ordnern (kein Daemon/Watcher)
- Keine Papierkorb-Funktion (Löschen ist außerhalb des Scope)

---

Nutze `/requirements`, um detaillierte Feature-Specs für jeden Eintrag in der Roadmap zu erstellen.
