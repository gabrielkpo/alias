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
| `.txt`, `.md` | UTF-8 (byte order mark dropped); Windows-1252 as a reported fallback |
| `.docx` | body, tables (row by row), headers and footers, including first-page and even-page ones |
| PDF with a text layer | every page, joined with a form feed; pages without text are reported |

Scanned PDFs and images need OCR and are not supported yet. Nothing is dropped silently: what
could not be read is listed in `Document.warnings`. Headers and footers are kept on purpose,
since names and file numbers often sit there.

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
