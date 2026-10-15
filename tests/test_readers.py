import docx
import pytest
from pypdf import PdfReader, PdfWriter

from alias_pii import readers
from alias_pii.masking import find_leaks, mask
from alias_pii.readers import UnsupportedFileError, read_document
from alias_pii.rules import RuleDetector

IBAN = "FR76 3000 6000 0112 3456 7890 189"


def test_plain_text_and_markdown(tmp_path):
    (tmp_path / "a.txt").write_text("Écrire à a.b@example.com", encoding="utf-8")
    (tmp_path / "b.md").write_bytes("﻿# Note\nTél. 01 99 00 12 34".encode())
    txt, md = read_document(tmp_path / "a.txt"), read_document(tmp_path / "b.md")
    assert (txt.format, txt.text, txt.warnings) == ("txt", "Écrire à a.b@example.com", [])
    assert md.text == "# Note\nTél. 01 99 00 12 34"  # byte order mark dropped


def test_legacy_encoding_is_decoded_and_reported(tmp_path):
    (tmp_path / "old.txt").write_bytes("Hélène écrit".encode("cp1252"))
    document = read_document(tmp_path / "old.txt")
    assert document.text == "Hélène écrit"
    assert document.warnings == ["not valid UTF-8, decoded as Windows-1252"]


def test_docx_keeps_headers_footers_and_tables(tmp_path):
    word = docx.Document()
    word.sections[0].header.paragraphs[0].text = "Dossier n° 2024/00421"
    word.sections[0].footer.paragraphs[0].text = "contact@example.com"
    word.add_paragraph("Bonjour,")
    table = word.add_table(rows=1, cols=3)
    table.cell(0, 0).text = "IBAN"
    table.cell(0, 1).merge(table.cell(0, 2)).text = IBAN
    word.add_paragraph("Cordialement")
    word.add_section()  # its header is linked to the first one: must not be read twice
    word.save(tmp_path / "letter.docx")

    document = read_document(tmp_path / "letter.docx")
    assert document.text.splitlines() == [
        "Dossier n° 2024/00421",
        "contact@example.com",
        "Bonjour,",
        f"IBAN | {IBAN}",
        "Cordialement",
    ]


def test_pdf_pages_are_kept_apart_and_empty_pages_reported(make_pdf):
    path = make_pdf([["Madame (cliente)", f"IBAN {IBAN}"], [], ["contact@example.com"]])
    document = read_document(path)
    pages = document.text.split("\f")
    assert len(pages) == 3
    assert pages[0].splitlines() == ["Madame (cliente)", f"IBAN {IBAN}"]
    assert pages[2].strip() == "contact@example.com"
    assert document.warnings == [
        "page 2: no extractable text (scanned page? OCR is not supported yet)"
    ]


def test_password_protected_pdf_is_refused(make_pdf, tmp_path):
    writer = PdfWriter(clone_from=PdfReader(make_pdf([["secret"]])))
    writer.encrypt("pass", algorithm="RC4-128")
    writer.write(tmp_path / "locked.pdf")
    with pytest.raises(UnsupportedFileError, match="password"):
        read_document(tmp_path / "locked.pdf")


def test_broken_pdf_is_refused(tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf at all")
    with pytest.raises(UnsupportedFileError, match="unreadable"):
        read_document(tmp_path / "broken.pdf")


@pytest.mark.parametrize("name", ["scan.png", "notes.odt", "README"])
def test_unsupported_types_are_refused(tmp_path, name):
    (tmp_path / name).write_bytes(b"x")
    with pytest.raises(UnsupportedFileError, match="unsupported"):
        read_document(tmp_path / name)


def test_oversized_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(readers, "MAX_BYTES", 10)
    (tmp_path / "big.txt").write_text("x" * 11)
    with pytest.raises(UnsupportedFileError, match="limit"):
        read_document(tmp_path / "big.txt")


def test_repr_does_not_show_the_text(tmp_path):
    (tmp_path / "a.txt").write_text("a.b@example.com")
    assert "a.b@example.com" not in repr(read_document(tmp_path / "a.txt"))


def test_read_then_mask_leaves_nothing_in_clear(tmp_path):
    word = docx.Document()
    word.sections[0].footer.paragraphs[0].text = "a.b@example.com"
    word.add_table(rows=1, cols=1).cell(0, 0).text = IBAN
    word.save(tmp_path / "w.docx")
    result = mask(read_document(tmp_path / "w.docx").text, RuleDetector())
    assert result.text == "[EMAIL_1]\n[IBAN_1]"
    assert find_leaks(result.text, result.entities) == []
