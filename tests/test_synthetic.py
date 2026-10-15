import json
from collections import Counter

import pytest

pytest.importorskip("faker")

from alias_pii.entities import EntityType  # noqa: E402
from alias_pii.rules import RuleDetector  # noqa: E402
from alias_pii.synthetic import generate, templates_for, write_jsonl  # noqa: E402


@pytest.fixture(scope="module")
def train():
    return generate(300, "train", seed=1)


def test_generation_is_reproducible():
    first = [(e.text, e.spans) for e in generate(20, "train", seed=7)]
    assert first == [(e.text, e.spans) for e in generate(20, "train", seed=7)]
    assert first != [(e.text, e.spans) for e in generate(20, "train", seed=8)]


def test_spans_point_at_non_empty_non_overlapping_values(train):
    for example in train:
        previous_end = -1
        for span in example.spans:
            value = example.text[span.start : span.end]
            assert value.strip() == value and value
            assert span.start >= previous_end
            assert span.label in EntityType.__members__
            previous_end = span.end


def test_both_languages_and_every_label_are_covered(train):
    assert {e.language for e in train} == {"fr", "en"}
    assert {e.locale for e in train} == {"fr_FR", "en_US", "en_GB"}
    assert {s.label for e in train for s in e.spans} == set(EntityType.__members__)


def test_validation_templates_are_never_used_for_training():
    assert not set(templates_for("train")) & set(templates_for("validation"))
    assert {e.template for e in generate(100, "validation")} <= set(templates_for("validation"))


@pytest.mark.parametrize("label", ["EMAIL", "PHONE", "IBAN", "NATIONAL_ID"])
def test_rule_formats_are_realistic(train, label):
    """The rules must find every generated e-mail, phone, IBAN and national ID: otherwise the
    generator produces values no real document would contain."""
    detector = RuleDetector()
    missed = Counter()
    for example in train:
        found = {(e.start, e.end) for e in detector.detect(example.text)}
        for span in example.spans:
            if span.label == label and (span.start, span.end) not in found:
                missed[example.text[span.start : span.end]] += 1
    assert not missed


def test_jsonl_round_trip(tmp_path, train):
    write_jsonl(train[:5], tmp_path / "out" / "train.jsonl")
    lines = (tmp_path / "out" / "train.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["text"] == train[0].text
    assert record["spans"][0] == {
        "start": train[0].spans[0].start,
        "end": train[0].spans[0].end,
        "label": train[0].spans[0].label,
    }
