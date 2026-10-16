"""Documents written by an LLM around placeholders (dataset v0.3, docs/DATASET.md §10).

The grid generator assembles documents from phrase banks; its wording is ours. Here a language
model writes the whole document, with placeholders such as `{{PERSON_1}}` instead of every
personal value. The placeholders are then replaced by fake values from `IdentityFactory`, so the
spans are exact by construction. A document is rejected when a placeholder asked for is missing,
when the model invents one, or when the quality gates find a strict-format value (e-mail, phone,
IBAN, national ID) outside the placeholders.

Only the prompt leaves the machine: document type, domain, language and placeholder names. No
value, fake or real, is sent. Responses are cached on disk by a hash of model, prompt version
and messages, so a build can be resumed and rerun without new calls.

    uv run --group data python -m alias_pii.llm_writer --out data/llm --n 200 --seed 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from alias_pii import quality
from alias_pii.documents import DOC_TYPES, SPLITS, TEST_ONLY_TYPES, Document, Span
from alias_pii.identities import IdentityFactory

PROMPT_VERSION = "3"
DEFAULT_MODEL = "mistral-small-latest"
API_URL = "https://api.mistral.ai/v1/chat/completions"
PLACEHOLDER = re.compile(r"\{\{\s*([A-Z_]+?)_(\d)\s*\}\}")

DESCRIPTIONS = {
    "PERSON": "full name of a person",
    "ADDRESS": "postal address",
    "EMAIL": "personal e-mail address",
    "PHONE": "personal phone number",
    "IBAN": "bank account number (IBAN)",
    "NATIONAL_ID": "national identification number",
    "BIRTH_DATE": "date of birth",
    "IDENTIFIER": "customer, file or patient number",
}
STYLES = {
    "fr": ["formel", "administratif", "familier", "concis", "détaillé", "technique"],
    "en": ["formal", "administrative", "casual", "concise", "detailed", "technical"],
}
SYSTEM = (
    "You write realistic {language} documents for a dataset that trains a personal-data "
    "detector. Every piece of personal data must be written as one of the placeholders given, "
    "exactly as given (for example {{{{PERSON_1}}}}), never as a real or invented value. Use "
    "each placeholder at least once; you may repeat it. Do not create other placeholders. Do not "
    "write any other name, e-mail address, phone number, postal address, account number or ID "
    "number: refer to other people by their role and to organisations by a generic name. "
    "Only person placeholders may appear more than once; every other placeholder appears exactly "
    "once, for the value it names (a birth date placeholder is never a hire date). "
    "Each person placeholder is one person: never use the same one for two people (an employee "
    "and their manager); anyone else is named by role only (the manager, the adviser). Never "
    "leave a gap such as [Address] or <name>: when a value has no placeholder, leave that field "
    "out or describe it in words. "
    "Output only the document, without comments or Markdown fences."
)
# A gap the model left instead of a value, such as "[Employee's Address]" or "<bank name>".
TEMPLATE_GAP = re.compile(r"\[[A-Za-z][^\]\n]{2,60}\]|<[A-Za-z][^>\n]{2,40}>")
USER = (
    "Document type: {doc_type}. Domain: {domain}. Tone: {style}. Length: about {words} words.\n"
    "Placeholders:\n{placeholders}"
)


class Client(Protocol):
    def complete(self, messages: list[dict], model: str, temperature: float) -> str: ...


class MistralClient:
    """Chat completions over HTTPS, with backoff on rate limits (the free plan allows few calls
    per second). The key comes from `MISTRAL_API_KEY`, or a `.env` file, and is never logged."""

    def __init__(self, api_key: str | None = None, min_interval: float = 1.1, retries: int = 6):
        import httpx  # only needed when calling the API

        self.key = api_key or os.environ.get("MISTRAL_API_KEY") or _key_from_dotenv()
        if not self.key:
            raise RuntimeError("MISTRAL_API_KEY is not set (environment or .env)")
        self.http = httpx.Client(timeout=120)
        self.transport_error = httpx.TransportError
        self.min_interval, self.retries, self.last = min_interval, retries, 0.0

    def complete(self, messages: list[dict], model: str, temperature: float) -> str:
        body = {"model": model, "messages": messages, "temperature": temperature}
        for attempt in range(self.retries):
            time.sleep(max(0.0, self.min_interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                response = self.http.post(
                    API_URL, json=body, headers={"Authorization": f"Bearer {self.key}"}
                )
            except self.transport_error:  # timeout, connection reset: retry like a 5xx
                time.sleep(min(60, 2**attempt + random.random()))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(min(60, 2**attempt + random.random()))
                continue
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        raise RuntimeError(f"Mistral API: gave up after {self.retries} attempts")


def _key_from_dotenv(path: Path = Path(".env")) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "MISTRAL_API_KEY":
            return value.strip().strip("'\"") or None
    return None


class Cache:
    """One JSON file per request, named by the hash of model, prompt version and messages."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(model: str, messages: list[dict], temperature: float) -> str:
        payload = json.dumps([model, PROMPT_VERSION, temperature, messages], ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, key: str) -> str | None:
        path = self.directory / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8"))["content"] if path.is_file() else None

    def put(self, key: str, content: str) -> None:
        path = self.directory / f"{key}.json"
        path.write_text(json.dumps({"content": content}, ensure_ascii=False), encoding="utf-8")


