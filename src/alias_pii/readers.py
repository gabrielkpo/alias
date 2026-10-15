"""Turn an input file into plain text for detection: .txt, .md, .docx and native PDF.

Personal data often sits where a text extractor does not look by default: Word headers,
footers, tables, text boxes, footnotes and comments, PDF form fields and annotations. Those
are read too. What still cannot be read (scanned pages, charts, embedded objects) is listed in
`Document.warnings`, never dropped in silence.
"""

from __future__ import annotations

import re
import unicodedata
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
_LIGATURES = {code: unicodedata.normalize("NFKC", chr(code)) for code in range(0xFB00, 0xFB07)}
_SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True)
_NON_ASCII_RUN = re.compile(rb"[\x80-\xff]+")
# A well-formed UTF-8 sequence (no overlong forms, no surrogates), one character.
_UTF8_SEQUENCE = re.compile(
    rb"[\xc2-\xdf][\x80-\xbf]"
    rb"|\xe0[\xa0-\xbf][\x80-\xbf]|[\xe1-\xec\xee\xef][\x80-\xbf]{2}|\xed[\x80-\x9f][\x80-\xbf]"
    rb"|\xf0[\x90-\xbf][\x80-\xbf]{2}|[\xf1-\xf3][\x80-\xbf]{3}|\xf4[\x80-\x8f][\x80-\xbf]{2}"
)


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
        document = _read_plain(path, suffix[1:])
    elif suffix == ".docx":
        document = _read_docx(path)
    else:
        document = _read_pdf(path)
    # Composed accents (NFC): "re\u0301fe\u0301rence" from macOS or a PDF must match the same
    # rules as "référence".
    # PDF ligatures (U+FB00-U+FB06) are split too, or "\ufb01le no." would hide the "file"
    # keyword; a full NFKC would also rewrite ², ½ or ™, so only these are expanded.
    text = unicodedata.normalize("NFC", document.text)
    document.text = text.translate(_LIGATURES)
    return document


# --- plain text ---------------------------------------------------------------------------


def _read_plain(path: Path, fmt: str) -> Document:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):  # UTF-8 byte order mark: same path as plain UTF-8
        raw = raw[3:]
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            text = _decode_wide(path, raw, encoding)
            return Document(path, text, fmt)
    if b"\x00" in raw:
        # Real text never contains NUL bytes: this is UTF-16 without a byte order mark (which
        # also decodes as "valid" UTF-8, giving "m\x00a\x00i\x00l").
        encoding = _utf16_byte_order(raw)
        if encoding is None:
            raise UnsupportedFileError(
                f"{path.name}: contains NUL bytes but is not recognisable UTF-16 text"
            )
        text = _decode_wide(path, raw, encoding)
        return Document(path, text, fmt, [f"no byte order mark, decoded as {encoding}"])
    text, legacy_bytes = _decode_mixed(raw)
    warnings = []
    if legacy_bytes:
        warnings.append(f"{legacy_bytes} byte(s) not UTF-8, decoded as Windows-1252")
    return Document(path, text, fmt, warnings)


