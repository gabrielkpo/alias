"""Rule layer: regular expressions plus checksums for strict formats, French and English.

Covers EMAIL, PHONE, IBAN, NATIONAL_ID (FR NIR, US SSN, UK NINO) and IDENTIFIER (a file or
contract number announced by a keyword). PERSON, ADDRESS and BIRTH_DATE are left to the model.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import phonenumbers

from alias_pii.entities import Entity, EntityType, resolve_overlaps
from alias_pii.validators import IBAN_LENGTHS, iban_is_valid, nir_is_valid

PHONE_REGIONS = ("FR", "GB", "US")

# Unicode domains too (jean@société.fr): \w is Unicode-aware; the TLD is letters only.
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}\b")

# 15 characters with optional single separators (space, dot or dash): sex, year, month,
# department (or 2A/2B), commune, order number, key. The checksum decides; the pattern only
# finds candidates.
_SEP = r"[ .-]?"
_NIR = re.compile(
    rf"(?<![\w])[1-478](?:{_SEP}\d){{4}}{_SEP}(?:\d{_SEP}\d|2{_SEP}[ABab])(?:{_SEP}\d){{6}}"
    rf"{_SEP}\d{_SEP}\d(?![\w])"
)

# Separators required: nine bare digits are too often something else.
_US_SSN = re.compile(r"(?<![\d-])(?!000|666|9\d\d)\d{3}([- ])(?!00)\d{2}\1(?!0000)\d{4}(?![\d-])")

# HMRC rules: no D, F, I, Q, U, V in either prefix letter, no O second, and some pairs unused.
_UK_NINO = re.compile(
    r"(?<![A-Za-z0-9])(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]"
    r" ?\d{2} ?\d{2} ?\d{2} ?[A-D](?![A-Za-z0-9])",
    re.IGNORECASE,
)

_IBAN_START = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}")

# Words need a boundary, or "num" would match the start of "number" and leave "ber" as the value.
_NUMBER_WORD = r"(?:n[°º]\.?|#|(?:number|num[ée]ro|num\.|no\.|nr\.|num|no|nr|id)(?!\w))"
_ID_KEYWORD = (
    r"(?:dossier|contrat|client|r[ée]f[ée]rence|r[ée]f\.?|facture|police|patient|adh[ée]rent"
    r"|matricule|sinistre|commande|compte|abonn[ée]|badge|passeport|permis"
    r"|case|file|contract|customer|reference|invoice|policy|member(?:ship)?|employee|account"
    r"|claim|order|ticket|passport|licen[cs]e|id)"
)
# A short verb or article may sit between the keyword and the value: "account number is ...".
_FILLER = r"(?:(?:is|was|est|était|=)\s+)?(?:(?:le|la|the)\s+)?"
# "n° de dossier : 2024/0042", "Customer ID: AB-123456", "le numéro de dossier est le 2024/1234"
_IDENTIFIER = re.compile(
    rf"(?:\b{_NUMBER_WORD}\s*(?:de\s+|du\s+|d['’]\s*|of\s+)?)?\b{_ID_KEYWORD}(?!\w)"
    rf"(?:\s+{_NUMBER_WORD})?\s*(?:[:#]\s*)?{_FILLER}"
    r"(?P<value>[A-Z0-9](?:[A-Z0-9/_.\-]*[A-Z0-9])?)",
    re.IGNORECASE,
)


class RuleDetector:
    """Deterministic detector. `detect` returns non-overlapping spans sorted by position."""

    name = "rules"

    def detect(self, text: str) -> list[Entity]:
        found = [
            *self._emails(text),
            *self._phones(text),
            *self._ibans(text),
            *self._national_ids(text),
            *self._identifiers(text),
        ]
        return resolve_overlaps(found)

    def _entity(self, type_: EntityType, text: str, start: int, end: int, kind=None) -> Entity:
        return Entity(type_, start, end, text[start:end], source=self.name, kind=kind)

    def _emails(self, text: str) -> Iterator[Entity]:
        for m in _EMAIL.finditer(text):
            yield self._entity(EntityType.EMAIL, text, m.start(), m.end())

    def _phones(self, text: str) -> Iterator[Entity]:
        # National formats depend on the region (06 12 34 56 78 vs (415) 555-0132), so the text
        # is scanned once per region; international formats are found by every pass.
        for region in PHONE_REGIONS:
            for match in phonenumbers.PhoneNumberMatcher(text, region):
                kind = phonenumbers.region_code_for_number(match.number)
                yield self._entity(EntityType.PHONE, text, match.start, match.end, kind)

    def _ibans(self, text: str) -> Iterator[Entity]:
        for m in _IBAN_START.finditer(text):
            # Walk alphanumerics, allowing one space or dash between groups, and remember where
            # each character ends so a valid IBAN can be cut at its exact length.
            ends: list[int] = []
            i = m.start()
            while i < len(text) and len(ends) < 34:
                char = text[i]
                if char.isascii() and char.isalnum():
                    i += 1
                    ends.append(i)
                elif char in " -" and i + 1 < len(text) and text[i + 1].isascii():
                    if not text[i + 1].isalnum():
                        break
                    i += 1
                else:
                    break
            expected = IBAN_LENGTHS.get(m.group()[:2].upper())
            lengths = [expected] if expected else range(len(ends), 14, -1)
            for length in lengths:
                if length > len(ends):
                    continue
                end = ends[length - 1]
                if end < len(text) and text[end].isalnum():
                    continue
                if iban_is_valid(text[m.start() : end]):
                    yield self._entity(EntityType.IBAN, text, m.start(), end, m.group()[:2].upper())
                    break

    def _national_ids(self, text: str) -> Iterator[Entity]:
        for m in _NIR.finditer(text):
            if nir_is_valid(m.group()):
                yield self._entity(EntityType.NATIONAL_ID, text, m.start(), m.end(), "FR_NIR")
        for m in _US_SSN.finditer(text):
            yield self._entity(EntityType.NATIONAL_ID, text, m.start(), m.end(), "US_SSN")
        for m in _UK_NINO.finditer(text):
            yield self._entity(EntityType.NATIONAL_ID, text, m.start(), m.end(), "UK_NINO")

    def _identifiers(self, text: str) -> Iterator[Entity]:
        for m in _IDENTIFIER.finditer(text):
            value = m.group("value")
            # A keyword followed by "3" or "of" is not an identifier: require a digit and length.
            if len(value) >= 4 and any(c.isdigit() for c in value):
                yield self._entity(EntityType.IDENTIFIER, text, m.start("value"), m.end("value"))
