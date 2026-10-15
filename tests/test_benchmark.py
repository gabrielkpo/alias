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
