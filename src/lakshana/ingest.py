"""Lightweight text ingestion: PDF (pdfplumber), images (pytesseract), plain text.

Single entrypoint: ``extract_text_from_file(path) -> str``.
For scanned PDFs, falls back to OCR-per-page using pdf2image + pytesseract if
the page yields no embedded text.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_TEXT = {".txt", ".md", ".csv", ".tsv", ".log", ".json", ".xml", ".html"}
SUPPORTED_PDF = {".pdf"}
SUPPORTED_IMAGE = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
SUPPORTED = SUPPORTED_TEXT | SUPPORTED_PDF | SUPPORTED_IMAGE

# Refuse files larger than this — they almost always indicate a misconfiguration
# (e.g. accidentally pointing at a video file) and can OOM the embedding step.
# Caller can opt in to larger files by passing ``max_bytes`` explicitly.
DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB hard ceiling
WARN_BYTES = 10 * 1024 * 1024           # 10 MB — log a warning, still process


def extract_text_from_file(file_path: str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    """Extract plain text from a supported file.

    Supported extensions: .txt .md .csv .tsv .log .json .xml .html
                          .pdf .png .jpg .jpeg .tiff .tif .bmp .webp

    Raises:
        ValueError: unsupported extension, or file exceeds ``max_bytes``.
        FileNotFoundError: file doesn't exist on disk.
        IsADirectoryError: ``file_path`` points at a directory.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"No such file: {file_path}")
    if path.is_dir():
        raise IsADirectoryError(
            f"{file_path} is a directory. "
            f"Use lakshana.ingest.get_supported_files(dir) to enumerate files first."
        )

    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"File '{path.name}' is {size / 1_048_576:.1f} MiB which exceeds the "
            f"{max_bytes / 1_048_576:.0f} MiB ceiling. Pass max_bytes=<larger> if "
            f"you know this file is legitimate; otherwise check for a misrouted "
            f"video / archive / dataset dump."
        )
    if size > WARN_BYTES:
        logger.warning(
            "Processing large file %s (%.1f MiB) — may be slow or memory-heavy",
            path.name, size / 1_048_576,
        )

    ext = path.suffix.lower()

    if ext in SUPPORTED_TEXT:
        return _read_text(path)
    if ext in SUPPORTED_PDF:
        return _read_pdf(path)
    if ext in SUPPORTED_IMAGE:
        return _read_image(path)
    raise ValueError(
        f"Unsupported file type: '{ext}'. "
        f"Supported: {sorted(SUPPORTED_TEXT | SUPPORTED_PDF | SUPPORTED_IMAGE)}"
    )


def _read_text(path: Path) -> str:
    """Read a text-like file, transparently handling UTF-8 BOM and bad bytes."""
    # utf-8-sig strips a leading BOM if present, then falls back to plain UTF-8.
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except UnicodeDecodeError:
        # Last-resort fallback — decode latin-1 (single-byte safe) and replace.
        return path.read_text(encoding="latin-1", errors="replace")


def get_supported_files(directory: str) -> list[str]:
    """List supported files in a directory (non-recursive, sorted)."""
    out = []
    for entry in sorted(Path(directory).iterdir()):
        if entry.is_file() and entry.suffix.lower() in SUPPORTED:
            out.append(str(entry))
    return out


def _read_pdf(path: Path) -> str:
    import pdfplumber

    pages: list[str] = []
    needs_ocr = False
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
            else:
                needs_ocr = True
                pages.append("")  # placeholder, may be filled by OCR

    if needs_ocr:
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(path), dpi=150)
            for i, img in enumerate(images):
                if i < len(pages) and pages[i].strip():
                    continue
                ocr_text = _ocr_image(img)
                if i < len(pages):
                    pages[i] = ocr_text
                else:
                    pages.append(ocr_text)
        except Exception as e:
            logger.warning("PDF OCR fallback failed for %s: %s", path.name, e)

    return "\n\n".join(p for p in pages if p.strip())


def _read_image(path: Path) -> str:
    from PIL import Image

    return _ocr_image(Image.open(path))


def _ocr_image(img) -> str:
    """OCR a PIL Image with pytesseract. Returns empty string on failure."""
    try:
        import pytesseract
        return pytesseract.image_to_string(img).strip()
    except Exception as e:
        logger.warning("OCR failed: %s", e)
        return ""
