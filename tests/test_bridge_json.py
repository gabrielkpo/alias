"""A body nested too deep to read is refused (400), not a crash (500), and so is such an answer
from the provider (502). Fictitious values only."""

import httpx
from fastapi.testclient import TestClient

from alias_pii.bridge import create_bridge
from alias_pii.rules import RuleDetector

LOCAL = "http://127.0.0.1:8001"
DEEP = "[" * 100_000


def test_a_request_nested_too_deep_is_refused():
    app = create_bridge(RuleDetector(), api_key="k", transport=httpx.MockTransport(lambda r: None))
    client = TestClient(app, base_url=LOCAL)
    answer = client.post(
        "/v1/chat/completions", content=DEEP, headers={"Content-Type": "application/json"}
    )
    assert answer.status_code == 400


def test_an_answer_nested_too_deep_is_a_gateway_error():
    def provider(request):
        return httpx.Response(200, content=DEEP, headers={"Content-Type": "application/json"})

    app = create_bridge(RuleDetector(), api_key="k", transport=httpx.MockTransport(provider))
    body = {"model": "m", "messages": [{"role": "user", "content": "Bonjour."}]}
    assert (
        TestClient(app, base_url=LOCAL).post("/v1/chat/completions", json=body).status_code == 502
    )
