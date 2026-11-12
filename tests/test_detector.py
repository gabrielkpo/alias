from alias_pii.detector import RulesAndModel
from alias_pii.entities import Entity, EntityType
from alias_pii.masking import mask

TEXT = "Jean Dupont, né le 12/03/1985, IBAN FR76 3000 6000 0112 3456 7890 189."


def span(label, value, source="model", text=TEXT):
    start = text.index(value)
    return Entity(EntityType(label), start, start + len(value), value, source=source)


class FakeModel:
    """Stands in for the fine-tuned model: finds the name and, wrongly, a piece of the IBAN."""

    def detect(self, text):
        return [span("PERSON", "Jean Dupont", text=text), span("PHONE", "3000 6000", text=text)]


def test_model_spans_plus_proven_rule_spans():
    found = RulesAndModel(FakeModel()).detect(TEXT)
    assert [(e.type, e.text) for e in found] == [
        (EntityType.PERSON, "Jean Dupont"),
        (EntityType.BIRTH_DATE, "12/03/1985"),
        (EntityType.IBAN, "FR76 3000 6000 0112 3456 7890 189"),  # the checksummed span wins
    ]


def test_overlap_is_merged_not_dropped():
    class Wider:
        def detect(self, text):
            return [span("IDENTIFIER", "189.", text=text)]

    found = RulesAndModel(Wider()).detect(TEXT)
    iban = [e for e in found if e.type is EntityType.IBAN]
    assert len(iban) == 1 and iban[0].text.endswith("189.")  # union, nothing left in clear


def test_masks_with_the_combined_detector():
    result = mask(TEXT, RulesAndModel(FakeModel()))
    assert result.text == "[PERSON_1], né le [BIRTH_DATE_1], IBAN [IBAN_1]."


def test_rules_only_add_the_types_they_prove():
    text = (
        "Standard : 01 99 00 12 34, facture n° 2024/00421, IBAN FR76 3000 6000 0112 3456 7890 189."
    )

    class Nothing:
        def detect(self, text):
            return []

    assert [e.type for e in RulesAndModel(Nothing()).detect(text)] == [EntityType.IBAN]
    every = RulesAndModel(Nothing(), rule_types=None).detect(text)
    assert [e.type for e in every] == [EntityType.PHONE, EntityType.IDENTIFIER, EntityType.IBAN]


def test_person_file_identifiers_are_kept_other_identifiers_left_out():
    class Nothing:
        def detect(self, text):
            return []

    from alias_pii.detector import PERSON_FILE_KEYWORDS

    text = "Objet : dossier n° 2024/00421. Commande n° CMD-2024-118. Facture n° F-2024-07."
    assert RulesAndModel(Nothing()).id_keywords == PERSON_FILE_KEYWORDS  # the default
    assert [(e.type, e.text) for e in RulesAndModel(Nothing()).detect(text)] == [
        (EntityType.IDENTIFIER, "2024/00421")
    ]
    assert RulesAndModel(Nothing(), id_keywords=()).detect(text) == []  # the second variant


def test_a_dropped_rule_type_does_not_absorb_a_kept_one():
    class Nothing:
        def detect(self, text):
            return []

    # The rules' phone matcher also reads this claim number as a US phone; phones from the
    # rules are dropped, so the identifier must survive instead of being merged into a phone.
    text = "Déclaration de sinistre n° 2015550123"
    assert [(e.type, e.text) for e in RulesAndModel(Nothing()).detect(text)] == [
        (EntityType.IDENTIFIER, "2015550123")
    ]
