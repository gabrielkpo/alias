from alias_pii.baselines import _chunks, language_of
from alias_pii.benchmark import report, run, score_document
from alias_pii.entities import Entity, EntityType

TEXT = "Contact: Ana Li, ana.li@example.org, 06 12 34 56 78."


def entity(label, value, text=TEXT):
    start = text.index(value)
    return Entity(EntityType(label), start, start + len(value), value)


def test_strict_overlap_and_leak():
    gold = [entity("PERSON", "Ana Li"), entity("EMAIL", "ana.li@example.org")]
    predicted = [entity("PERSON", "Ana"), entity("EMAIL", "ana.li@example.org")]
    c = score_document(TEXT, gold, predicted)
    assert (c["ALL"].gold, c["ALL"].predicted, c["ALL"].strict) == (2, 2, 1)
    assert c["PERSON"].overlap_gold == 1 and c["PERSON"].strict == 0
    assert c["PERSON"].leaked == 0  # "Li" remains, but not the full value
    assert c["EMAIL"].leaked == 0


def test_missed_value_leaks():
    gold = [entity("EMAIL", "ana.li@example.org")]
    c = score_document(TEXT, gold, [])
    assert c["EMAIL"].leaked == 1 and c["ALL"].scores()["leak_rate"] == 1.0


class Fixed:
    def detect(self, text):
        return [entity("EMAIL", "ana.li@example.org", text)]


def test_run_and_report():
    doc = {
        "text": TEXT,
        "language": "en",
        "source": "grid-v0.2",
        "spans": [{"start": 17, "end": 35, "label": "EMAIL"}],
    }
    assert TEXT[17:35] == "ana.li@example.org"
    summary = run("fixed", Fixed(), [doc, doc]).summary()
    assert summary["by"]["all"]["all"]["recall"] == 1.0
    assert summary["by"]["language"]["en"]["precision"] == 1.0
    assert "| fixed | 1.000 |" in report([summary], "test", 2)


def test_chunks_cover_text_and_language():
    text = ("ligne de texte assez longue\n" * 100).strip()
    pieces = _chunks(text, 200)
    assert "".join(p for _, p in pieces) == text
    assert all(text[o : o + len(p)] == p for o, p in pieces)
    assert language_of("Le patient est venu pour une visite.") == "fr"
    assert language_of("The patient came for a visit with the doctor.") == "en"


def test_duplicate_predictions_count_once():
    gold = [entity("EMAIL", "ana.li@example.org")]
    c = score_document(TEXT, gold, gold * 2)
    assert c["EMAIL"].strict == 1 and c["ALL"].scores()["recall"] == 1.0


def test_mistral_zero_shot_parses_and_caches(tmp_path):
    from alias_pii.baselines import MistralZeroShot

    class FakeClient:
        calls = 0

        def complete(self, messages, model, temperature):
            FakeClient.calls += 1
            return (
                '```json\n{"entities": [{"label": "PERSON", "text": "Ana Li"},'
                ' {"label": "EMAIL", "text": "no@example.org"}, {"label": "X", "text": "y"}]}```'
            )

    detector = MistralZeroShot(client=FakeClient(), cache_dir=tmp_path)
    found = detector.detect(TEXT)
    assert [(e.type.value, e.text) for e in found] == [("PERSON", "Ana Li")]
    detector.detect(TEXT)
    assert FakeClient.calls == 1  # second answer from the cache
    assert MistralZeroShot.parse(TEXT, "not json") == []


def test_hybrid_keeps_context_labels_from_the_model_only():
    from alias_pii.baselines import HybridBaseline

    class FakeModel:
        def detect(self, text):
            return [entity("PERSON", "Ana Li", text), entity("EMAIL", "ana.li@example.org", text)]

    hybrid = HybridBaseline.__new__(HybridBaseline)
    hybrid.rules, hybrid.gliner = __import__("alias_pii.rules").rules.RuleDetector(), FakeModel()
    labels = sorted(e.type.value for e in hybrid.detect(TEXT))
    assert labels == ["EMAIL", "PERSON", "PHONE"]  # e-mail and phone from the rules, once each


def test_mistral_parse_whole_words_and_bad_items():
    from alias_pii.baselines import MistralZeroShot

    text = "Ana Li vit à Lille."
    raw = '{"entities": ["Ana", 3, {"label": "PERSON", "text": "Li"}]}'
    assert [(e.start, e.end) for e in MistralZeroShot.parse(text, raw)] == [(4, 6)]


def test_api_methods_refuse_real_data(tmp_path, monkeypatch):
    import pytest

    from alias_pii import benchmark

    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setattr("sys.argv", ["b", "--data", str(real), "--methods", "mistral"])
    with pytest.raises(SystemExit):
        benchmark.main()
