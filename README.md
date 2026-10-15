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

## License
MIT, see [LICENSE](LICENSE).
