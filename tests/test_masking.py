from alias_pii.entities import Entity, EntityType
from alias_pii.masking import AliasTable, find_leaks, mask, restore
from alias_pii.rules import RuleDetector

detector = RuleDetector()


class FakeNames:
    """Stands in for the future model: marks fixed person names, plus the rules."""

    def __init__(self, *names):
        self.names = names

    def detect(self, text):
        entities = detector.detect(text)
        for name in self.names:
            start = text.find(name)
            while start != -1:
                end = start + len(name)
                entities.append(Entity(EntityType.PERSON, start, end, name, source="fake"))
                start = text.find(name, end)
        return sorted(entities, key=lambda e: e.start)


def test_round_trip_restores_the_original_values():
    text = "Écrire à jean.dupont@exemple.fr, IBAN FR76 3000 6000 0112 3456 7890 189."
    result = mask(text, detector)
    assert result.text == "Écrire à [EMAIL_1], IBAN [IBAN_1]."
    answer = "Le virement vers [IBAN_1] est confirmé ; réponse envoyée à [EMAIL_1]."
    restored = restore(answer, result.table)
    assert restored.text == (
        "Le virement vers FR76 3000 6000 0112 3456 7890 189 est confirmé ; "
        "réponse envoyée à jean.dupont@exemple.fr."
    )
    assert restored.missing == []
    assert restored.unknown == []


def test_same_value_gets_the_same_alias():
    text = "Call 06 12 34 56 78, or +33 6 12 34 56 78, not 07 98 76 54 32."
    assert mask(text, detector).text == "Call [PHONE_1], or [PHONE_1], not [PHONE_2]."


def test_person_alias_ignores_case_and_accents():
    text = "Hélène Martin a signé. HELENE MARTIN confirme."
    result = mask(text, FakeNames("Hélène Martin", "HELENE MARTIN"))
    assert result.text == "[PERSON_1] a signé. [PERSON_1] confirme."


def test_table_is_shared_across_documents():
    table = AliasTable()
    first = mask("mail: a.b@exemple.fr", detector, table)
    second = mask("autre: c.d@exemple.fr, encore a.b@exemple.fr", detector, table)
    assert first.text == "mail: [EMAIL_1]"
    assert second.text == "autre: [EMAIL_2], encore [EMAIL_1]"


def test_alias_already_in_the_input_is_not_reused():
    text = "Le gabarit utilise [EMAIL_1] ; écrire à a.b@exemple.fr"
    result = mask(text, detector)
    assert result.text == "Le gabarit utilise [EMAIL_1] ; écrire à [EMAIL_2]"
    restored = restore(result.text, result.table)
    assert restored.text == "Le gabarit utilise [EMAIL_1] ; écrire à a.b@exemple.fr"
    assert restored.unknown == []


def test_restore_reports_dropped_and_invented_aliases():
    result = mask("a.b@exemple.fr et 06 12 34 56 78", detector)
    restored = restore("Contact [EMAIL_1] and [PERSON_7].", result.table)
    assert restored.text == "Contact a.b@exemple.fr and [PERSON_7]."
    assert restored.missing == ["[PHONE_1]"]
    assert restored.unknown == ["[PERSON_7]"]


def test_restore_tolerates_spaces_inside_brackets():
    result = mask("a.b@exemple.fr", detector)
    assert restore("Send to [ EMAIL_1 ].", result.table).text == "Send to a.b@exemple.fr."


def test_table_repr_does_not_show_values():
    result = mask("a.b@exemple.fr", detector)
    assert "a.b" not in repr(result.table)


def test_no_leak_after_masking():
    text = "IBAN FR76 3000 6000 0112 3456 7890 189, NIR 1 85 05 78 006 084 91"
    result = mask(text, detector)
    assert find_leaks(result.text, result.entities) == []


def test_leak_is_found_when_a_value_is_written_differently():
    iban = Entity(EntityType.IBAN, 0, 33, "FR76 3000 6000 0112 3456 7890 189")
    assert find_leaks("compte FR7630006000011234567890189", [iban]) == [iban]
