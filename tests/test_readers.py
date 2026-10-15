import unicodedata

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
    assert document.warnings == ["3 byte(s) not UTF-8, decoded as Windows-1252"]


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


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_utf16_and_utf32_with_byte_order_mark(tmp_path, encoding):
    (tmp_path / "unicode.txt").write_bytes("Écrire à a.b@example.com".encode(encoding))
    document = read_document(tmp_path / "unicode.txt")
    assert (document.text, document.warnings) == ("Écrire à a.b@example.com", [])


def test_utf16_without_byte_order_mark_is_not_read_as_windows_1252(tmp_path):
    (tmp_path / "nobom.txt").write_bytes("mail a.b@example.com".encode("utf-16-le"))
    document = read_document(tmp_path / "nobom.txt")
    assert document.text == "mail a.b@example.com"
    assert document.warnings == ["no byte order mark, decoded as utf-16-le"]
    assert mask(document.text, RuleDetector()).text == "mail [EMAIL_1]"


def _append_xml(word, xml):
    from docx.oxml import parse_xml

    word.element.body.insert(len(word.element.body) - 1, parse_xml(xml))


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
MC = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'


def test_docx_text_boxes_content_controls_and_comments(tmp_path):
    word = docx.Document()
    word.add_paragraph("Bonjour,")
    # A text box is stored twice (Choice and legacy Fallback): it must be read once.
    box = "<w:txbxContent><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:txbxContent>"
    _append_xml(
        word,
        f"<w:p {W} {MC}><w:r><mc:AlternateContent>"
        f"<mc:Choice Requires='wps'>{box.format('12 rue des Lilas')}</mc:Choice>"
        f"<mc:Fallback>{box.format('12 rue des Lilas')}</mc:Fallback>"
        "</mc:AlternateContent></w:r></w:p>",
    )
    _append_xml(
        word,
        f"<w:sdt {W}><w:sdtContent><w:p><w:r><w:t>Client : a.b@example.com</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>",
    )
    signed = word.add_paragraph("Signé")
    word.add_comment(signed.runs, text="Relu par c.d@example.com", author="X")
    word.save(tmp_path / "w.docx")

    lines = read_document(tmp_path / "w.docx").text.splitlines()
    assert lines.count("12 rue des Lilas") == 1
    assert "Client : a.b@example.com" in lines
    assert "Relu par c.d@example.com" in lines


def test_docx_equal_adjacent_cells_are_kept(tmp_path):
    word = docx.Document()
    row = word.add_table(rows=1, cols=3).rows[0]
    for cell, value in zip(row.cells, ["Oui", "Oui", "Non"], strict=True):
        cell.text = value
    word.save(tmp_path / "t.docx")
    assert read_document(tmp_path / "t.docx").text == "Oui | Oui | Non"


def test_broken_docx_is_refused(tmp_path):
    (tmp_path / "old.docx").write_bytes(b"\xd0\xcf\x11\xe0 legacy .doc renamed")
    with pytest.raises(UnsupportedFileError, match="not a readable .docx"):
        read_document(tmp_path / "old.docx")


def test_pdf_form_fields_and_annotations_are_read(make_pdf):
    path = make_pdf(
        [["Nom :", "IBAN :"]],
        fields={"nom": "Hélène Martin", "iban": IBAN},
        note="Rappeler au 01 99 00 12 34",
    )
    extra = read_document(path).text.split("\f")[-1].splitlines()
    assert extra == ["nom: Hélène Martin", f"iban: {IBAN}", "Rappeler au 01 99 00 12 34"]


def test_one_broken_pdf_page_does_not_hide_the_others(make_pdf, monkeypatch):
    from pypdf import PageObject

    original = PageObject.extract_text

    def flaky(self, *args, **kwargs):
        if "page two" in original(self, *args, **kwargs):
            raise KeyError("/Font")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PageObject, "extract_text", flaky)
    document = read_document(make_pdf([["page one"], ["page two"], ["page three"]]))
    assert [p.strip() for p in document.text.split("\f")] == ["page one", "", "page three"]
    assert document.warnings == ["page 2: text could not be extracted (KeyError)"]


def test_binary_file_with_a_text_suffix_is_refused(tmp_path):
    (tmp_path / "image.txt").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01")
    with pytest.raises(UnsupportedFileError, match="NUL bytes"):
        read_document(tmp_path / "image.txt")


def test_big_endian_utf16_without_byte_order_mark(tmp_path):
    (tmp_path / "be.txt").write_bytes("Écrire à a.b@example.com".encode("utf-16-be"))
    document = read_document(tmp_path / "be.txt")
    assert document.text == "Écrire à a.b@example.com"
    assert document.warnings == ["no byte order mark, decoded as utf-16-be"]


