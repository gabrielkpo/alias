import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from alias_pii.app import create_app, load_detector  # noqa: E402

TEXT = (
    "Écrire à jean.dupont@example.com, IBAN FR76 3000 6000 0112 3456 7890 189, "
    "ou jean.dupont@example.com."
)


@pytest.fixture
def client():
    detector, name = load_detector(None)
    return TestClient(create_app(detector, name, max_chars=500))


def test_mask_returns_aliases_positions_and_report(client):
    response = client.post("/api/mask", json={"text": TEXT})
    assert response.status_code == 200
    body = response.json()
    assert body["masked"] == "Écrire à [EMAIL_1], IBAN [IBAN_1], ou [EMAIL_1]."
    assert [(e["type"], e["alias"]) for e in body["entities"]] == [
        ("EMAIL", "[EMAIL_1]"),
        ("IBAN", "[IBAN_1]"),
        ("EMAIL", "[EMAIL_1]"),
    ]
    first = body["entities"][0]
    assert TEXT[first["start"] : first["end"]] == "jean.dupont@example.com"
    assert body["report"] == {"EMAIL": 2, "IBAN": 1, "total": 3}


def test_response_never_holds_the_values(client):
    raw = client.post("/api/mask", json={"text": TEXT}).text
    assert "jean.dupont" not in raw and "3000 6000" not in raw


def test_each_request_starts_a_new_alias_table(client):
    client.post("/api/mask", json={"text": "a@example.com b@example.com"})
    body = client.post("/api/mask", json={"text": "b@example.com"}).json()
    assert body["masked"] == "[EMAIL_1]"


def test_too_long_is_refused(client):
    assert client.post("/api/mask", json={"text": "x" * 501}).status_code == 413
    big = client.post(
        "/api/mask",
        content=b'{"text": "' + b"x" * 5000 + b'"}',
        headers={"content-type": "application/json"},
    )
    assert big.status_code == 413


def test_health_and_security_headers(client):
    response = client.get("/health")
    assert response.json()["detector"] == "rules"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in response.headers


def test_no_docs_that_load_a_cdn(client):
    assert client.get("/docs").status_code == 404


def test_page_and_its_files_are_served_locally(client):
    page = client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert "/static/app.js" in page.text and "http" not in page.text.split("<body>")[0]
    script = client.get("/static/app.js")
    assert script.status_code == 200 and "innerHTML" not in script.text
    assert client.get("/static/style.css").status_code == 200
    assert "default-src 'self'" in page.headers["content-security-policy"]


def test_demo_flag_reaches_the_page(client):
    assert client.get("/health").json()["demo"] is False
    detector, name = load_detector(None)
    demo = TestClient(create_app(detector, name, demo=True))
    assert demo.get("/health").json()["demo"] is True


def test_a_chunked_body_too_large_is_refused(client):
    """Without a Content-Length the size check on the header cannot apply: the body is counted
    as it arrives and refused past the limit."""

    def chunks():  # a short text, a long unknown field: only the byte count can refuse it
        yield b'{"text": "x", "pad": "'
        for _ in range(10):
            yield b"x" * 1000
        yield b'"}'

    response = client.post(
        "/api/mask", content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
