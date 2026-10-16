"""Character spans to BIO token labels and back (step 4, docs/TRAINING.md).

The dataset labels characters; a token-classification model labels tokens. These functions work
on the tokenizer's offset mapping only, so they are tested without a model:

- `token_labels`: one label id per token of a window; special tokens get -100 (ignored by the
  loss);
- `merge_windows`: long documents are read in overlapping windows; each token keeps the prediction
  of the window where it sits farthest from an edge, where the model saw the most context;
- `spans_from_tokens`: B/I runs of one label become one character span.
"""

from __future__ import annotations

from alias_pii.entities import Entity, EntityType

LABELS = [t.value for t in EntityType]
TAGS = ["O"] + [f"{prefix}-{label}" for label in LABELS for prefix in ("B", "I")]
TAG_ID = {tag: i for i, tag in enumerate(TAGS)}
IGNORE = -100


def token_labels(
    text: str, offsets: list[tuple[int, int]], spans: list[tuple[int, int, str]]
) -> list[int]:
    """BIO label id for each token. `offsets` are the (start, end) characters of each token, (0, 0)
    for special tokens; `spans` are (start, end, label). A token belongs to the span containing
    its first non-space character; it is `B` when it is the first token of that span in this
    window, `I` otherwise (a window may start inside a span)."""
    ordered = sorted(spans)
    labels, previous = [], None
    for start, end in offsets:
        if start == end:
            labels.append(IGNORE)
            previous = None
            continue
        while start < end - 1 and text[start].isspace():  # some tokenizers include the space
            start += 1
        span = next((s for s in ordered if s[0] <= start < s[1]), None)
        if span is None:
            labels.append(TAG_ID["O"])
        else:
            labels.append(TAG_ID[f"{'I' if previous == span else 'B'}-{span[2]}"])
        previous = span
    return labels


def merge_windows(
    windows: list[tuple[list[tuple[int, int]], list[int]]],
) -> list[tuple[int, int, int]]:
    """(start, end, tag id) per token of the document from overlapping windows, each window given as
    (offsets, predicted tag ids). Keeps, for each token, the window where it is most central."""
    best: dict[tuple[int, int], tuple[int, int]] = {}
    for offsets, tags in windows:
        real = [i for i, (s, e) in enumerate(offsets) if s != e]
        for rank, i in enumerate(real):
            margin = min(rank, len(real) - 1 - rank)
            key = offsets[i]
            if key not in best or margin > best[key][0]:
                best[key] = (margin, tags[i])
    return sorted((s, e, tag) for (s, e), (_, tag) in best.items())


def spans_from_tokens(text: str, tokens: list[tuple[int, int, int]]) -> list[Entity]:
    """Character spans from sorted (start, end, tag id) tokens. An `I` continues the open span
    when it has the same label; an `I` without an open span of its label starts one (the model
    sometimes misses the `B`). Spans are trimmed of surrounding whitespace."""
    entities, open_span = [], None  # open_span: [label, start, end]

    def close() -> None:
        if open_span:
            label, start, end = open_span
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            if start < end:
                entities.append(
                    Entity(EntityType(label), start, end, text[start:end], 1.0, "model")
                )

    for start, end, tag_id in tokens:
        tag = TAGS[tag_id]
        if tag == "O":
            close()
            open_span = None
            continue
        prefix, label = tag.split("-", 1)
        if prefix == "I" and open_span and open_span[0] == label:
            open_span[2] = end
        else:
            close()
            open_span = [label, start, end]
    close()
    return entities
