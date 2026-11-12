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


def test_the_measure_works_over_real_connections():
    """Over a real socket, as the real API: connections kept open between requests (the whole
    run must share one event loop) and gzip-encoded answers (the recorder must not decode them
    twice)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Mistral(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive, as the real API

        def do_POST(self):
            import gzip

            self.rfile.read(int(self.headers["content-length"]))
            body = gzip.compress(
                json.dumps(
                    {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}}
                ).encode()
            )
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-encoding", "gzip")  # as the real API
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Mistral)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        documents = generate(3, "validation", 0)
        upstream = f"http://127.0.0.1:{server.server_port}"
        transport = httpx.AsyncHTTPTransport()
        detector = Known(documents, "")
        report = measure(documents, detector, transport, "m", 50, 10_000, upstream=upstream)
        assert report["documents"] == 3 and report["errors"] == 0
    finally:
        server.shutdown()
