"""Checksum validators for strict formats. Inputs may contain separators: white space, dots,
slashes, dashes of any kind and invisible characters; full-width digits read as digits."""

from __future__ import annotations

import re
import unicodedata

# Total IBAN length per country (ISO 13616 registry), for the countries most likely to appear
# in French and English documents. Other countries fall back to the generic 15-34 range.
IBAN_LENGTHS = {
    "AT": 20, "BE": 16, "CH": 21, "DE": 22, "DK": 18, "ES": 24, "FI": 18, "FR": 27, "GB": 22,
    "GR": 27, "IE": 22, "IT": 27, "LU": 20, "MC": 27, "NL": 18, "NO": 15, "PL": 28, "PT": 25,
    "SE": 24,
}  # fmt: skip

# The separators the rules read through (rules.SPACES, DASHES, INVISIBLE), so one value written
# two ways compacts to the same string.
_SEPARATORS = re.compile(
    r"[\s./\-\u00ad\u061c\u180e\u200b-\u200f\u2010-\u2015\u202a-\u202e\u2060-\u2064"
    r"\u2066-\u2069\u2212\ufe58\ufe63\uff0d\ufeff]"
)


def compact(value: str) -> str:
    return _SEPARATORS.sub("", unicodedata.normalize("NFKC", value)).upper()


def iban_is_valid(value: str) -> bool:
    """ISO 7064 mod 97-10: first 4 characters moved to the end, letters as numbers, mod 97 == 1."""
    iban = compact(value)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    expected = IBAN_LENGTHS.get(iban[:2])
    if expected is not None and len(iban) != expected:
        return False
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def nir_is_valid(value: str) -> bool:
    """French social security number: 13 characters + 2-digit key = 97 - (number mod 97).

    Corsica departments 2A and 2B are replaced by 19 and 18 before computing the key.
    """
    nir = compact(value)
    if not re.fullmatch(r"[1-478]\d{4}(?:\d{2}|2[AB])\d{6}\d{2}", nir):
        return False
    month = int(nir[3:5])
    # 01-12 is a real month; 20-42 and 50-99 are used when the birth month is unknown.
    if not (1 <= month <= 12 or 20 <= month <= 42 or 50 <= month <= 99):
        return False
    body = nir[:13].replace("2A", "19").replace("2B", "18")
    return 97 - int(body) % 97 == int(nir[13:])
