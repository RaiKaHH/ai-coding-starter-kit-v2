"""
PROJ-2: Struktur-basierter Datei-Verschieber – Business Logic.

Responsibilities:
- Parse structure_rules.yaml (PyYAML)
- Map scan_files against rules (fnmatch / re)
- Dry-run: return MovePreviewItem list (no I/O)
- Execute: shutil.move() for confirmed items (BackgroundTask)
- Write every move to operation_log with batch_id
- Handle name collisions (_1, _2 suffixes)
"""
