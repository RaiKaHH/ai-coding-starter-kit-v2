"""
PROJ-9: Undo / Rollback – Business Logic.

Responsibilities:
- Read operation_log from DB (single op or full batch)
- LIFO ordering for batch undos
- Pre-flight checks before each operation:
    1. target_path still exists (file not deleted)
    2. source_path is free (no collision) – prompt UI if blocked
    3. Volume / mount point still available (os.path.exists on parent)
- Execute reverse operation via shutil.move()
- Create missing source directories with os.makedirs
- Update operation_log.status: 'reverted' | 'revert_failed'
- Partial batch failure: log failed item, continue remaining ops
"""
