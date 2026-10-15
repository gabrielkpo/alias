from pathlib import Path

import pytest


def _pdf_string(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return b"(" + escaped.encode("cp1252") + b")"


def build_pdf(
    pages: list[list[str]],
    fields: dict[str, str] | None = None,
    note: str | None = None,
) -> bytes:
    """A minimal PDF, one text line per entry; an empty page stands in for a scanned page.

    `fields` adds filled-in text form fields, `note` a sticky-note annotation on page 1.
    """
    fields = fields or {}
    objects: list[bytes] = []
    page_ids = []
    font_id = 3 + 2 * len(pages)
    field_ids = [font_id + 1 + i for i in range(len(fields))]
    note_id = font_id + 1 + len(fields)
    for index, lines in enumerate(pages):
        content = b"BT /F1 12 Tf 72 720 Td 14 TL "
        content += b"".join(_pdf_string(line) + b" Tj T* " for line in lines) + b"ET"
        page_id, content_id = 3 + 2 * index, 4 + 2 * index
        page_ids.append(page_id)
        annots = f" /Annots [{note_id} 0 R]" if note and index == 0 else ""
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >>{annots} >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    acroform = ""
    if fields:
        acroform = " /AcroForm << /Fields [" + " ".join(f"{i} 0 R" for i in field_ids) + "] >>"
    objects = [
        f"<< /Type /Catalog /Pages 2 0 R{acroform} >>".encode(),
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        *objects,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        *(
            b"<< /FT /Tx /T " + _pdf_string(name) + b" /V " + _pdf_string(value) + b" >>"
            for name, value in fields.items()
        ),
    ]
    if note:
        objects.append(
            b"<< /Type /Annot /Subtype /Text /Rect [0 0 20 20] /Contents "
            + _pdf_string(note)
            + b" >>"
        )
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out


@pytest.fixture
def make_pdf(tmp_path: Path):
    def make(pages: list[list[str]], name: str = "doc.pdf", **extra) -> Path:
        path = tmp_path / name
        path.write_bytes(build_pdf(pages, **extra))
        return path

    return make
