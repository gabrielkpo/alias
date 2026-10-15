"""Entity types, detected spans and overlap resolution."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum


class EntityType(StrEnum):
    """What a span is. The value is also the alias prefix: `[PERSON_1]`.

    Labels are language-neutral so a French and an English document get the same tags, and the
    trained model keeps one label per concept. The country of a national ID lives in `Entity.kind`.
    """

    PERSON = "PERSON"
    ADDRESS = "ADDRESS"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    IBAN = "IBAN"
    NATIONAL_ID = "NATIONAL_ID"
    BIRTH_DATE = "BIRTH_DATE"
    IDENTIFIER = "IDENTIFIER"


# When two spans overlap, the higher priority wins. Checksummed formats first: a valid IBAN
# key is stronger evidence than a phone-like run of digits or a keyword-based identifier.
PRIORITY = {
    EntityType.IBAN: 70,
    EntityType.NATIONAL_ID: 60,
    EntityType.EMAIL: 50,
    EntityType.PHONE: 40,
    EntityType.BIRTH_DATE: 30,
    EntityType.PERSON: 20,
    EntityType.ADDRESS: 20,
    EntityType.IDENTIFIER: 10,
}


@dataclass(frozen=True)
class Entity:
    """A detected span: `text[start:end]` is the personal value."""

    type: EntityType
    start: int
    end: int
    text: str = field(repr=False)  # the personal value: kept out of logs and tracebacks
    score: float = 1.0
    source: str = "rules"
    kind: str | None = None  # finer label, e.g. "FR_NIR", "US_SSN", "UK_NINO"

    def overlaps(self, other: Entity) -> bool:
        return self.start < other.end and other.start < self.end


def resolve_overlaps(entities: list[Entity]) -> list[Entity]:
    """Merge overlapping spans into one, so the result is sorted and non-overlapping.

    A group of overlapping spans becomes a single span covering all of them, typed after its
    strongest member (priority, then length, then score). Dropping the weaker span instead would
    leave its non-overlapping part in clear: "AB-0612345678-ZZ" would become "AB-[PHONE_1]-ZZ".
    """
    merged: list[Entity] = []
    group: list[Entity] = []
    for entity in sorted(entities, key=lambda e: (e.start, e.end)):
        if group and entity.start >= max(e.end for e in group):
            merged.append(_merge(group))
            group = []
        group.append(entity)
    if group:
        merged.append(_merge(group))
    return merged


def _merge(group: list[Entity]) -> Entity:
    best = max(group, key=lambda e: (PRIORITY[e.type], e.end - e.start, e.score))
    start = min(e.start for e in group)
    end = max(e.end for e in group)
    if (start, end) == (best.start, best.end):
        return best
    # Overlapping spans cover [start, end) without gaps: rebuild the text from their pieces.
    chars = [""] * (end - start)
    for e in group:
        chars[e.start - start : e.end - start] = e.text
    return replace(best, start=start, end=end, text="".join(chars))
