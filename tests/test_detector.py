from alias_pii.detector import RulesAndModel
from alias_pii.entities import Entity, EntityType
from alias_pii.masking import mask

TEXT = "Jean Dupont, né le 12/03/1985, IBAN FR76 3000 6000 0112 3456 7890 189."


def span(label, value, source="model", text=TEXT):
    start = text.index(value)
    return Entity(EntityType(label), start, start + len(value), value, source=source)


class FakeModel:
    """Stands in for the fine-tuned model: finds the name and a piece of the IBAN."""

    def detect(self, text):
        return [span("PERSON", "Jean Dupont", text=text), span("PHONE", "3000 6000", text=text)]


def test_union_keeps_both_sources():
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
