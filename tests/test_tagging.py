from alias_pii.tagging import IGNORE, TAG_ID, TAGS, merge_windows, spans_from_tokens, token_labels

TEXT = "Bonjour Ana Li, IBAN FR76 3000."
#       0       8   12 14   20  25


def offsets_of(text, words):
    out, cursor = [(0, 0)], 0
    for w in words:
        start = text.index(w, cursor)
        out.append((start, start + len(w)))
        cursor = start + len(w)
    return out + [(0, 0)]


def test_token_labels_bio_and_special_tokens():
    offsets = offsets_of(TEXT, ["Bonjour", "Ana", "Li", ",", "IBAN", "FR76", "3000", "."])
    spans = [(8, 14, "PERSON"), (21, 30, "IBAN")]
    tags = [TAGS[i] if i != IGNORE else None for i in token_labels(TEXT, offsets, spans)]
    assert tags == [None, "O", "B-PERSON", "I-PERSON", "O", "O", "B-IBAN", "I-IBAN", "O", None]


def test_token_with_leading_space_is_labelled():
    assert token_labels(TEXT, [(7, 11)], [(8, 14, "PERSON")]) == [TAG_ID["B-PERSON"]]


def test_round_trip_through_windows():
    offsets = offsets_of(TEXT, ["Bonjour", "Ana", "Li", ",", "IBAN", "FR76", "3000", "."])
    labels = token_labels(TEXT, offsets, [(8, 14, "PERSON"), (21, 30, "IBAN")])
    tags = [0 if t == IGNORE else t for t in labels]
    # two overlapping windows: the second disagrees on "Ana" but sees it at its edge
    first = (offsets[:6] + [(0, 0)], tags[:6] + [0])
    second = ([(0, 0)] + offsets[2:], [0, 0] + tags[3:])
    entities = spans_from_tokens(TEXT, merge_windows([first, second]))
    assert [(e.type.value, e.text) for e in entities] == [
        ("PERSON", "Ana Li"),
        ("IBAN", "FR76 3000"),
    ]


def test_i_without_b_starts_a_span():
    tokens = [(8, 11, TAG_ID["I-PERSON"]), (12, 14, TAG_ID["I-PERSON"])]
    assert [e.text for e in spans_from_tokens(TEXT, tokens)] == ["Ana Li"]
