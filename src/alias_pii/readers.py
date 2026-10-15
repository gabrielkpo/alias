"""Turn an input file into plain text for detection: .txt, .md, .docx and native PDF.

Nothing is dropped silently. Personal data often sits in places a text extractor skips by
default (Word headers and tables, PDF footers), so those are kept, and anything that could not
be read is reported in `Document.warnings` instead of being lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import docx
from pypdf import PdfReader
from pypdf.errors import PdfReadError

SUPPORTED_SUFFIXES = (".txt", ".md", ".docx", ".pdf")
# Inputs are the user's own files, but a huge one is more likely a mistake than a document.
MAX_BYTES = 50 * 1024 * 1024


class UnsupportedFileError(ValueError):
    """The file type is not handled (yet): scanned PDFs and images need OCR."""


@dataclass
class Document:
    path: Path
    text: str = field(repr=False)  # personal data: kept out of logs and tracebacks
    format: str
    warnings: list[str] = field(default_factory=list)


def read_document(path: str | Path) -> Document:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileError(
            f"{path.name}: unsupported file type {suffix or '(none)'}; "
            f"supported: {', '.join(SUPPORTED_SUFFIXES)}"
        )
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise UnsupportedFileError(f"{path.name}: {size} bytes, above the {MAX_BYTES} limit")
    if suffix in (".txt", ".md"):
        return _read_plain(path, suffix[1:])
    if suffix == ".docx":
        return _read_docx(path)
    return _read_pdf(path)


def _read_plain(path: Path, fmt: str) -> Document:
    raw = path.read_bytes()
    try:
        return Document(path, raw.decode("utf-8-sig"), fmt)
    except UnicodeDecodeError:
        # Older French files are often Windows-1252; say so rather than guessing in silence.
        text = raw.decode("cp1252", errors="replace")
        return Document(path, text, fmt, ["not valid UTF-8, decoded as Windows-1252"])


def _read_docx(path: Path) -> Document:
    document = docx.Document(str(path))
    parts: list[str] = []
    seen_parts: set[int] = set()
    for section in document.sections:
        # Linked headers and footers are the same part: read each one once.
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            if part.is_linked_to_previous or id(part.part) in seen_parts:
                continue
            seen_parts.add(id(part.part))
            parts.extend(_docx_block_text(part))
    parts.extend(_docx_block_text(document))
    return Document(path, "\n".join(p for p in parts if p.strip()), "docx")


def _docx_block_text(container) -> list[str]:
    """Paragraphs and table cells in document order, so names in tables are not lost."""
    lines: list[str] = []
    for block in container.iter_inner_content():
        if isinstance(block, docx.table.Table):
            for row in block.rows:
                cells = []
                for cell in row.cells:
                    cell_text = "\n".join(p.text for p in cell.paragraphs).strip()
                    # Merged cells come back once per grid column: keep one copy.
                    if cell_text and (not cells or cells[-1] != cell_text):
                        cells.append(cell_text)
                lines.append(" | ".join(cells))
        else:
            lines.append(block.text)
    return lines


def _read_pdf(path: Path) -> Document:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnsupportedFileError(f"{path.name}: password-protected PDF")
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise UnsupportedFileError(f"{path.name}: unreadable PDF ({exc})") from exc
    warnings = [
        f"page {number}: no extractable text (scanned page? OCR is not supported yet)"
        for number, text in enumerate(pages, start=1)
        if not text.strip()
    ]
    # Pages are joined with a form feed so positions can still be mapped back to a page.
    return Document(path, "\f".join(pages), "pdf", warnings)
