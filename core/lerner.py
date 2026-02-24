"""
PROJ-4: Semantischer Struktur-Lerner – Business Logic.

Responsibilities:
- Recursively scan a reference folder (reuses analyzer logic)
- Aggregate per-subfolder statistics (collections.Counter for extensions + n-grams)
- Sample max 50 filenames per folder before sending to AI
- Call ai_service.py for folder profiling (AIFolderProfile response)
- Offline fallback: store only extension stats without AI description
- Persist results to folder_profiles table
- Generate structure_rules.yaml from folder_profiles (PyYAML)
- Concurrency: asyncio.Queue with max 2–3 concurrent AI calls
"""
