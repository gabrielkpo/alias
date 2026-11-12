# Input files

`read_document(path)` turns a file into plain text before detection:

| Format | What is read |
|---|---|
| `.txt`, `.md` | UTF-8, UTF-16, UTF-32; UTF-8 and Windows-1252 decided per character (reported); ambiguous mixes refused; NFC |
| `.docx` | body, tables (nested too), headers and footers (first-page and even-page too), text boxes, content controls (inline, block, in cells), tracked insertions, footnotes, endnotes, comments |
| PDF with a text layer | every page (joined with a form feed), then filled-in form fields and annotation texts |

What still cannot be read is reported in `Document.warnings`: scanned pages (OCR is not
supported yet), charts, SmartArt and embedded objects. Broken, encrypted or binary files raise
`UnsupportedFileError`.

Known limits of the readers:
- Typographic spaces (no-break, narrow, thin) count as spaces and invisible characters
  (zero-width space or joiner, soft hyphen) are skipped by the rules; the model reads the text
  as written, so a name or address split by an invisible character may still be missed.
- UTF-8 or Windows-1252 is decided per character from a list of characters plausible in French or
  English: anything else (CJK, Hebrew, Arabic, full-width) comes out garbled.
- UTF-16 or UTF-32 mixed with another encoding is refused; convert the file to UTF-8.
- Some PDFs (LaTeX) store an accent before its letter ("R´ef´erence"): accented keywords then miss.
- Non-standard PDF strings (UTF-8 in PDF 2.0 annotations and form fields) are decoded as
  PDFDocEncoding by pypdf.