def _decode_mixed(raw: bytes) -> tuple[str, int]:
    """UTF-8, with Windows-1252 where the bytes are not plausible UTF-8. Returns the text and the
    number of bytes read as Windows-1252.

    Files mix both, even within a line (a line appended by an old tool without a newline), and
    each wrong guess hides data from the rules while staying exactly recoverable: UTF-8 read as
    Windows-1252 gives "sociÃ©tÃ©"; Windows-1252 read as UTF-8 can form valid but absurd
    characters ("ABONNÉ" + no-break space gives "ABONNɠ"). So the decision is made sequence by
    sequence: a well-formed UTF-8 sequence is kept if its character is plausible in French or
    English text, and any other byte is read as Windows-1252.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        if all(_plausible(char) for char in text):
            return text, 0
    parts: list[str] = []
    legacy = 0
    position = 0
    for match in _NON_ASCII_RUN.finditer(raw):
        parts.append(raw[position : match.start()].decode("ascii"))
        run, index = match.group(), 0
        while index < len(run):
            sequence = _UTF8_SEQUENCE.match(run, index)
            if sequence:
                char = sequence.group().decode("utf-8")
                if _plausible(char):
                    parts.append(char)
                    index = sequence.end()
                    continue
                chunk = sequence.group()  # well-formed but absurd: Windows-1252 bytes
            else:
                chunk = run[index : index + 1]
            parts.append(chunk.decode("cp1252", errors="replace"))
            legacy += len(chunk)
            index += len(chunk)
        position = match.end()
    parts.append(raw[position:].decode("ascii"))
    return "".join(parts), legacy


def _plausible(char: str) -> bool:
    """Characters a French or English text may contain once correctly decoded.

    Wide on purpose (a rejected character only costs its own bytes), but excluding where
    Windows-1252 letters followed by symbols land when read as UTF-8: IPA (U+0250-U+02AF, from
    É, Ç, È... + a no-break space or a quote) and CJK (from é, è, à... + two symbols).
    """
    code = ord(char)
    return (
        code < 0x80
        or 0x00A0 <= code <= 0x024F  # Latin-1, Latin Extended-A and -B (Œ, Ł, Ș...)
        or 0x02B0 <= code <= 0x036F  # spacing modifiers (ˆ ˜), combining accents (NFD text)
        or 0x0370 <= code <= 0x04FF  # Greek (units, maths), Cyrillic (names)
        or 0x1E00 <= code <= 0x1EFF  # Latin Extended Additional
        or 0x2000 <= code <= 0x2BFF  # punctuation, currency, arrows, maths, symbols
        or 0xE000 <= code <= 0xF8FF  # private use: Word and PDF bullets
        or 0xFB00 <= code <= 0xFB06  # ligatures copied from PDFs (fi, fl)
        or code in (0xFE0F, 0xFEFF, 0xFFFD)  # emoji selector, stray byte order mark, replacement
        or 0x1F000 <= code <= 0x1FAFF  # emoji
    )


def _utf16_byte_order(raw: bytes) -> str | None:
    """Byte order of BOM-less UTF-16, from where its NUL bytes sit, or None if unclear.

    Latin-script text in UTF-16 has a NUL high byte for most characters: in the odd positions
    for little-endian, in the even ones for big-endian, and almost never in the other half.
    """
    if len(raw) % 2:
        return None
    pairs = len(raw) // 2
    nul_even = raw[0::2].count(0) / pairs
    nul_odd = raw[1::2].count(0) / pairs
    if nul_odd >= 0.3 and nul_even <= 0.02:
        return "utf-16-le"
    if nul_even >= 0.3 and nul_odd <= 0.02:
        return "utf-16-be"
    return None


def _decode_wide(path: Path, raw: bytes, encoding: str) -> str:
    """Decode UTF-16 or UTF-32, then check the result really is French or English text.

    A wrong guess is dangerous rather than just ugly: one byte of ASCII paired with the next
    gives a CJK-looking character ("Je" -> U+654A), so a misread region matches no rule, yet
    re-encoding it gives the original back exactly. This happens with mixed files, such as ANSI
    text appended to a UTF-16 file by a Windows shell. Such a file is refused, not guessed.
    """
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise UnsupportedFileError(f"{path.name}: invalid {encoding} text ({exc.reason})") from exc
    if "\x00" in text or any(_outside_scope(char) for char in text) or _misread_ascii(text):
        raise UnsupportedFileError(
            f"{path.name}: decoding as {encoding} gives characters outside French and "
            "English text (mixed encodings?); convert the file to UTF-8"
        )
    return text


def _outside_scope(char: str) -> bool:
    """Scripts a French or English document should not contain, and where misread ASCII lands.

    Two printable ASCII bytes read as one UTF-16 unit give U+0909 to U+7E7E: letters and digits
    put the result in U+3000 and above. Latin, punctuation, currency and common symbols
    (U+0000-U+058F, U+1E00-U+2BFF) stay allowed; `_misread_ascii` covers what lands there.
    """
    code = ord(char)
    return (
        0x0400 <= code <= 0x052F  # Cyrillic
        or 0x0590 <= code <= 0x1DFF
        or 0x2C00 <= code <= 0xFAFF
        or 0xFB1D <= code <= 0xFDFF  # Hebrew and Arabic presentation forms
        or 0xFE70 <= code <= 0xFEFF
    )


def _misread_ascii(text: str) -> bool:
    """Misread ASCII that lands among allowed symbols: "1 8 5 0" read as UTF-16 is "‱‸‵".

    A character whose two bytes are both printable ASCII is suspicious when one byte is a letter
    or a digit, or when it follows another such character. Real symbols there (…, •, ™)
    have punctuation bytes and come alone; a few rare ones (≤, ≥, ⅓) are refused too. Characters
    beyond U+FFFF (emoji, or bytes paired into surrogates) are refused as well.
    """
    previous = False
    for char in text:
        code = ord(char)
        if code > 0xFFFF:
            return True
        high, low = code >> 8, code & 0xFF
        both_ascii = 0x20 <= high <= 0x7E and 0x20 <= low <= 0x7E
        if both_ascii and (chr(high).isalnum() or chr(low).isalnum() or previous):
            return True
        previous = both_ascii
    return False


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