def fill(text: str, values: dict[str, tuple[str, str]]) -> tuple[str, list[Span], list[str]]:
    """Replace every placeholder by its value. `values` maps `PERSON_1` to (value, label).
    Returns the text, the spans and the problems (missing or invented placeholders)."""
    problems: list[str] = []
    occurrences = Counter(f"{m.group(1)}_{m.group(2)}" for m in PLACEHOLDER.finditer(text))
    found = set(occurrences)
    problems += [f"{name}: placeholder repeated" for name, n in sorted(occurrences.items())
                 if n > 1 and not name.startswith("PERSON_")]  # fmt: skip
    problems += [f"{name}: placeholder missing" for name in sorted(set(values) - found)]
    problems += [f"{name}: placeholder invented" for name in sorted(found - set(values))]
    if problems:
        return text, [], problems
    out: list[str] = []
    spans: list[Span] = []
    position = cursor = 0
    for match in PLACEHOLDER.finditer(text):
        literal = text[cursor : match.start()]
        out.append(literal)
        position += len(literal)
        value, label = values[f"{match.group(1)}_{match.group(2)}"]
        spans.append(Span(position, position + len(value), label))
        out.append(value)
        position += len(value)
        cursor = match.end()
    out.append(text[cursor:])
    filled = "".join(out)
    if "{{" in filled or "}}" in filled:
        problems.append("TEXT: leftover braces")
    if TEMPLATE_GAP.search(filled):
        problems.append("TEXT: template gap left by the model")
    return filled, spans, problems


