# Alias

[![CI](https://github.com/gabrielkpo/alias/actions/workflows/ci.yml/badge.svg)](https://github.com/gabrielkpo/alias/actions/workflows/ci.yml)

Masks personal data in a document **locally**, before the text is sent to an LLM, then puts the
real values back into the answer. French and English.

> Status: work in progress (step 1 of 7: rules, masking, restoring).

## What it does
1. Detects personal data: people, addresses, e-mails, phone numbers, IBANs, national IDs
   (French NIR, US SSN, UK NINO), birth dates, file and contract numbers.
2. Replaces each value with a stable alias (`[PERSON_1]`, `[IBAN_1]`): the same value keeps the
   same alias across the document, so the LLM can follow who is who.
3. Restores the real values in the LLM answer, and reports aliases the LLM dropped or invented.

Everything runs on the user's machine. Only the masked text leaves it.

## What it is not
Alias is a component, not an anonymity guarantee and not a GDPR compliance tool. Context can
still identify a person after masking (a job title, a rare event), and no detector has perfect
recall.

## Quick start
```
uv sync --group dev
uv run pytest
```

```python
from alias_pii.masking import mask, restore
from alias_pii.rules import RuleDetector

result = mask(
    "Écrire à jean.dupont@example.com, IBAN FR76 3000 6000 0112 3456 7890 189.", RuleDetector()
)
result.text  # "Écrire à [EMAIL_1], IBAN [IBAN_1]."  <- only this goes to the LLM
answer = "Virement vers [IBAN_1] confirmé."
restore(answer, result).text  # real IBAN back, only for aliases sent in this exchange
```

## Input files (step 2)
`read_document(path)` turns a file into plain text before detection:

| Format | What is read |
|---|---|
| `.txt`, `.md` | UTF-8, UTF-16 and UTF-32 (UTF-16 also without byte order mark); UTF-8 and Windows-1252 decided sequence by sequence (a UTF-8 sequence is kept only if its character is plausible in French or English; reported); text normalised to NFC, PDF ligatures split; UTF-16 mixed with anything else is refused, never guessed |
| `.docx` | body, tables (nested too), headers and footers (first-page and even-page too), text boxes, content controls (inline, block, in cells), tracked insertions, footnotes, endnotes, comments |
| PDF with a text layer | every page (joined with a form feed), then filled-in form fields and annotation texts |

Personal data often sits outside the main text (a name in a header, an address in a text box, an
IBAN in a form field), so those places are read. What still cannot be read is reported in
`Document.warnings`: scanned pages (OCR is not supported yet), charts, SmartArt and embedded
objects. Broken, encrypted or binary files raise `UnsupportedFileError`.

Known limits of the readers:
- Invisible or special spaces inside a value (zero-width space, soft hyphen, no-break space in an
  IBAN, narrow no-break space in a phone number) stop detection; the value stays readable.
- UTF-8 or Windows-1252 is decided per character from a list of characters plausible in French or
  English: anything else (CJK, Hebrew, Arabic, full-width) comes out garbled.
- UTF-16 or UTF-32 mixed with another encoding is refused; convert the file to UTF-8.
- Some PDFs (LaTeX) store an accent before its letter ("R´ef´erence"): accented keywords then miss.
- Non-standard PDF strings (UTF-8 in PDF 2.0 annotations and form fields) are decoded as
  PDFDocEncoding by pypdf.

## Rule layer (step 1)
| Type | French | English | Check |
|---|---|---|---|
| EMAIL | yes | yes | format |
| PHONE | yes | UK, US | `phonenumbers` (libphonenumber) |
| IBAN | any country | any country | mod 97 + length per country |
| NATIONAL_ID | NIR | US SSN, UK NINO | NIR key (Corsica 2A/2B), SSN and NINO forbidden ranges |
| IDENTIFIER | after a keyword (`n° de dossier`, `réf.`) | after a keyword (`Customer ID`, `policy number`) | at least 4 characters with a digit |

PERSON, ADDRESS and BIRTH_DATE need context: they are the job of the trained model (step 4).

Known limits of the rules: a 4-digit year after a keyword (`compte 2024`) is flagged as an
identifier (recall first); an SSN needs its dashes or spaces; a NIR without its key is missed.

## License
MIT, see [LICENSE](LICENSE).
