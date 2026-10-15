"""Turn an input file into plain text for detection: .txt, .md, .docx and native PDF.

Personal data often sits where a text extractor does not look by default: Word headers,
footers, tables, text boxes, footnotes and comments, PDF form fields and annotations. Those
are read too. What still cannot be read (scanned pages, charts, embedded objects) is listed in
`Document.warnings`, never dropped in silence.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import docx
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from lxml import etree
from pypdf import PdfReader
from pypdf.errors import DependencyError, PdfReadError

SUPPORTED_SUFFIXES = (".txt", ".md", ".docx", ".pdf")
# Inputs are the user's own files, but a huge one is more likely a mistake than a document.
MAX_BYTES = 50 * 1024 * 1024

_BOMS = (  # longest first: the UTF-32 LE mark starts with the UTF-16 LE one
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)
_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
# Parts of a .docx that hold text outside the body, read with entities and network disabled.
_DOCX_NOTE_PARTS = ("footnotes.xml", "endnotes.xml", "comments.xml")
_DOCX_UNREAD_PARTS = {
    "/charts/": "charts",
    "/diagrams/": "SmartArt",
    "/embeddings/": "embedded objects",
}
_SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True)


class UnsupportedFileError(ValueError):
    """The file cannot be read: unsupported type (scans and images need OCR), broken or locked."""


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


# --- plain text ---------------------------------------------------------------------------


def _read_plain(path: Path, fmt: str) -> Document:
    raw = path.read_bytes()
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            return Document(path, raw.decode(encoding), fmt)
    if b"\x00" in raw:
        # Real text never contains NUL bytes. Any wrong guess here is dangerous: decoded as
        # UTF-8, UTF-16 gives "m\x00a\x00i\x00l"; decoded with the wrong byte order, text gives
        # CJK-looking characters. Either way the rules match nothing, yet the original can be
        # recovered exactly. So only accept UTF-16 when its NUL pattern is unambiguous.
        encoding = _utf16_without_bom(raw)
        if encoding is None:
            raise UnsupportedFileError(
                f"{path.name}: contains NUL bytes but is not recognisable UTF-16 text"
            )
        text = raw.decode(encoding)
        return Document(path, text, fmt, [f"no byte order mark, decoded as {encoding}"])
    try:
        return Document(path, raw.decode("utf-8"), fmt)
    except UnicodeDecodeError:
        pass
    # Older French files are often Windows-1252; say so rather than guessing in silence.
    text = raw.decode("cp1252", errors="replace")
    return Document(path, text, fmt, ["not valid UTF-8, decoded as Windows-1252"])


def _utf16_without_bom(raw: bytes) -> str | None:
    """Byte order of BOM-less UTF-16, from where its NUL bytes sit, or None if unclear.

    Latin-script text in UTF-16 has a NUL high byte for most characters: in the odd positions
    for little-endian, in the even ones for big-endian, and almost never in the other half.
    """
    if len(raw) % 2:
        return None
    pairs = len(raw) // 2
    nul_even = raw[0::2].count(0) / pairs
    nul_odd = raw[1::2].count(0) / pairs
    for encoding, high, low in (("utf-16-le", nul_odd, nul_even), ("utf-16-be", nul_even, nul_odd)):
        if high >= 0.3 and low <= 0.02:
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                return None
            return encoding if "\x00" not in text else None
    return None


# --- Word ---------------------------------------------------------------------------------


def _read_docx(path: Path) -> Document:
    try:
        document = docx.Document(str(path))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise UnsupportedFileError(f"{path.name}: not a readable .docx ({exc})") from exc

    lines: list[str] = []
    seen_parts: set[int] = set()
    for section in document.sections:
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            # Linked headers and footers are the same part: read each one once.
            if part.is_linked_to_previous or id(part.part) in seen_parts:
                continue
            seen_parts.add(id(part.part))
            lines += _docx_blocks(part) + _text_boxes(part._element)
    body = document.element.body
    lines += _docx_blocks(document) + _text_boxes(body)
    # Block-level content controls (form fields in templates) are skipped by iter_inner_content.
    for sdt in body.iterchildren(qn("w:sdt")):
        lines += [_paragraph_text(p) for p in sdt.iter(qn("w:p"))]

    warnings: list[str] = []
    for package_part in document.part.package.iter_parts():
        name = str(package_part.partname)
        if name.rsplit("/", 1)[-1] in _DOCX_NOTE_PARTS:
            root = etree.fromstring(package_part.blob, _SAFE_XML)
            lines += [_paragraph_text(p) for p in root.iter(qn("w:p"))]
        for marker, label in _DOCX_UNREAD_PARTS.items():
            message = f"{label} are not read"
            if marker in name and message not in warnings:
                warnings.append(message)
    return Document(path, "\n".join(line for line in lines if line.strip()), "docx", warnings)


def _docx_blocks(container) -> list[str]:
    """Paragraphs and table cells in document order, so names in tables are not lost."""
    lines: list[str] = []
    for block in container.iter_inner_content():
        if isinstance(block, docx.table.Table):
            for row in block.rows:
                cells, seen = [], set()
                for cell in row.cells:
                    # A merged cell is returned once per grid column, as the same element.
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cell_text = "\n".join(p.text for p in cell.paragraphs).strip()
                    if cell_text:
                        cells.append(cell_text)
                lines.append(" | ".join(cells))
        else:
            lines.append(block.text)
    return lines


def _text_boxes(element) -> list[str]:
    """Text boxes and shapes. Word stores each one twice (new and legacy format): read one."""
    lines: list[str] = []
    for box in element.iter(qn("w:txbxContent")):
        if any(ancestor.tag == _MC_FALLBACK for ancestor in box.iterancestors()):
            continue
        lines += [_paragraph_text(p) for p in box.iterchildren(qn("w:p"))]
    return lines


def _paragraph_text(paragraph) -> str:
    return "".join(node.text or "" for node in paragraph.iter(qn("w:t")))


# --- PDF ----------------------------------------------------------------------------------


def _read_pdf(path: Path) -> Document:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnsupportedFileError(f"{path.name}: password-protected PDF")
        pages = list(reader.pages)
    except (PdfReadError, DependencyError, NotImplementedError) as exc:
        raise UnsupportedFileError(f"{path.name}: unreadable PDF ({exc})") from exc

    texts: list[str] = []
    warnings: list[str] = []
    annotations: list[str] = []
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # one broken page must not hide the others
            text = ""
            warnings.append(f"page {number}: text could not be extracted ({type(exc).__name__})")
        else:
            if not text.strip():
                warnings.append(
                    f"page {number}: no extractable text (scanned page? OCR is not supported yet)"
                )
        texts.append(text)
        annotations += _pdf_annotations(page)

    # Filled-in forms keep most of their personal data in fields, not in the page text.
    try:
        fields = reader.get_form_text_fields() or {}
    except Exception as exc:
        fields = {}
        warnings.append(f"form fields could not be read ({type(exc).__name__})")
    extra = [f"{name}: {value}" for name, value in fields.items() if value]
    extra += annotations
    # Pages are joined with a form feed so positions can still be mapped back to a page;
    # form fields and annotations come after the last page.
    text = "\f".join(texts)
    if extra:
        text += "\f" + "\n".join(extra)
    return Document(path, text, "pdf", warnings)


def _pdf_annotations(page) -> list[str]:
    """Comments and sticky notes: their /Contents text, not their position on the page."""
    lines: list[str] = []
    for ref in page.get("/Annots") or []:
        try:
            contents = ref.get_object().get("/Contents")
        except Exception:
            continue
        if contents:
            lines.append(str(contents))
    return lines
