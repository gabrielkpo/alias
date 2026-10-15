import json
from pathlib import Path

from alias_pii import sources
from alias_pii.documents import Span


def test_detokenise_french_and_person_spans():
    tokens = ["Selon", "l'", "auteur", "Victor", "Hugo", ",", "la", "ville", "(", "Paris", ")", "."]
    tags = [0, 0, 0, 2, 2, 0, 0, 0, 0, 1, 0, 0]
    text, spans = sources._detokenise(tokens, tags)
    assert text == "Selon l'auteur Victor Hugo, la ville (Paris)."
    assert [text[s.start : s.end] for s in spans] == ["Victor Hugo"]


def test_merge_joins_same_label_overlaps_only():
    merged = sources._merge([Span(0, 10, "PERSON"), Span(0, 4, "PERSON"), Span(12, 20, "ADDRESS")])
    assert merged == [Span(0, 10, "PERSON"), Span(12, 20, "ADDRESS")]


def test_gretel_maps_labels_and_drops_others(monkeypatch):
    text = "Client : Ana Li, Acme SA, ana.li@example.org "
    row = {
        "quality_score": 90,
        "generated_text": text,
        "pii_spans": "[]",
        "__index_level_0__": 7,
        "expanded_type": "Letter",
        "domain": "finance",
        "document_type": "Email",
    }
    row["pii_spans"] = json.dumps(
        [
            {"start": 9, "end": 15, "label": "name"},
            {"start": 17, "end": 24, "label": "company"},
            {"start": 26, "end": 45, "label": "email"},
        ]
    )
    monkeypatch.setattr(sources, "_read", lambda path: [row, {**row, "quality_score": 50}])
    documents = list(sources.gretel(Path("raw"), "fr", "test"))
    assert len(documents) == 1  # the low-quality row is skipped
    doc = documents[0]
    assert [(s.label, text[s.start : s.end]) for s in doc.spans] == [
        ("PERSON", "Ana Li"),
        ("EMAIL", "ana.li@example.org"),
    ]
    assert doc.split == "test"
    kept, rejected = sources.convert(iter(documents))
    assert len(kept) == 1 and not rejected


def test_wikiner_paragraphs_keep_offsets(monkeypatch):
    rows = [
        {"id": 2, "tokens": ["Marie", "Curie", "naît", "."], "ner_tags": [2, 2, 0, 0]},
        {"id": 1, "tokens": ["Il", "pleut", "."], "ner_tags": [0, 0, 0]},
    ]
    monkeypatch.setattr(sources, "_read", lambda path: rows)
    (doc,) = sources.wikiner(Path("raw"), "test", sentences=2)
    assert doc.text == "Il pleut. Marie Curie naît."
    assert [doc.text[s.start : s.end] for s in doc.spans] == ["Marie Curie"]
