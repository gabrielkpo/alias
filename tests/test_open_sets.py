from alias_pii.benchmark import score_document
from alias_pii.entities import Entity, EntityType
from alias_pii.open_sets import tab_document

# A TAB-shaped document with fictitious values (tests/README.md).
TEXT = (
    "The case originated in an application (no. 12345/06) lodged by Mr John Example. "
    "The applicant was born in 1961. Judge A. Sample presided. See Article 29 § 3. "
    "Applicant B lives in Exampletown."
)


def mention(kind, value, start_from=0):
    start = TEXT.index(value, start_from)
    return {
        "entity_type": kind,
        "start_offset": start,
        "end_offset": start + len(value),
        "identifier_type": "QUASI",
    }


DOCUMENT = {
    "doc_id": "001-00000",
    "text": TEXT,
    "annotations": {
        "annotator2": {"entity_mentions": []},
        "annotator1": {
            "entity_mentions": [
                mention("CODE", "12345/06"),
                mention("PERSON", "Mr John Example"),
                mention("PERSON", "Mr John Example"),  # the same span twice: kept once
                mention("DATETIME", "1961"),
                mention("PERSON", "Judge A. Sample"),
                mention("CODE", "29 § 3"),
                mention("PERSON", "B", TEXT.index("Applicant B")),
                mention("LOC", "Exampletown"),
            ]
        },
    },
}


def test_tab_labels_become_alias_labels():
    converted = tab_document(DOCUMENT)
    found = [(TEXT[s["start"] : s["end"]], s["label"]) for s in converted["spans"]]
    assert found == [
        ("12345/06", "IDENTIFIER"),
        ("John Example", "PERSON"),  # honorific left out, as in Alias's own labels
        ("1961", "BIRTH_DATE"),  # a date announced by "born in"
        ("A. Sample", "PERSON"),
    ]
    ignored = [TEXT[s:e] for s, e in converted["ignore"]]
    assert ignored == ["29 § 3", "B"]  # a case-law reference and a lone initial
    assert converted["labels"] == ["PERSON", "IDENTIFIER", "BIRTH_DATE"]
    assert converted["source"] == "tab:001-00000"


def entity(label, value, start_from=0):
    start = TEXT.index(value, start_from)
    return Entity(EntityType(label), start, start + len(value), value)


def test_only_the_source_labels_are_scored_and_ignored_regions_are_skipped():
    gold = [entity("PERSON", "John Example")]
    predicted = [
        entity("PERSON", "John Example"),
        entity("ADDRESS", "Exampletown"),  # a label this source does not annotate
        entity("IDENTIFIER", "29 § 3"),  # inside an ignored region
        entity("PERSON", "Judge"),  # a real false positive
    ]
    start = TEXT.index("29 § 3")
    counts = score_document(
        TEXT, gold, predicted, labels=["PERSON"], ignore=[(start, start + len("29 § 3"))]
    )
    assert counts["ALL"].predicted == 2
    assert counts["PERSON"].strict == 1
    assert "ADDRESS" not in counts and "IDENTIFIER" not in counts
