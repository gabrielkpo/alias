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

from alias_pii.entities import Entity, EntityType, resolve_overlaps
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
    entities: list[Entity] = field(repr=False)
    table: AliasTable
    aliases: list[str]  # aliases this call wrote into `text`, in order of first use
    literals: set[str]  # alias-shaped tokens that were already in the input text


@dataclass
class RestoreResult:
    text: str = field(repr=False)
    restored: list[str]  # aliases found in the answer and replaced
    missing: list[str]  # aliases sent to the LLM that the answer does not mention
    unknown: list[str]  # alias-shaped tokens left as is: invented, or from another exchange


def mask(text: str, detector: Detector, table: AliasTable | None = None) -> MaskResult:
    table = table if table is not None else AliasTable()
    table.reserve(text)
    literals = {_canonical(m) for m in ALIAS_PATTERN.finditer(text)}
    # Enforce the sorted, non-overlapping contract here: an unsorted span list would make the
    # cursor go back and write an already-masked value in clear.
    entities = resolve_overlaps(detector.detect(text))
    parts: list[str] = []
    aliases: list[str] = []
    cursor = 0
    for entity in entities:
        alias = table.alias_for(entity)
        parts.append(text[cursor : entity.start])
        parts.append(alias)
        if alias not in aliases:
            aliases.append(alias)
        cursor = entity.end
    parts.append(text[cursor:])
    return MaskResult("".join(parts), entities, table, aliases, literals)


def restore(answer: str, *sent: MaskResult) -> RestoreResult:
    """Put back the values of the aliases written by the `mask` calls whose text was sent.

    Restoring is scoped to this exchange, not to the whole session table: otherwise a document
    containing a literal "[EMAIL_1]", or an LLM guessing sequential aliases, could pull a value
    from an earlier, unrelated document into the answer. An alias that was already literal in
    one of the inputs is never restored, since it cannot be told apart from the real one.
    """
    if not sent:
        raise ValueError("restore needs the MaskResult of each text sent to the LLM")
    table = sent[0].table
    if any(result.table is not table for result in sent):
        raise ValueError("all MaskResults must share the same AliasTable")
    literals = set().union(*(result.literals for result in sent))
    allowed = [a for result in sent for a in result.aliases if a not in literals]
    restored: list[str] = []
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        alias = _canonical(match)
        value = table.value_of(alias) if alias in allowed else None
        if value is None:
            if alias not in literals and alias not in unknown:
                unknown.append(alias)
            return match.group()
        if alias not in restored:
            restored.append(alias)
        return value

    text = ALIAS_PATTERN.sub(replace, answer)
    missing = list(dict.fromkeys(a for a in allowed if a not in restored))
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
