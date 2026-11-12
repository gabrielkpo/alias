"""The bridge measure, run against a fake Mistral: counts only, no text in the report."""

import json

import httpx
import pytest

pytest.importorskip("faker")
pytest.importorskip("fastapi")

from alias_pii.documents import generate  # noqa: E402
from alias_pii.entities import Entity, EntityType  # noqa: E402
from alias_pii.measure_bridge import aliases, measure  # noqa: E402


class Known:
    """Finds exactly the values of the documents, plus one it misses on purpose."""

    def __init__(self, documents, missed):
        self.values = {d.text[s.start : s.end] for d in documents for s in d.spans} - {missed}

    def detect(self, text):
        found = []
        for value in self.values:
            start = text.find(value)
            if start >= 0:
                found.append(Entity(EntityType.PERSON, start, start + len(value), value))
        return found


def test_the_measure_counts_leaks_aliases_and_tokens_without_text():
    documents = generate(3, "validation", 0)
    missed = documents[0].text[documents[0].spans[0].start : documents[0].spans[0].end]

    def mistral(request):
        text = json.loads(request.content)["messages"][-1]["content"]
        first = sorted(aliases(text))[:1]
        message = {"role": "assistant", "content": f"Résumé : {' '.join(first)}"}
        usage = {"prompt_tokens": 100, "completion_tokens": 20}
        body = {"model": "fake-2026", "choices": [{"index": 0, "message": message}], "usage": usage}
        return httpx.Response(200, json=body)

    detector = Known(documents, missed)
    report = measure(documents, detector, httpx.MockTransport(mistral), "m", 50, budget=10_000)
    assert report["documents"] == 3 and report["errors"] == 0
    assert report["values_leaked"] >= 1  # the value the detector missed
    assert report["aliases_kept"] == 3 and report["aliases_restored"] == 3
    assert report["answers_with_alias_left"] == 0
    assert (report["tokens_in"], report["tokens_out"]) == (300, 60)
    assert report["models"] == ["fake-2026"]
    serialized = json.dumps(report)
    for document in documents:
        for span in document.spans:
            assert document.text[span.start : span.end] not in serialized


def test_the_measure_stops_at_its_token_budget():
    documents = generate(5, "validation", 0)

    def mistral(request):
        message = {"role": "assistant", "content": "ok"}
        usage = {"prompt_tokens": 600, "completion_tokens": 0}
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": usage})

    report = measure(documents, Known(documents, ""), httpx.MockTransport(mistral), "m", 50, 1000)
    assert report["documents"] == 2
