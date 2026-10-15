"""Quality gates for the synthetic dataset (docs/DATASET.md §8).

Every generated document goes through `check`; a document with any problem is rejected, never
fixed by hand, so errors are corrected in the generator. `deduplicate` removes exact and near
duplicates (same text once letters are lower-cased and digits masked).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from alias_pii.entities import EntityType
from alias_pii.rules import RuleDetector
from alias_pii.validators import iban_is_valid, nir_is_valid

# Types with a strict format: a generated value must have a real-world format, and the rules must
# find no value of these types outside the labels and the declared distractors.
STRICT_TYPES = {"EMAIL", "PHONE", "IBAN", "NATIONAL_ID"}
_DETECTOR = RuleDetector()
# Format of a US SSN with or without separators: the rules require separators (fewer false
# positives), but a compact SSN is still a real one, and exactly what a model must learn.
_SSN = re.compile(r"(?!000|666|9\d\d)\d{3}([- ]?)(?!00)\d{2}\1(?!0000)\d{4}")
_NINO = re.compile(
    r"(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?(\d{2} ?){3}[A-D]"
)


def check(text: str, spans: Iterable, negatives: Iterable = ()) -> list[str]:
    """Problems of one document; an empty list means it passes every gate.

    `negatives` are the distractors the generator placed on purpose (a company mailbox, a
    switchboard number): the rules may detect them, they must stay unlabelled.
    """
    problems: list[str] = []
    spans = sorted(spans, key=lambda s: (s.start, s.end))
    previous_end = 0
    for span in spans:
        value = text[span.start : span.end]
        if span.label not in EntityType.__members__:
            problems.append(f"unknown label {span.label}")
        if not value or value != value.strip():
            problems.append(f"{span.label}: empty value or surrounding whitespace")
        if span.start < previous_end:
            problems.append(f"{span.label}: overlaps the previous span")
        previous_end = max(previous_end, span.end)

    for span in spans:
        if span.label in STRICT_TYPES and not _realistic(span.label, text[span.start : span.end]):
            problems.append(f"{span.label}: not a real-world format")
    allowed = [*spans, *negatives]
    for found in _DETECTOR.detect(text):
        if found.type.value in STRICT_TYPES and not any(
            found.start < s.end and s.start < found.end for s in allowed
        ):
            problems.append(f"{found.type.value}: detected outside the labels (unlabelled value)")
    return problems


def _realistic(label: str, value: str) -> bool:
    if label == "IBAN":
        return iban_is_valid(value)
    if label == "NATIONAL_ID":
        return nir_is_valid(value) or bool(_SSN.fullmatch(value) or _NINO.fullmatch(value))
    # e-mails and phones: the rules (libphonenumber for phones) define a real format
    return any(
        e.type.value == label and e.start == 0 and e.end == len(value)
        for e in _DETECTOR.detect(value)
    )


def near_duplicate_key(text: str) -> str:
    """Same key for texts that differ only by case, digits or spacing."""
    return re.sub(r"\s+", " ", re.sub(r"\d", "0", text.lower())).strip()


def deduplicate(examples: list) -> tuple[list, int]:
    """Keep the first of each group of near duplicates. Returns the kept examples and the count
    removed."""
    seen: set[str] = set()
    kept = []
    for example in examples:
        key = near_duplicate_key(example.text)
        if key not in seen:
            seen.add(key)
            kept.append(example)
    return kept, len(examples) - len(kept)


def summarise(problems: Iterable[list[str]]) -> Counter:
    """Count rejections by kind, for the datasheet."""
    return Counter(
        problem.split(":")[0] + ":" + problem.split(":")[-1] for ps in problems for problem in ps
    )
