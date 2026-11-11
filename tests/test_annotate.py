import pytest

from alias_pii.annotate import AnnotationError, collect, from_markup, prepare, to_markup
from alias_pii.entities import Entity, EntityType
from alias_pii.rules import RuleDetector

TEXT = "Écrire à Jean Dupont,\njean.dupont@example.com, IBAN FR76 3000 6000 0112 3456 7890 189."


def test_round_trip():
    entities = RuleDetector().detect(TEXT)
    marked = to_markup(TEXT, entities)
    assert "[[EMAIL|jean.dupont@example.com]]" in marked
    text, spans = from_markup(marked)
    assert text == TEXT
    assert [(TEXT[s["start"] : s["end"]], s["label"]) for s in spans] == [
        (e.text, e.type.value) for e in entities
    ]


def test_hand_edits_are_read_back():
    edited = "Écrire à [[PERSON|Jean Dupont]],\n[[ADDRESS|14 rue des Lilas\n69003 Lyon]]."
    text, spans = from_markup(edited)
    assert text == "Écrire à Jean Dupont,\n14 rue des Lilas\n69003 Lyon."
    assert [text[s["start"] : s["end"]] for s in spans] == [
        "Jean Dupont",
        "14 rue des Lilas\n69003 Lyon",
    ]


@pytest.mark.parametrize(
    "marked", ["[[NAME|Jean]]", "[[PERSON| Jean]]", "[[PERSON|]]", "[[PERSON|Jean]"]
)
def test_mistakes_are_refused(marked):
    with pytest.raises(AnnotationError):
        from_markup(marked)


def test_text_with_brackets_is_refused():
    with pytest.raises(AnnotationError):
        to_markup("see [[1]]", [Entity(EntityType.EMAIL, 0, 3, "see")])


def test_prepare_keeps_hand_work_and_collect_builds_the_set(tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    (source / "lettre.txt").write_text(TEXT, encoding="utf-8")
    out = tmp_path / "real" / "fr"
    assert len(prepare([source / "lettre.txt"], out, RuleDetector())) == 1
    annotated = out / "lettre.ann.txt"
    annotated.write_text(
        annotated.read_text("utf-8").replace("Jean Dupont,", "[[PERSON|Jean Dupont]],"), "utf-8"
    )
    assert prepare([source / "lettre.txt"], out, RuleDetector()) == []  # not overwritten
    [document] = collect(out, "fr")
    assert document["text"] == TEXT and document["source"] == "real:lettre"
    assert "PERSON" in [s["label"] for s in document["spans"]]


def test_only_data_real_is_accepted(tmp_path):
    from alias_pii.annotate import _inside_real

    assert _inside_real(tmp_path / "data" / "real" / "fr")
    assert not _inside_real(tmp_path / "docs" / "real")
    assert not _inside_real(tmp_path / "data" / "synthetic")
