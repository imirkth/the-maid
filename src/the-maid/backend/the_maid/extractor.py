"""
The Maid — Text Extraction Module
Extracts readable text from files for LLM-based categorization.
Supports: .txt .md .csv .py .js .ts .rs .html .css .json .xml .yaml .yml .pdf
For PDFs: uses fitz (PyMuPDF) to extract text from first few pages.
For text-like files: reads directly, limited to max_chars.
For unsupported/binary files: returns empty string.
"""

from pathlib import Path
from typing import Set

# Extensions we can read directly as text
TEXT_EXTENSIONS: Set[str] = {
    ".txt", ".md", ".csv", ".py", ".js", ".ts", ".rs",
    ".html", ".css", ".json", ".xml", ".yaml", ".yml",
}

# PDF extension
PDF_EXTENSIONS: Set[str] = {".pdf"}

# .docx extension (optional support via python-docx)
DOCX_EXTENSIONS: Set[str] = {".docx"}


def extract_text(file_path: str, max_chars: int = 2000) -> str:
    """Extract readable text from a file for LLM categorization.

    Returns empty string for binary files or extraction failures.
    """
    path = Path(file_path)
    if not path.is_file():
        return ""

    ext = path.suffix.lower()

    try:
        if ext in TEXT_EXTENSIONS:
            return _read_text_file(path, max_chars)
        elif ext in PDF_EXTENSIONS:
            return _extract_pdf_text(path, max_chars)
        elif ext in DOCX_EXTENSIONS:
            return _extract_docx_text(path, max_chars)
        else:
            return ""
    except Exception:
        return ""


def _read_text_file(path: Path, max_chars: int) -> str:
    """Read a text-like file directly."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(max_chars)


def _extract_pdf_text(path: Path, max_chars: int) -> str:
    """Extract text from PDF using PyMuPDF (fitz)."""
    try:
        import fitz
    except ImportError:
        return ""

    doc = fitz.open(str(path))
    text_parts: list[str] = []
    total = 0

    for page in doc:
        page_text = page.get_text()
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(page_text) > remaining:
            page_text = page_text[:remaining]
        text_parts.append(page_text)
        total += len(page_text)

    doc.close()
    return "".join(text_parts)


def _extract_docx_text(path: Path, max_chars: int) -> str:
    """Extract text from .docx using python-docx if available."""
    try:
        import docx
    except ImportError:
        return ""

    document = docx.Document(str(path))
    text_parts: list[str] = []
    total = 0

    for para in document.paragraphs:
        remaining = max_chars - total
        if remaining <= 0:
            break
        text = para.text
        if len(text) > remaining:
            text = text[:remaining]
        text_parts.append(text)
        total += len(text)

    return "\n".join(text_parts)