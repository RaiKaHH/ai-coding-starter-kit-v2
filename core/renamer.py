"""
PROJ-3: KI-gestützter Datei-Umbenenner – Business Logic.

Responsibilities:
- Fast mode: extract date from EXIF / OS metadata, keep base name
- Smart mode:
    - Extract text via pypdf / pytesseract (max 3000 chars / 3 pages)
    - Call ai_service.py for date + filename extraction
    - Validate AI JSON response (Pydantic AIRenameResult)
    - Fallback chain: AI date → EXIF date → OS ctime
- Build target filename: YYYY-MM-DD_snake_case_name.ext
- Sanitise AI-suggested names (only a-z, 0-9, -, _)
- Execute renames via shutil.move()
- Write every rename to operation_log with batch_id
- Concurrency: asyncio.Semaphore(3) for AI calls
"""
