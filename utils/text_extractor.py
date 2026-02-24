"""
PROJ-3: Text extraction from files for AI analysis.

Responsibilities:
- Extract text from PDFs via pypdf (native text layer)
- Extract text from images via pytesseract (OCR)
- Extract text from plain text files (txt, md, csv, etc.)
- Cap output at MAX_CHARS (2000) to prevent LLM token overflow
- Shared utility for PROJ-3 and PROJ-8

Supported file types:
  .pdf         -> pypdf (first 2 pages)
  .txt/.md/... -> direct read (utf-8 with fallback)
  .jpg/.png/.. -> pytesseract OCR
"""
import logging
from pathlib import Path

logger = logging.getLogger("text_extractor")

# Maximum characters to return (spec: 2000)
MAX_CHARS = 2000

# File extensions handled by each strategy
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".rst", ".tex",
}

_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp",
}

_PDF_EXTENSIONS = {".pdf"}


async def extract_text(file_path: Path) -> tuple[str, bool]:
    """
    Extract text content from a file.

    Args:
        file_path: Absolute path to the file.

    Returns:
        Tuple of (extracted_text, success).
        On failure, returns ("", False) so the caller can fall back to fast mode.
    """
    if not file_path.exists():
        logger.warning("Datei existiert nicht: %s", file_path)
        return "", False

    suffix = file_path.suffix.lower()

    try:
        if suffix in _PDF_EXTENSIONS:
            return await _extract_pdf(file_path)
        elif suffix in _TEXT_EXTENSIONS:
            return await _extract_plain_text(file_path)
        elif suffix in _IMAGE_EXTENSIONS:
            return await _extract_image_ocr(file_path)
        else:
            logger.info(
                "Kein Textextraktor fuer Dateityp %s: %s",
                suffix, file_path.name,
            )
            return "", False
    except Exception as exc:
        logger.warning(
            "Textextraktion fehlgeschlagen fuer %s: %s",
            file_path.name, type(exc).__name__,
        )
        return "", False


async def _extract_pdf(file_path: Path) -> tuple[str, bool]:
    """Extract text from first 2 pages of a PDF using pypdf."""
    import asyncio
    from functools import partial

    def _do_extract() -> str:
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        pages_to_read = min(len(reader.pages), 2)
        text_parts: list[str] = []
        total_len = 0

        for i in range(pages_to_read):
            page_text = reader.pages[i].extract_text() or ""
            remaining = MAX_CHARS - total_len
            if remaining <= 0:
                break
            text_parts.append(page_text[:remaining])
            total_len += len(text_parts[-1])

        return "\n".join(text_parts)

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _do_extract)
    text = text.strip()[:MAX_CHARS]

    if not text:
        logger.info("PDF hat keinen extrahierbaren Text (evtl. gescannt): %s", file_path.name)
        # Try OCR as fallback for scanned PDFs
        return await _extract_scanned_pdf_ocr(file_path)

    return text, True


async def _extract_scanned_pdf_ocr(file_path: Path) -> tuple[str, bool]:
    """Fallback: convert first page of a scanned PDF to image and OCR it."""
    import asyncio

    def _do_ocr() -> str:
        try:
            from pypdf import PdfReader
            from PIL import Image
            import pytesseract
            import io

            reader = PdfReader(str(file_path))
            if not reader.pages:
                return ""

            # Try to extract images from first page
            page = reader.pages[0]
            images = page.images if hasattr(page, "images") else []

            text_parts: list[str] = []
            for img_obj in images[:3]:  # max 3 images from first page
                img_bytes = img_obj.data
                img = Image.open(io.BytesIO(img_bytes))
                ocr_text = pytesseract.image_to_string(img, lang="deu+eng")
                text_parts.append(ocr_text)
                if sum(len(t) for t in text_parts) >= MAX_CHARS:
                    break

            return "\n".join(text_parts)
        except ImportError:
            logger.warning("pytesseract nicht installiert -- OCR-Fallback nicht verfuegbar.")
            return ""
        except Exception as exc:
            logger.warning("PDF-OCR fehlgeschlagen: %s", exc)
            return ""

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _do_ocr)
    text = text.strip()[:MAX_CHARS]

    if not text:
        return "", False
    return text, True


async def _extract_plain_text(file_path: Path) -> tuple[str, bool]:
    """Read plain text files with encoding fallback."""
    import asyncio

    def _do_read() -> str:
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                return file_path.read_text(encoding=encoding)[:MAX_CHARS]
            except UnicodeDecodeError:
                continue
        return ""

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _do_read)
    text = text.strip()[:MAX_CHARS]

    if not text:
        return "", False
    return text, True


async def _extract_image_ocr(file_path: Path) -> tuple[str, bool]:
    """Extract text from images via pytesseract OCR."""
    import asyncio

    def _do_ocr() -> str:
        try:
            from PIL import Image
            import pytesseract

            img = Image.open(str(file_path))
            return pytesseract.image_to_string(img, lang="deu+eng")
        except ImportError:
            logger.warning("pytesseract nicht installiert -- OCR nicht verfuegbar.")
            return ""
        except Exception as exc:
            logger.warning("Bild-OCR fehlgeschlagen fuer %s: %s", file_path.name, exc)
            return ""

    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _do_ocr)
    text = text.strip()[:MAX_CHARS]

    if not text:
        return "", False
    return text, True
