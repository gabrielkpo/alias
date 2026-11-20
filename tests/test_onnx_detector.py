"""OnnxDetector, the detector the app and `alias-pii serve` run, on a text longer than one
window, with a stub tokenizer and session: windows go to the model a few at a time and their
results merge, an entity in the overlap included. No model and no ONNX Runtime needed."""

import pytest

np = pytest.importorskip("numpy")

from alias_pii.entities import EntityType  # noqa: E402
from alias_pii.onnx_export import OnnxDetector  # noqa: E402
from alias_pii.tagging import TAG_ID  # noqa: E402

TEXT = "Bonjour Jean Dupont merci , Jean Dupont signe ici ."
WINDOW, STRIDE = 4, 2


class Tokenizer:
    """Splits on spaces into windows of WINDOW words overlapping by STRIDE, padded."""

    def __call__(self, text, **options):
        words, position = [], 0
        for word in text.split(" "):
            words.append((word, position, position + len(word)))
            position += len(word) + 1
        windows = [words[i : i + WINDOW] for i in range(0, len(words) - STRIDE, WINDOW - STRIDE)]
        vocab = {w for w, _, _ in words}
        index = {w: i + 1 for i, w in enumerate(sorted(vocab))}
        self.word_of = {i: w for w, i in index.items()}
        ids = [[index[w] for w, _, _ in win] + [0] * (WINDOW - len(win)) for win in windows]
        offsets = [[(s, e) for _, s, e in win] + [(0, 0)] * (WINDOW - len(win)) for win in windows]
        mask = [[1] * len(win) + [0] * (WINDOW - len(win)) for win in windows]
        return {
            "input_ids": np.array(ids),
            "attention_mask": np.array(mask),
            "offset_mapping": np.array(offsets),
        }


class Session:
    """Tags Jean as B-PERSON and Dupont as I-PERSON; records each batch size."""

    def __init__(self, tokenizer):
        self.tokenizer, self.batches = tokenizer, []

    def run(self, names, inputs):
        ids = inputs["input_ids"]
        self.batches.append(len(ids))
        logits = np.zeros((*ids.shape, len(TAG_ID)))
        for (row, col), token in np.ndenumerate(ids):
            word = self.tokenizer.word_of.get(int(token), "")
            tag = {"Jean": "B-PERSON", "Dupont": "I-PERSON"}.get(word, "O")
            logits[row, col, TAG_ID[tag]] = 1.0
        return [logits]


def test_a_long_text_is_detected_window_by_window_in_small_batches():
    detector = object.__new__(OnnxDetector)
    detector.tokenizer = Tokenizer()
    detector.session = Session(detector.tokenizer)
    detector.max_length, detector.stride, detector.batch = WINDOW, STRIDE, 2
    found = detector.detect(TEXT)
    assert [(e.type, e.text) for e in found] == [
        (EntityType.PERSON, "Jean Dupont"),
        (EntityType.PERSON, "Jean Dupont"),
    ]
    assert max(detector.session.batches) <= 2 and sum(detector.session.batches) > 2
