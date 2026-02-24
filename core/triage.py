"""
PROJ-5: Smart Inbox Triage – Business Logic.

Responsibilities:
- Stage 1 (strict match): compare filename against structure_rules.yaml rules
- Stage 2 (fuzzy match): compare filename tokens against folder_profiles.keywords
  using difflib.SequenceMatcher or TF-IDF (collections.Counter)
- Return confidence score (0-100) per file
- Handle ties: surface top-2 candidates without auto-selecting
- Delegate actual move execution to core/mover.py (no own shutil calls)
- Feedback loop: when user corrects folder, update folder_profiles.keywords
"""
