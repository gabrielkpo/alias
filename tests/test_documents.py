from collections import Counter

import pytest

pytest.importorskip("faker")

from alias_pii.build_dataset import build_split, datasheet  # noqa: E402
from alias_pii.documents import DOC_TYPES, LABELS, TEST_ONLY_TYPES, GridGenerator  # noqa: E402
from alias_pii.quality import check  # noqa: E402


@pytest.fixture(scope="module")
def built():
    return {
        split: build_split(split, n, seed=2)
        for split, n in [("train", 800), ("validation", 150), ("test", 150)]
    }


def test_every_document_passes_the_gates(built):
    for documents, _, _ in built.values():
        for document in documents:
            assert check(document.text, document.spans, document.negatives) == []


def test_grid_is_covered(built):
    train = built["train"][0]
    assert {d.doc_type for d in train} == set(DOC_TYPES) - TEST_ONLY_TYPES
    assert {d.layout for d in train} == {"prose", "key_value", "table", "email", "chat"}
    assert {d.language for d in train} == {"fr", "en", "mixed"}
    assert {s.label for d in train for s in d.spans} == set(LABELS)


def test_test_only_type_never_appears_in_train_or_validation(built):
    for split in ("train", "validation"):
        assert not {d.doc_type for d in built[split][0]} & TEST_ONLY_TYPES
    assert {d.doc_type for d in built["test"][0]} & TEST_ONLY_TYPES


def test_training_labels_are_balanced(built):
    counts = Counter(s.label for d in built["train"][0] for s in d.spans)
    total = sum(counts.values())
    shares = {label: counts[label] / total for label in LABELS}
    assert max(shares.values()) < 0.27 and min(shares.values()) > 0.06


def test_generation_is_reproducible():
    first = [GridGenerator("train", seed=4).document().text for _ in range(1)]
    assert first == [GridGenerator("train", seed=4).document().text for _ in range(1)]


def test_datasheet_reports_every_axis(built):
    sheet = datasheet(built, seed=2)
    for heading in ("Size and quality gates", "Labels", "doc type", "layout", "person origin"):
        assert heading in sheet
