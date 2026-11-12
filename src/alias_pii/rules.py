"""Rule layer: regular expressions plus checksums for strict formats, French and English.

Covers EMAIL, PHONE, IBAN, NATIONAL_ID (FR NIR, US SSN, UK NINO), IDENTIFIER (a file or
contract number announced by a keyword) and BIRTH_DATE when a keyword announces it ("né(e) le",
"date of birth", "DOB"): a date alone may be any date. PERSON and ADDRESS are left to the model.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import replace

import phonenumbers

from alias_pii.entities import Entity, EntityType, resolve_overlaps
from alias_pii.validators import IBAN_LENGTHS, iban_is_valid, nir_is_valid

PHONE_REGIONS = ("FR", "GB", "US")

# Unicode domains too (jean@société.fr): \w is Unicode-aware; the TLD is letters only.
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]++@[\w-]++(?:\.[\w-]++)*\.[^\W\d_]{2,}\b")

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
    rf"(?:\b{_NUMBER_WORD}\s*(?:de\s+|du\s+|d['’]\s*|of\s+)?)?\b(?P<keyword>{_ID_KEYWORD})(?!\w)"
    rf"(?:\s+{_NUMBER_WORD})?\s*(?:[:#]\s*)?{_FILLER}"
    r"(?P<value>[A-Z0-9](?:[A-Z0-9/_.\-]*[A-Z0-9])?)",
    re.IGNORECASE,
)


_MONTHS = (
    r"(?:janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre"
    r"|d[ée]cembre|january|february|march|april|may|june|july|august|september|october"
    r"|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?"
)
_DATE = (
    r"(?:\d{1,2}[/.\-]\d{1,2}[/.\-](?:\d{4}|\d{2})"  # 16/11/1955, 01.12.1986, 07-16-51
    r"|\d{4}-\d{2}-\d{2}"  # 1955-11-16
    rf"|\d{{1,2}}(?:er|st|nd|rd|th)?\s+(?:of\s+)?{_MONTHS}\s+\d{{4}}"  # 2 novembre 1956
    rf"|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})"  # July 2, 1969
)
_BIRTH_KEYWORD = (
    r"(?:\bn[ée]e?(?:\(e\))?\s+le"  # né le, née le, né(e) le
    r"|\b(?:date\s+de\s+)?naiss(?:ance|\.)(?:\s+d[ée]clar[ée]e)?"
    r"|\bdate\s+of\s+birth|\bbirth\s*date|\bd\.?o\.?b\b\.?|\bborn(?:\s+on)?)"
)
# Keyword, then punctuation or a short verb before the date: "Date of birth: ", "DOB - ",
# "date of birth as ", "né(e) le : ".
_BIRTH_DATE = re.compile(
    rf"{_BIRTH_KEYWORD}[\s:(|\-–—]*(?:(?:is|was|as|est|le|on)\s+)?"
    rf"(?P<value>(?<!\d){_DATE})(?![\d\w])",
    re.IGNORECASE,
)
# The same, keyword after the date: "15/04/1965 : date de naissance", "8 July 1943: date of birth".
_BIRTH_DATE_BEFORE = re.compile(
    rf"(?<![\d\w])(?P<value>{_DATE})\s*[:\-–—]\s*{_BIRTH_KEYWORD}",
    re.IGNORECASE,
)


def keyword_kind(keyword: str) -> str:
    """The keyword that announced an identifier, as its `kind`: lower case, no accent, no final
    dot ("Adhérent" -> "adherent", "réf." -> "ref"). The detector keeps an identifier from the
    rules only when this keyword names a person's file (`detector.PERSON_FILE_KEYWORDS`)."""
    decomposed = unicodedata.normalize("NFKD", keyword.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).rstrip(".")


# Typography the rules would not read as a separator: spaces other than U+0020 (no-break,
# narrow no-break, thin, figure...) count as a space, and invisible characters (zero-width
# spaces and joiners, soft hyphen, BOM) are skipped. A value written with them, common in French
# typography and in text copied from a PDF, would otherwise stay readable.
SPACES = frozenset(
    "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008"
    "\u2009\u200a\u202f\u205f\u3000"
)
INVISIBLE = frozenset("\u00ad\u200b\u200c\u200d\u2060\ufeff")
_TYPOGRAPHY = re.compile(f"[{''.join(sorted(SPACES | INVISIBLE))}]")


def shadow(text: str) -> tuple[str, list[int]]:
    """The text as the rules read it (`SPACES` as a space, `INVISIBLE` skipped), and for each of
    its positions, plus its end, the position in the original text."""
    chars: list[str] = []
    origin: list[int] = []
    for i, char in enumerate(text):
        if char in INVISIBLE:
            continue
        chars.append(" " if char in SPACES else char)
        origin.append(i)
    origin.append(len(text))
    return "".join(chars), origin


class RuleDetector:
    """Deterministic detector. `detect` returns non-overlapping spans sorted by position."""

    name = "rules"

    def detect(self, text: str) -> list[Entity]:
        return resolve_overlaps(self.find(text))

    def find(self, text: str) -> list[Entity]:
        """Every rule's spans, before overlaps are merged: a caller keeping only some types
        (`detector.RulesAndModel`) filters first, so a type it drops cannot absorb one it keeps.
        The rules read the text with its typographic spaces and invisible characters normalised
        (`shadow`); spans point into the original text."""
        if not _TYPOGRAPHY.search(text):
            return self._find(text)
        read, origin = shadow(text)
        found = []
        for e in self._find(read):
            start, end = origin[e.start], origin[e.end - 1] + 1
            found.append(replace(e, start=start, end=end, text=text[start:end]))
        return found

    def _find(self, text: str) -> list[Entity]:
        return [
            *self._emails(text),
            *self._phones(text),
            *self._ibans(text),
            *self._national_ids(text),
            *self._identifiers(text),
            *self._birth_dates(text),
        ]

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
                yield self._entity(
                    EntityType.IDENTIFIER,
                    text,
                    m.start("value"),
                    m.end("value"),
                    keyword_kind(m.group("keyword")),
                )

    def _birth_dates(self, text: str) -> Iterator[Entity]:
        for m in [*_BIRTH_DATE.finditer(text), *_BIRTH_DATE_BEFORE.finditer(text)]:
            yield self._entity(EntityType.BIRTH_DATE, text, m.start("value"), m.end("value"))
