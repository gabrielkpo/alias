"""Public annotated corpora converted to the Alias schema (dataset v0.4, docs/DATASET.md §11).

- gretelai/synthetic_pii_finance_multilingual (Apache-2.0): synthetic financial documents in
  many formats (EDI, BAI, SWIFT, contracts, letters), French and English files.
- WikiNER French (Nothman et al. 2013, CC BY 4.0), mirror Jean-Baptiste/wikiner_fr: Wikipedia
  sentences with PER/LOC/ORG/MISC tags. Only `PER` maps to an Alias label; places and
  organisations stay unlabelled, as in the Alias schema.

The files are downloaded to `data/raw/` (ignored by Git, see the README) and read locally.
Every converted document goes through the same quality gates as the generated ones; the
reason for each rejection is counted, so the datasheet shows how much of a corpus is kept.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from alias_pii import quality
from alias_pii.documents import Document, Span

# gretel label -> Alias label; labels absent from this table stay unlabelled (companies, dates,
# times, card numbers, SWIFT codes, IP addresses...): they are not part of the Alias schema.
GRETEL_LABELS = {
    "name": "PERSON",
    "first_name": "PERSON",
    "last_name": "PERSON",
    "street_address": "ADDRESS",
    "email": "EMAIL",
    "phone_number": "PHONE",
    "iban": "IBAN",
    "ssn": "NATIONAL_ID",
    "date_of_birth": "BIRTH_DATE",
    "customer_id": "IDENTIFIER",
    "employee_id": "IDENTIFIER",
    "passport_number": "IDENTIFIER",
    "driver_license_number": "IDENTIFIER",
}
GRETEL_FILES = {"fr": "France", "en": "English"}
WIKINER_PER = 2
_NO_SPACE_BEFORE = {".", ",", ")", "]", "}", "%", "...", "»"}
_NO_SPACE_AFTER = {"(", "[", "{", "«"}


def _split_of(part: str, key: str) -> str:
    """The corpus's own test part stays test; a stable 10 % of its training part (by hash of
    the row id) becomes validation, since neither corpus has a validation part."""
    if part == "test":
        return "test"
    return "validation" if hashlib.sha256(key.encode()).digest()[0] < 26 else "train"


def _read(path: Path) -> list[dict]:
    import pyarrow.parquet as pq  # only needed when converting

    return pq.read_table(path).to_pylist()


def gretel(raw: Path, language: str, part: str, min_quality: int = 80) -> Iterator[Document]:
    """Documents of one gretel file (`part` is `train` or `test`). Spans are mapped, trimmed
    of surrounding whitespace and dropped when outside the Alias schema."""
    for row in _read(raw / "gretel" / f"{GRETEL_FILES[language]}_{part}.parquet"):
        if row["quality_score"] < min_quality:
            continue
        text = row["generated_text"]
        spans = []
        for span in json.loads(row["pii_spans"]):
            label = GRETEL_LABELS.get(span["label"])
            if label is None:
                continue
            start, end = span["start"], span["end"]
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            spans.append(Span(start, end, label))
        key = str(row["__index_level_0__"])
        yield Document(
            text=text,
            spans=_merge(spans),
            language=language,
            locale="fr_FR" if language == "fr" else "en_US",
            doc_type=row["expanded_type"],
            domain=row["domain"],
            layout=row["document_type"],
            split=_split_of(part, key),
            source="gretel-pii-finance-multilingual",
        )


def _merge(spans: list[Span]) -> list[Span]:
    """Sorted spans; overlapping spans of the same label (a `name` and the `first_name` inside
    it) become one. Overlaps between different labels are left for the gates to reject."""
    merged: list[Span] = []
    for span in sorted(set(spans), key=lambda s: (s.start, s.end)):
        last = merged[-1] if merged else None
        if last and last.label == span.label and span.start < last.end:
            merged[-1] = Span(last.start, max(last.end, span.end), last.label)
        else:
            merged.append(span)
    return merged


def _detokenise(tokens: list[str], tags: list[int]) -> tuple[str, list[Span]]:
    """French text from WikiNER tokens, with `PER` token runs as PERSON spans."""
    text, spans, start = "", [], None
    previous = None
    for token, tag in zip(tokens, tags, strict=True):
        if (
            text
            and token not in _NO_SPACE_BEFORE
            and previous not in _NO_SPACE_AFTER
            and not (previous and previous.endswith("'"))
        ):
            text += " "
        if tag == WIKINER_PER and start is None:
            start = len(text)
        if tag != WIKINER_PER and start is not None:
            spans.append(Span(start, len(text.rstrip()), "PERSON"))
            start = None
        text += token
        previous = token
    if start is not None:
        spans.append(Span(start, len(text), "PERSON"))
    return text, spans


def wikiner(raw: Path, part: str, sentences: int = 4) -> Iterator[Document]:
    """Paragraphs of `sentences` consecutive WikiNER sentences (rows are in article order)."""
    rows = _read(raw / "wikiner_fr" / f"{part}.parquet")
    rows.sort(key=lambda r: r["id"])
    for i in range(0, len(rows) - sentences + 1, sentences):
        text, spans = "", []
        for row in rows[i : i + sentences]:
            sentence, found = _detokenise(row["tokens"], row["ner_tags"])
            offset = len(text) + (1 if text else 0)
            text = f"{text} {sentence}" if text else sentence
            spans += [Span(s.start + offset, s.end + offset, s.label) for s in found]
        key = str(rows[i]["id"])
        yield Document(
            text=text,
            spans=spans,
            language="fr",
            locale="fr_FR",
            doc_type="encyclopedia",
            domain="encyclopedia",
            layout="prose",
            split=_split_of(part, key),
            source="wikiner-fr",
        )


def convert(documents: Iterator[Document]) -> tuple[list[Document], Counter]:
    """Documents that pass the quality gates and the rejections by reason."""
    kept, rejected = [], Counter()
    for document in documents:
        problems = quality.check(document.text, document.spans)
        if problems:
            rejected.update(quality.summarise([problems]))
        else:
            kept.append(document)
    return kept, rejected
