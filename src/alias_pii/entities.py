"""Entity types, detected spans and overlap resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    """Keep a set of non-overlapping spans, sorted by position.

    Greedy: highest priority first, then longest span, then highest score, then leftmost.
    """
    ranked = sorted(
        entities,
        key=lambda e: (-PRIORITY[e.type], -(e.end - e.start), -e.score, e.start),
    )
    kept: list[Entity] = []
    for entity in ranked:
        if not any(entity.overlaps(k) for k in kept):
            kept.append(entity)
    return sorted(kept, key=lambda e: e.start)
