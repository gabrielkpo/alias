import pytest

from alias_pii.validators import iban_is_valid, nir_is_valid

# All values are fictitious: published example IBANs and NIRs whose key was computed for the test.


@pytest.mark.parametrize(
    "iban",
    [
        "FR7630006000011234567890189",
        "FR76 3000 6000 0112 3456 7890 189",
        "fr76 3000 6000 0112 3456 7890 189",
        "GB82 WEST 1234 5698 7654 32",
        "DE89 3704 0044 0532 0130 00",
    ],
)
def test_valid_ibans(iban):
    assert iban_is_valid(iban)


@pytest.mark.parametrize(
    "iban",
    [
        "FR7630006000011234567890188",  # wrong check digits
        "FR763000600001123456789018",  # one character short for France
        "GB82WEST1234569876543",  # one character short for the UK
        "XX00",
    ],
)
def test_invalid_ibans(iban):
    assert not iban_is_valid(iban)


@pytest.mark.parametrize(
    "nir",
    [
        "185057800608491",
        "1 85 05 78 006 084 91",
        "2 90 02 75 123 456 21",
        "1 85 05 2A 006 084 35",  # Corsica: 2A counts as 19 in the key
    ],
)
def test_valid_nirs(nir):
    assert nir_is_valid(nir)


@pytest.mark.parametrize(
    "nir",
    [
        "185057800608492",  # wrong key
        "985057800608491",  # sex digit 9 does not exist
        "185137800608491",  # month 13
        "18505780060849",  # too short
    ],
)
def test_invalid_nirs(nir):
    assert not nir_is_valid(nir)
