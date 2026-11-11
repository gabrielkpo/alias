import pytest

from alias_pii.entities import EntityType
from alias_pii.masking import mask
from alias_pii.rules import RuleDetector

detector = RuleDetector()


def found(text):
    return [(e.type, e.text, e.kind) for e in detector.detect(text)]


def test_french_letter():
    text = (
        "Bonjour, merci d'écrire à jean.dupont@example.com ou d'appeler le 01 99 00 12 34. "
        "Virement sur FR76 3000 6000 0112 3456 7890 189 avant vendredi. "
        "N° de sécurité sociale : 1 85 05 78 006 084 91. Dossier n° 2024/00421."
    )
    assert found(text) == [
        (EntityType.EMAIL, "jean.dupont@example.com", None),
        (EntityType.PHONE, "01 99 00 12 34", "FR"),
        (EntityType.IBAN, "FR76 3000 6000 0112 3456 7890 189", "FR"),
        (EntityType.NATIONAL_ID, "1 85 05 78 006 084 91", "FR_NIR"),
        (EntityType.IDENTIFIER, "2024/00421", None),
    ]


def test_english_letter():
    text = (
        "Please contact jane.doe@example.org or call +44 20 7946 0958. "
        "US office: (415) 555-0132. SSN 123-45-6789, NINO AB 12 34 56 C. "
        "Pay to GB82 WEST 1234 5698 7654 32. Customer ID: AC-559102."
    )
    assert found(text) == [
        (EntityType.EMAIL, "jane.doe@example.org", None),
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


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        # a weaker overlapping span is merged, not dropped: no prefix or suffix left in clear
        ("Customer ID: AB-0199001234-ZZ", "Customer ID: [PHONE_1]"),
        ("Account number is 12345678", "Account number is [IDENTIFIER_1]"),
        ("Le numéro de dossier est le 2024/1234", "Le numéro de dossier est le [IDENTIFIER_1]"),
        ("écrire à jean@société.example", "écrire à [EMAIL_1]"),
        ("NIR 1-85-05-78-006-084-91", "NIR [NATIONAL_ID_1]"),
        ("NINO ab 12 34 56 c", "NINO [NATIONAL_ID_1]"),
    ],
)
def test_formats_that_used_to_leak(text, masked):
    assert mask(text, detector).text == masked


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Karim El Amrani, né le 2 novembre 1956, demeurant à Lyon.", "2 novembre 1956"),
        ("Je suis née le 01.12.1986.", "01.12.1986"),
        ("Köster, né(e) le 16/01/1994.", "16/01/1994"),
        ("Date de naissance déclarée : 16 décembre 1985", "16 décembre 1985"),
        ("Naissance : 25/07/1986", "25/07/1986"),
        ("Name: Tran Thi Lan Date of Birth: July 2, 1969", "July 2, 1969"),
        ("DOB : 07/11/1947.", "07/11/1947"),
        ("They confirmed their date of birth as 07/16/1951.", "07/16/1951"),
        ("I was born on 18 July 2001 in Leeds.", "18 July 2001"),
        ("Date of Birth: 1981-11-30", "1981-11-30"),
        ("15/04/1965 : date de naissance de l'assuré.", "15/04/1965"),
    ],
)
def test_birth_date_announced_by_a_keyword(text, value):
    assert (EntityType.BIRTH_DATE, value, None) in found(text)


@pytest.mark.parametrize(
    "text",
    [
        "Le contrat est signé le 12/03/2020.",
        "The meeting is on July 2, 2024.",
        "Il ne le savait pas le 3 mars.",
    ],
)
def test_other_dates_are_left_to_the_model(text):
    assert not [f for f in found(text) if f[0] is EntityType.BIRTH_DATE]


@pytest.mark.parametrize("text", ["+" * 50_000, "a@" + "a." * 25_000 + "1", "+@" * 25_000])
def test_rules_stay_fast_on_hostile_input(text):
    import time

    start = time.perf_counter()
    detector.detect(text)
    assert time.perf_counter() - start < 2.0
