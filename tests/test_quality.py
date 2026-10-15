from dataclasses import dataclass

from alias_pii.quality import check, deduplicate


@dataclass
class S:
    start: int
    end: int
    label: str


@dataclass
class E:
    text: str


def test_a_clean_document_passes():
    text = "Écrire à a.b@example.com"
    assert check(text, [S(9, 24, "EMAIL")]) == []


def test_bad_spans_are_reported():
    text = "Nom : Jean Dupont"
    problems = check(text, [S(5, 17, "PERSON"), S(10, 17, "PERSON"), S(0, 3, "NAME")])
    assert any("surrounding whitespace" in p for p in problems)
    assert any("overlaps" in p for p in problems)
    assert any("unknown label" in p for p in problems)


def test_unlabelled_value_is_rejected_unless_declared_as_distractor():
    text = "Écrire à a.b@example.com ou contact@corp.example"
    labels = [S(9, 24, "EMAIL")]
    assert any("outside the labels" in p for p in check(text, labels))
    assert check(text, labels, negatives=[S(28, 48, "EMAIL")]) == []


def test_unrealistic_formats_are_rejected():
    text = "IBAN FR76 3000 6000 0112 3456 7890 188 et SSN 123456789"
    problems = check(text, [S(5, 38, "IBAN"), S(46, 55, "NATIONAL_ID")])
    assert problems == ["IBAN: not a real-world format"]  # the compact SSN is a real format


def test_near_duplicates_are_removed():
    kept, removed = deduplicate([E("Dossier 2024/001"), E("DOSSIER  2025/772"), E("Autre")])
    assert [e.text for e in kept] == ["Dossier 2024/001", "Autre"] and removed == 1