class LLMWriter:
    """Draws a request (type, domain, language, placeholders), asks the model, fills the values
    and checks the result. One fresh fake identity per document, as in the grid generator."""

    def __init__(self, split: str, client: Client, cache: Cache, seed: int = 0,
                 model: str = DEFAULT_MODEL, temperature: float = 0.9):  # fmt: skip
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}")
        self.split, self.client, self.cache = split, client, cache
        self.model, self.temperature = model, temperature
        self.rng = random.Random(f"llm-{seed}-{split}")
        self.doc_types = [t for t in DOC_TYPES if split == "test" or t not in TEST_ONLY_TYPES]

    def request(self) -> dict:
        rng = self.rng
        doc_type = rng.choice(self.doc_types)
        spec = DOC_TYPES[doc_type]
        language = rng.choice(["fr", "en"])
        optional = spec["optional"]  # some types have fewer than three optional fields
        labels = list(spec["fields"]) + rng.sample(
            optional, rng.randint(min(1, len(optional)), min(3, len(optional)))
        )
        names = [f"{label}_1" for label in labels]
        if rng.random() < 0.4:
            names.append("PERSON_2")  # a second person: colleague, relative, adviser
        return dict(
            doc_type=doc_type,
            domain=rng.choice(spec["domains"]),
            language=language,
            locale="fr_FR" if language == "fr" else rng.choice(["en_US", "en_GB"]),
            style=rng.choice(STYLES[language]),
            words=rng.choice([80, 120, 180, 250]),
            placeholders=names,
        )

    def messages(self, request: dict) -> list[dict]:
        listing = "\n".join(
            f"- {{{{{name}}}}}: {DESCRIPTIONS[name.rsplit('_', 1)[0]]}"
            for name in request["placeholders"]
        )
        language = {"fr": "French", "en": "English"}[request["language"]]
        return [
            {"role": "system", "content": SYSTEM.format(language=language)},
            {"role": "user", "content": USER.format(
                doc_type=request["doc_type"].replace("_", " "), domain=request["domain"],
                style=request["style"], words=request["words"], placeholders=listing)},
        ]  # fmt: skip

    def values(self, request: dict) -> tuple[dict[str, tuple[str, str]], str]:
        factory = IdentityFactory(request["locale"], self.rng)
        main, other = factory.identity(), factory.identity()
        drawn = {
            "PERSON": lambda i: factory.name_as(i),
            "ADDRESS": lambda i: factory.address_as(i, multiline=False),
            "EMAIL": lambda i: i.email,
            "PHONE": lambda i: factory.phone_as(i),
            "IBAN": lambda i: factory.iban_as(i),
            "NATIONAL_ID": lambda i: factory.national_id_as(i),
            "BIRTH_DATE": lambda i: factory.date_as(i.birth_date),
            "IDENTIFIER": lambda i: i.identifier,
        }
        values = {}
        for name in request["placeholders"]:
            label, index = name.rsplit("_", 1)
            values[name] = (drawn[label](main if index == "1" else other), label)
        return values, main.person.origin

    def document(self) -> tuple[Document | None, list[str]]:
        request = self.request()
        messages = self.messages(request)
        key = Cache.key(self.model, messages, self.temperature)
        raw = self.cache.get(key)
        if raw is None:
            raw = self.client.complete(messages, self.model, self.temperature)
            self.cache.put(key, raw)
        values, origin = self.values(request)
        text, spans, problems = fill(raw.strip(), values)
        if not problems:
            problems = quality.check(text, spans)
        if problems:
            return None, problems
        return Document(
            text=text,
            spans=spans,
            language=request["language"],
            locale=request["locale"],
            doc_type=request["doc_type"],
            domain=request["domain"],
            layout="llm",
            split=self.split,
            source=f"llm-v0.3:{self.model}:prompt-{PROMPT_VERSION}",
            person_origin=origin,
        ), []


def build_split(writer: LLMWriter, n: int) -> tuple[list[Document], Counter, int]:
    """`n` documents that pass the gates, rejections by reason, near duplicates removed."""
    kept: list[Document] = []
    keys: set[str] = set()
    rejected: Counter = Counter()
    duplicates = attempts = 0
    while len(kept) < n:
        attempts += 1
        if attempts > 3 * n + 20:
            raise RuntimeError(f"{writer.split}: too many rejected documents: {dict(rejected)}")
        document, problems = writer.document()
        if document is None:
            rejected.update(quality.summarise([problems]))
            continue
        key = quality.near_duplicate_key(document.text)
        if key in keys:
            duplicates += 1
            continue
        keys.add(key)
        kept.append(document)
    return kept, rejected, duplicates


def main() -> None:
    parser = argparse.ArgumentParser(description="Write Alias documents with Mistral.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("data/cache/mistral"))
    parser.add_argument("--n", type=int, default=200, help="documents per split (train gets 8x)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    client, cache = MistralClient(), Cache(args.cache)
    sizes = {"train": 8 * args.n, "validation": args.n, "test": args.n}
    for split in SPLITS:
        writer = LLMWriter(split, client, cache, args.seed, args.model)
        documents, rejected, duplicates = build_split(writer, sizes[split])
        with (args.out / f"{split}.jsonl").open("w", encoding="utf-8") as out:
            for document in documents:
                out.write(json.dumps(asdict(document), ensure_ascii=False) + "\n")
        print(f"{split}: {len(documents)} kept, {sum(rejected.values())} rejected "
              f"{dict(rejected)}, {duplicates} duplicates")  # fmt: skip


if __name__ == "__main__":
    main()
