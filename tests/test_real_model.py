"""The bridge with the published model on ONNX Runtime, end to end, as `alias-pii serve` loads it.

Skipped unless ALIAS_REAL_MODEL=1: it downloads the model (about 600 MB) and runs it, which is
done on a GitHub machine (.github/workflows/real-model.yml), never on a laptop. Mistral is a
fake that records what it receives: nothing leaves for the real API.
"""

import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ALIAS_REAL_MODEL") != "1", reason="downloads and runs the published model"
)

NAME, EMAIL = "Jean Dupont", "jean.dupont@example.com"
IBAN = "FR76 3000 6000 0112 3456 7890 189"
TEXT = f"Bonjour, je suis {NAME}. Écrire à {EMAIL}, virement sur l'IBAN {IBAN}."


def test_the_published_model_masks_and_restores_through_the_bridge():
    import importlib.util

    import httpx
    from fastapi.testclient import TestClient

    from alias_pii import cli
    from alias_pii.bridge import create_bridge

    assert importlib.util.find_spec("torch") is None  # the serve extra runs without PyTorch
    received = []

    def mistral(request):
        body = json.loads(request.content)
        received.append(body)
        echo = body["messages"][-1]["content"]
        message = {"role": "assistant", "content": f"Reçu : {echo}"}
        return httpx.Response(200, json={"choices": [{"index": 0, "message": message}]})

    folder = cli.published_model()
    assert cli.published_model() == folder  # the second call reads the cache
    app = create_bridge(
        cli.model_detector(folder),
        api_key="k",
        transport=httpx.MockTransport(mistral),
        detector_name="rules+model",
    )
    client = TestClient(app, base_url="http://127.0.0.1:8001")
    assert client.get("/health").json()["detector"] == "rules+model"
    body = {"model": "m", "messages": [{"role": "user", "content": TEXT}]}
    streamed = client.post("/v1/chat/completions", json={**body, "stream": True})
    events = [
        json.loads(line[6:]) for line in streamed.text.split("\n") if line.startswith("data: {")
    ]
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in events)
    assert text == f"Reçu : {TEXT}"
    sent = json.dumps(received, ensure_ascii=False)
    for value in (NAME, EMAIL, IBAN):
        assert value not in sent, value
    assert "[PERSON_1]" in sent and "[EMAIL_1]" in sent and "[IBAN_1]" in sent
    answer = client.post("/v1/chat/completions", json=body).json()
    assert answer["choices"][0]["message"]["content"] == f"Reçu : {TEXT}"
