import pytest

from alias_pii.entities import EntityType
from alias_pii.rules import RuleDetector

detector = RuleDetector()


def found(text):
    return [(e.type, e.text, e.kind) for e in detector.detect(text)]


def test_french_letter():
    text = (
        "Bonjour, merci d'écrire à jean.dupont@exemple.fr ou d'appeler le 06 12 34 56 78. "
        "Virement sur FR76 3000 6000 0112 3456 7890 189 avant vendredi. "
        "N° de sécurité sociale : 1 85 05 78 006 084 91. Dossier n° 2024/00421."
    )
    assert found(text) == [
        (EntityType.EMAIL, "jean.dupont@exemple.fr", None),
        (EntityType.PHONE, "06 12 34 56 78", "FR"),
        (EntityType.IBAN, "FR76 3000 6000 0112 3456 7890 189", "FR"),
        (EntityType.NATIONAL_ID, "1 85 05 78 006 084 91", "FR_NIR"),
        (EntityType.IDENTIFIER, "2024/00421", None),
    ]


def test_english_letter():
    text = (
        "Please contact jane.doe@example.co.uk or call +44 20 7946 0958. "
        "US office: (415) 555-0132. SSN 123-45-6789, NINO AB 12 34 56 C. "
        "Pay to GB82 WEST 1234 5698 7654 32. Customer ID: AC-559102."
    )
    assert found(text) == [
        (EntityType.EMAIL, "jane.doe@example.co.uk", None),
        (EntityType.PHONE, "+44 20 7946 0958", "GB"),
        (EntityType.PHONE, "(415) 555-0132", "US"),
        (EntityType.NATIONAL_ID, "123-45-6789", "US_SSN"),
        (EntityType.NATIONAL_ID, "AB 12 34 56 C", "UK_NINO"),
        (EntityType.IBAN, "GB82 WEST 1234 5698 7654 32", "GB"),
        (EntityType.IDENTIFIER, "AC-559102", None),
    ]


def test_iban_stops_before_the_next_word():
    text = "IBAN FR7630006000011234567890189 ET le reste"
    assert found(text) == [(EntityType.IBAN, "FR7630006000011234567890189", "FR")]


def test_invalid_checksums_are_ignored():
    text = "IBAN FR7630006000011234567890188, NIR 185057800608492"
    assert found(text) == []


def test_ssn_with_forbidden_area_is_ignored():
    assert found("SSN 666-45-6789 and 000-12-3456") == []


def test_nino_with_forbidden_prefix_is_ignored():
    assert found("NINO GB 12 34 56 C") == []


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Numéro de contrat : C-88123", "C-88123"),
        ("réf. FAC2024-77", "FAC2024-77"),
        ("Policy number 88-1234-X", "88-1234-X"),
        ("claim #CLM00912", "CLM00912"),
    ],
)
def test_identifiers_after_a_keyword(text, value):
    assert found(text) == [(EntityType.IDENTIFIER, value, None)]


def test_keyword_without_identifier():
    assert found("Le dossier est complet, the order of 3 items is fine.") == []


def test_iban_beats_identifier_on_overlap():
    text = "Compte : FR76 3000 6000 0112 3456 7890 189"
    assert [e.type for e in detector.detect(text)] == [EntityType.IBAN]


def test_nir_beats_phone_on_overlap():
    text = "NIR 185057800608491"
    assert [e.type for e in detector.detect(text)] == [EntityType.NATIONAL_ID]