@pytest.mark.parametrize(
    "raw",
    [
        b"Contact: a.b@example.com, tel 01 99 00 12 34\x00",  # UTF-8 with a stray NUL
        b"Contact: a.b@example.com\x00\x00",  # padding
    ],
)
def test_text_with_stray_nul_bytes_is_refused_not_mis_decoded(tmp_path, raw):
    """Decoded as UTF-16 it would become CJK-looking text: unmasked yet fully recoverable."""
    (tmp_path / "odd.txt").write_bytes(raw)
    with pytest.raises(UnsupportedFileError, match="NUL bytes"):
        read_document(tmp_path / "odd.txt")


PII_LINE = (
    "Contact: jean.dupont@example.com tel 01 99 00 12 34 IBAN FR76 3000 6000 0112 3456 7890 189\r\n"
)


@pytest.mark.parametrize("prefix", [PII_LINE, PII_LINE + "x"])  # even and odd length
def test_ansi_followed_by_utf16_without_bom_is_refused(tmp_path, prefix):
    """PowerShell `>>` appends UTF-16 to an ANSI file: no reading may hide the ANSI part."""
    raw = prefix.encode("cp1252") + ("Suite du fichier\r\n" * 6).encode("utf-16-le")
    (tmp_path / "mixed.txt").write_bytes(raw)
    with pytest.raises(UnsupportedFileError):
        read_document(tmp_path / "mixed.txt")


@pytest.mark.parametrize("tail", [PII_LINE, PII_LINE + "x"])
def test_utf16_with_bom_followed_by_ansi_is_refused(tmp_path, tail):
    raw = "Début\r\n".encode("utf-16") + tail.encode("cp1252")
    (tmp_path / "mixed.txt").write_bytes(raw)
    with pytest.raises(UnsupportedFileError):
        read_document(tmp_path / "mixed.txt")


def test_utf16_with_one_misaligned_region_is_refused(tmp_path):
    good = ("Ligne normale\r\n" * 200).encode("utf-16-le")  # region well under 2 %
    raw = good + b"!" + "a.b@example.com".encode("utf-16-le") + b"!"
    (tmp_path / "shifted.txt").write_bytes(raw)
    with pytest.raises(UnsupportedFileError, match="outside French and English"):
        read_document(tmp_path / "shifted.txt")


def test_utf16_with_punctuation_and_symbols_is_accepted(tmp_path):
    text = "« Café », 12 € – 50 % … • ✓ “ok” ’"
    (tmp_path / "symbols.txt").write_bytes(text.encode("utf-16"))
    assert read_document(tmp_path / "symbols.txt").text == text


SPACED_NIR = b"1 8 5 0 5 7 8 0 0 6 0 8 4 9 1 "
SPACED_PHONE = b"0 1 9 9 0 0 1 2 3 4 "


@pytest.mark.parametrize("tail", [SPACED_NIR, SPACED_PHONE])
@pytest.mark.parametrize(
    "head", ["﻿Dossier : ".encode("utf-16-le"), "Dossier : ".encode("utf-16-le")]
)
def test_spaced_digits_appended_to_utf16_are_refused(tmp_path, head, tail):
    """Misread, "1 8 5" becomes symbols in an allowed range: unmasked yet recoverable."""
    (tmp_path / "mixed.txt").write_bytes(head + tail)
    with pytest.raises(UnsupportedFileError):
        read_document(tmp_path / "mixed.txt")


def test_big_endian_bom_with_spaced_digits_is_refused(tmp_path):
    raw = b"\xfe\xff" + "Dossier :".encode("utf-16-be") + b" " + SPACED_NIR[:-1]
    (tmp_path / "be.txt").write_bytes(raw)
    with pytest.raises(UnsupportedFileError):
        read_document(tmp_path / "be.txt")


def test_utf8_file_with_a_windows_1252_line_keeps_its_utf8_parts(tmp_path):
    """Decoded whole as Windows-1252, "société" would become "sociÃ©tÃ©" and escape the rules."""
    raw = "Référence : AB-2024-0042\nCourriel : jean@société.example\n".encode()
    raw += "Appelé le client\n".encode("cp1252")
    (tmp_path / "mixed.txt").write_bytes(raw)
    document = read_document(tmp_path / "mixed.txt")
    assert document.text == (
        "Référence : AB-2024-0042\nCourriel : jean@société.example\nAppelé le client\n"
    )
    assert document.warnings == ["1 byte(s) not UTF-8, decoded as Windows-1252"]
    masked = mask(document.text, RuleDetector()).text
    assert masked == "Référence : [IDENTIFIER_1]\nCourriel : [EMAIL_1]\nAppelé le client\n"


