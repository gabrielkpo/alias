"""A real measure of Alias Bridge against the Mistral API (bridge plan, step 5).

Fictitious documents from the grid generator (validation split) go through the bridge, with the
published model, to the real Mistral API, and the run reports counts only, never a text:

- leaks: personal values of the documents found in what Mistral received;
- aliases: those sent, those Mistral kept in its answer, those the bridge put back;
- answers that still hold an alias of their request after restoring;
- tokens (and a cost, given the prices), and the time the bridge adds to Mistral's.

It runs on a GitHub machine (.github/workflows/bridge-measure.yml, by hand), with the key from
MISTRAL_API_KEY, and stops before a token budget is passed.

    python -m alias_pii.measure_bridge --n 50 --out reports/bridge-measure.json
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import statistics
import time
from pathlib import Path

import httpx

from alias_pii.masking import ALIAS_PATTERN

PROMPTS = {
    "fr": "Résume ce document en quelques phrases, en reprenant les personnes, adresses, "
    "numéros et dates qu'il cite.",
    "en": "Summarise this document in a few sentences, keeping the people, addresses, numbers "
    "and dates it mentions.",
}


class Recorder(httpx.AsyncBaseTransport):
    """Passes requests to the real transport and keeps what was sent and answered, for the
    counts (it lives in this process only and is never written out)."""

    def __init__(self, transport: httpx.AsyncBaseTransport):
        self.transport = transport
        self.sent: list[str] = []
        self.answers: list[dict] = []
        self.seconds: list[float] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        start = time.perf_counter()
        response = await self.transport.handle_async_request(request)
        await response.aread()
        self.seconds.append(time.perf_counter() - start)
        self.sent.append(request.content.decode("utf-8", "replace"))
        try:
            self.answers.append(json.loads(response.content))
        except ValueError:
            self.answers.append({})
        return httpx.Response(
            response.status_code, headers=response.headers, content=response.content
        )


def aliases(text: str) -> set[str]:
    return {f"[{m.group(1).upper()}_{int(m.group(2))}]" for m in ALIAS_PATTERN.finditer(text)}


def answer_text(data: dict) -> str:
    choices = data.get("choices") or [{}]
    content = (choices[0].get("message") or {}).get("content")
    return content if isinstance(content, str) else ""


def measure(documents, detector, transport, model: str, max_tokens: int, budget: int) -> dict:
    """Send each document through the bridge; counts only."""
    from fastapi.testclient import TestClient

    from alias_pii.bridge import create_bridge

    recorder = Recorder(transport)
    token = secrets.token_urlsafe(32)
    key = os.environ.get("MISTRAL_API_KEY") or "unset"
    app = create_bridge(
        detector, api_key=key, transport=recorder, detector_name="measure", local_token=token
    )
    client = TestClient(app, base_url="http://127.0.0.1:8001")
    counts = dict.fromkeys(
        [
            "documents",
            "errors",
            "values",
            "values_leaked",
            "aliases_sent",
            "aliases_kept",
            "aliases_restored",
            "answers_with_alias_left",
            "tokens_in",
            "tokens_out",
        ],
        0,
    )
    overhead, models = [], set()
    for document in documents:
        if counts["tokens_in"] + counts["tokens_out"] >= budget:
            break
        prompt = PROMPTS.get(document.language, PROMPTS["fr"])
        body = {
            "model": model,
            "messages": [{"role": "user", "content": f"{prompt}\n\n{document.text}"}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        start = time.perf_counter()
        response = client.post(
            "/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        took = time.perf_counter() - start
        counts["documents"] += 1
        if response.status_code != 200 or not recorder.sent:
            counts["errors"] += 1
            continue
        raw = recorder.answers[-1]
        messages = json.loads(recorder.sent[-1])["messages"]
        sent = "\n".join(m["content"] for m in messages if isinstance(m.get("content"), str))
        overhead.append(took - recorder.seconds[-1])
        values = {document.text[s.start : s.end] for s in document.spans}
        counts["values"] += len(values)
        counts["values_leaked"] += sum(value in sent for value in values)
        given = aliases(sent)
        kept = given & aliases(answer_text(raw))
        counts["aliases_sent"] += len(given)
        counts["aliases_kept"] += len(kept)
        counts["aliases_restored"] += int(response.headers.get("X-Alias-Restored", 0))
        counts["answers_with_alias_left"] += bool(given & aliases(answer_text(response.json())))
        usage = raw.get("usage") or {}
        counts["tokens_in"] += usage.get("prompt_tokens", 0)
        counts["tokens_out"] += usage.get("completion_tokens", 0)
        models.add(str(raw.get("model")))
    sent_docs = counts["documents"] - counts["errors"]
    return {
        **counts,
        "models": sorted(models),
        "leak_rate": counts["values_leaked"] / counts["values"] if counts["values"] else None,
        "kept_rate": counts["aliases_kept"] / counts["aliases_sent"]
        if counts["aliases_sent"]
        else None,
        "median_overhead_seconds": statistics.median(overhead) if overhead else None,
        "answers": sent_docs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure Alias Bridge against the Mistral API.")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model", default="mistral-small-latest")
    parser.add_argument("--max-tokens", type=int, default=300, help="per answer")
    parser.add_argument("--budget", type=int, default=150_000, help="tokens for the whole run")
    parser.add_argument("--price-in", type=float, default=0.0, help="per million input tokens")
    parser.add_argument("--price-out", type=float, default=0.0, help="per million output tokens")
    parser.add_argument("--out", type=Path, default=Path("reports/bridge-measure.json"))
    args = parser.parse_args()
    if not os.environ.get("MISTRAL_API_KEY"):
        raise SystemExit("MISTRAL_API_KEY is not set")

    from alias_pii import cli
    from alias_pii.documents import generate

    documents = generate(args.n, "validation", args.seed)
    detector = cli.model_detector(cli.published_model())
    transport = httpx.AsyncHTTPTransport(retries=2)
    report = measure(documents, detector, transport, args.model, args.max_tokens, args.budget)
    report["cost"] = (
        report["tokens_in"] * args.price_in + report["tokens_out"] * args.price_out
    ) / 1_000_000
    report["settings"] = {
        k: getattr(args, k) for k in ("n", "seed", "model", "max_tokens", "budget")
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
