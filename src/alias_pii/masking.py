"""Masking with stable aliases, and restoring the real values in the LLM answer.

The alias table maps `[PERSON_1]` back to "Jean Dupont". It stays on the user's machine: only
the masked text is meant to be sent to an LLM.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

import phonenumbers

from alias_pii.entities import Entity, EntityType
from alias_pii.validators import compact

_TYPES = "|".join(t.value for t in EntityType)
# Tolerates spaces inside the brackets, which some LLMs add when they rewrite text.
ALIAS_PATTERN = re.compile(rf"\[\s*({_TYPES})_(\d+)\s*\]")

_STRICT_FORMATS = {EntityType.EMAIL, EntityType.IBAN, EntityType.NATIONAL_ID, EntityType.IDENTIFIER}


class Detector(Protocol):
    def detect(self, text: str) -> list[Entity]: ...


def normalize(entity: Entity) -> str:
    """Key under which two surface forms count as the same value.

    "06 12 34 56 78" and "+33 6 12 34 56 78" are one phone; "Jean DUPONT" and "jean dupont" are
    one person. Variants such as "M. Dupont" are not merged yet.
    """
    if entity.type is EntityType.PHONE:
        try:
            number = phonenumbers.parse(entity.text, entity.kind or "FR")
            return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            return compact(entity.text)
    if entity.type in _STRICT_FORMATS:
        return compact(entity.text)
    decomposed = unicodedata.normalize("NFKD", entity.text.casefold())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_accents.split())


@dataclass
class AliasTable:
    """Value <-> alias mapping for one session. Reuse it across documents to keep aliases stable."""

    _by_key: dict[tuple[EntityType, str], str] = field(default_factory=dict)
    _values: dict[str, str] = field(default_factory=dict)
    _counters: dict[EntityType, int] = field(default_factory=dict)
    _reserved: set[str] = field(default_factory=set)

    def reserve(self, text: str) -> None:
        """Never hand out an alias that already appears literally in the input text."""
        self._reserved.update(_canonical(m) for m in ALIAS_PATTERN.finditer(text))

    def alias_for(self, entity: Entity) -> str:
        key = (entity.type, normalize(entity))
        if key not in self._by_key:
            alias = self._next_alias(entity.type)
            self._by_key[key] = alias
            self._values[alias] = entity.text
        return self._by_key[key]

    def value_of(self, alias: str) -> str | None:
        return self._values.get(alias)

    @property
    def aliases(self) -> list[str]:
        return list(self._values)

    def is_reserved(self, alias: str) -> bool:
        return alias in self._reserved

    def _next_alias(self, type_: EntityType) -> str:
        while True:
            self._counters[type_] = self._counters.get(type_, 0) + 1
            alias = f"[{type_.value}_{self._counters[type_]}]"
            if alias not in self._reserved:
                return alias

    def __repr__(self) -> str:  # never print personal values in logs or tracebacks
        return f"AliasTable({len(self._values)} aliases)"


@dataclass
class MaskResult:
    text: str
    entities: list[Entity]
    table: AliasTable


@dataclass
class RestoreResult:
    text: str
    restored: list[str]  # aliases found in the answer and replaced
    missing: list[str]  # aliases of the table the answer does not mention (dropped or reworded)
    unknown: list[str]  # alias-shaped tokens the table does not know (invented by the LLM)


def mask(text: str, detector: Detector, table: AliasTable | None = None) -> MaskResult:
    table = table if table is not None else AliasTable()
    table.reserve(text)
    entities = detector.detect(text)
    parts: list[str] = []
    cursor = 0
    for entity in entities:  # sorted and non-overlapping
        parts.append(text[cursor : entity.start])
        parts.append(table.alias_for(entity))
        cursor = entity.end
    parts.append(text[cursor:])
    return MaskResult("".join(parts), entities, table)


def restore(answer: str, table: AliasTable) -> RestoreResult:
    restored: list[str] = []
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        alias = _canonical(match)
        value = table.value_of(alias)
        if value is None:
            if not table.is_reserved(alias) and alias not in unknown:
                unknown.append(alias)
            return match.group()
        if alias not in restored:
            restored.append(alias)
        return value

    text = ALIAS_PATTERN.sub(replace, answer)
    missing = [a for a in table.aliases if a not in restored]
    return RestoreResult(text, restored, missing, unknown)


def find_leaks(masked_text: str, entities: list[Entity]) -> list[Entity]:
    """Entities whose value is still readable in the masked text (exact or without separators)."""
    compact_text = compact(masked_text)
    return [
        e
        for e in entities
        if e.text in masked_text
        or (
            (e.type in _STRICT_FORMATS or e.type is EntityType.PHONE)
            and compact(e.text) in compact_text
        )
    ]


def _canonical(match: re.Match[str]) -> str:
    return f"[{match.group(1)}_{int(match.group(2))}]"