def test_digits_paired_with_control_bytes_in_utf16_are_refused(tmp_path):
    """Each digit followed by 0x04 reads as Cyrillic: outside French and English, refused."""
    raw = "\ufeffNIR : ".encode("utf-16-le") + b"".join(bytes([d, 4]) for d in b"185057800608491")
    (tmp_path / "cyr.txt").write_bytes(raw)
    with pytest.raises(UnsupportedFileError):
        read_document(tmp_path / "cyr.txt")


@pytest.mark.parametrize(
    "lines",
    [
        ["N° D’ABONNÉ\u00a0: 48213377"],  # also contains invalid UTF-8 bytes
        ["ABONNÉ\u00a0: 48213377"],  # valid UTF-8 by accident: É + no-break space = U+0260
    ],
)
def test_windows_1252_that_looks_like_utf8_is_still_read_as_windows_1252(tmp_path, lines):
    (tmp_path / "abonne.txt").write_bytes("\r\n".join(lines).encode("cp1252"))
    document = read_document(tmp_path / "abonne.txt")
    assert document.text == "\r\n".join(lines)
    assert mask(document.text, RuleDetector()).text.endswith(": [IDENTIFIER_1]")


def test_french_quotes_around_a_name_in_windows_1252(tmp_path):
    (tmp_path / "q.txt").write_bytes("«\u00a0José\u00a0» a signé".encode("cp1252"))
    assert read_document(tmp_path / "q.txt").text == "«\u00a0José\u00a0» a signé"


def test_utf8_line_with_emoji_and_accents_stays_utf8(tmp_path):
    text = "✓ Écrire à jean@société.example 🙂 ≤ 3 €\n"
    (tmp_path / "e.txt").write_text(text, encoding="utf-8")
    document = read_document(tmp_path / "e.txt")
    assert (document.text, document.warnings) == (text, [])


def test_one_line_mixing_utf8_and_windows_1252_keeps_both(tmp_path):
    """PowerShell 5 Add-Content appends ANSI text to a UTF-8 file with no final newline."""
    raw = "Référence : AB-2024-0042 ; courriel jean@société.example".encode()
    raw += " – mis à jour".encode("cp1252")
    (tmp_path / "add.txt").write_bytes(raw)
    document = read_document(tmp_path / "add.txt")
    assert document.text == (
        "Référence : AB-2024-0042 ; courriel jean@société.example – mis à jour"
    )
    assert mask(document.text, RuleDetector()).text == (
        "Référence : [IDENTIFIER_1] ; courriel [EMAIL_1] – mis à jour"
    )


@pytest.mark.parametrize(
    "line",
    [
        "Référence : AB-2024-0042 (conﬁdentiel)",  # PDF ligature
        "Re\u0301fe\u0301rence : AB-2024-0042",  # decomposed accents (macOS, PDF)
        "\ufeffRéférence : AB-2024-0042",  # byte order mark in the middle of a file
        "Référence : AB-2024-0042 \ufffd M. Łukasz Wójcik, Ștefănescu",
    ],
)
def test_valid_utf8_with_unusual_but_legitimate_characters_stays_utf8(tmp_path, line):
    (tmp_path / "u.txt").write_bytes(b"Intro\n" + line.encode())
    document = read_document(tmp_path / "u.txt")
    expected = unicodedata.normalize("NFC", line).replace("\ufb01", "fi")
    assert document.text == "Intro\n" + expected
    assert document.warnings == []
    assert "[IDENTIFIER_1]" in mask(document.text, RuleDetector()).text


def test_pdf_ligatures_are_split_so_keywords_match(tmp_path):
    (tmp_path / "lig.txt").write_text("ﬁle no. 12345678, conﬁdentiel", encoding="utf-8")
    document = read_document(tmp_path / "lig.txt")
    assert document.text == "file no. 12345678, confidentiel"
    assert mask(document.text, RuleDetector()).text == "file no. [IDENTIFIER_1], confidentiel"


def test_utf8_with_bom_is_read_like_utf8(tmp_path):
    """Notepad "UTF-8 with BOM" and Excel "CSV UTF-8": symbols must not trip the UTF-16 checks."""
    text = "✓ 3 ≥ 2 • • 🙂 Иван, jean@société.example"
    (tmp_path / "bom.txt").write_bytes("﻿".encode() + text.encode())
    document = read_document(tmp_path / "bom.txt")
    assert (document.text, document.warnings) == (text, [])
