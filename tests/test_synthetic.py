import json

import pytest

pytest.importorskip("faker")

from alias_pii.entities import EntityType  # noqa: E402
from alias_pii.quality import check  # noqa: E402
from alias_pii.synthetic import (  # noqa: E402
    generate,
    generate_with_report,
    templates_for,
    write_jsonl,
)


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


def test_every_generated_document_passes_the_quality_gates(train):
    for example in train:
        assert check(example.text, example.spans, example.negatives) == []


def test_rejections_are_rare():
    examples, rejected = generate_with_report(300, "train", seed=3)
    assert len(examples) == 300 and sum(rejected.values()) < 15


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
