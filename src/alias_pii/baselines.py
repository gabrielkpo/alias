"""Baselines for the benchmark (README, step 3). Each one exposes `detect(text) -> list[Entity]`
with Alias labels; labels a baseline cannot produce are simply missing from its predictions.

Heavy dependencies are imported when a baseline is built, never at import time: the `bench`
dependency group installs them (`uv sync --group bench`), the models are downloaded once.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from alias_pii.entities import Entity, EntityType, resolve_overlaps
from alias_pii.rules import RuleDetector

_FRENCH = re.compile(r"\b(le|la|les|des|du|est|et|une|pour|vous|nous|dans|avec)\b", re.I)
_ENGLISH = re.compile(r"\b(the|and|is|of|to|for|you|we|in|with|your|this)\b", re.I)


def language_of(text: str) -> str:
    """`fr` or `en` from stop-word counts: enough to pick a spaCy model per document."""
    return "fr" if len(_FRENCH.findall(text)) >= len(_ENGLISH.findall(text)) else "en"


def _chunks(text: str, size: int = 1200) -> list[tuple[int, str]]:
    """Pieces of at most about `size` characters cut at line ends, with their offsets: GLiNER
    reads a few hundred tokens at a time."""
    pieces, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start, end)
            if cut <= start:
                cut = text.rfind(" ", start, end)
            end = cut + 1 if cut > start else end
        pieces.append((start, text[start:end]))
        start = end
    return pieces


class PresidioBaseline:
    """Microsoft Presidio with spaCy `fr_core_news_lg` and `en_core_web_lg`. Presidio has no
    address or birth-date recogniser: `LOCATION` and `DATE_TIME` are not mapped (mapping every
    date to `BIRTH_DATE` would turn each invoice date into a false positive)."""

    MAP = {"PERSON": "PERSON", "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "PHONE",
           "IBAN_CODE": "IBAN", "US_SSN": "NATIONAL_ID", "UK_NINO": "NATIONAL_ID",
           "FR_NIR": "NATIONAL_ID"}  # fmt: skip

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "fr", "model_name": "fr_core_news_lg"},
                       {"lang_code": "en", "model_name": "en_core_web_lg"}],
        })  # fmt: skip
        self.engine = AnalyzerEngine(
            nlp_engine=provider.create_engine(), supported_languages=["fr", "en"]
        )

    def detect(self, text: str) -> list[Entity]:
        found = self.engine.analyze(text=text, language=language_of(text))
        return [
            Entity(EntityType(self.MAP[r.entity_type]), r.start, r.end, text[r.start : r.end],
                   r.score, "presidio")
            for r in found
            if r.entity_type in self.MAP
        ]  # fmt: skip


class GlinerBaseline:
    """GLiNER multi PII (`urchade/gliner_multi_pii-v1`), zero-shot with natural-language labels."""

    LABELS = {"person": "PERSON", "address": "ADDRESS", "email": "EMAIL",
              "phone number": "PHONE", "iban": "IBAN",
              "national identification number": "NATIONAL_ID", "date of birth": "BIRTH_DATE",
              "customer or file number": "IDENTIFIER"}  # fmt: skip

    def __init__(self, model: str = "urchade/gliner_multi_pii-v1", threshold: float = 0.5):
        from gliner import GLiNER

        self.model = GLiNER.from_pretrained(model)
        self.threshold = threshold

    def detect(self, text: str) -> list[Entity]:
        entities = []
        for offset, piece in _chunks(text):
            for e in self.model.predict_entities(piece, list(self.LABELS), self.threshold):
                start, end = offset + e["start"], offset + e["end"]
                entities.append(Entity(EntityType(self.LABELS[e["label"]]), start, end,
                                       text[start:end], e["score"], "gliner"))  # fmt: skip
        return entities


class HybridBaseline:
    """Rules for the formats they validate, GLiNER for what needs context (names, addresses,
    birth dates); overlaps merged as in masking. Tests the complementarity measured in step 3:
    GLiNER misses most IBANs and national IDs, which the rules find."""

    CONTEXT = {EntityType.PERSON, EntityType.ADDRESS, EntityType.BIRTH_DATE}

    def __init__(self) -> None:
        self.rules, self.gliner = RuleDetector(), GlinerBaseline()

    def detect(self, text: str) -> list[Entity]:
        model = [e for e in self.gliner.detect(text) if e.type in self.CONTEXT]
        return resolve_overlaps(self.rules.detect(text) + model)


ZERO_SHOT_PROMPT = (
    "List every piece of personal data in the document below. Labels: PERSON (a person's name), "
    "ADDRESS (a person's postal address), EMAIL, PHONE (a person's phone number), IBAN, "
    "NATIONAL_ID (NIR, SSN, NINO), BIRTH_DATE, IDENTIFIER (a customer, file or patient number "
    "of a person). Company names, company addresses, switchboards and invoice or order numbers "
    "are not personal data. Answer with JSON only: "
    '{"entities": [{"label": "...", "text": "exact substring of the document"}]}.'
    "\n\nDocument:\n"
)


class MistralZeroShot:
    """Mistral asked to list the values of each label (no training). Spans are every occurrence of
    each returned value in the document; values not found verbatim are dropped. Only synthetic or
    public benchmark documents are sent, never real ones. Answers are cached on disk."""

    def __init__(
        self, model: str = "mistral-small-latest", client=None, cache_dir: Path | None = None
    ):
        from alias_pii.llm_writer import Cache, MistralClient

        self.model = model
        self.client = client or MistralClient()
        self.cache = Cache(cache_dir or Path("data/cache/mistral-zero-shot"))

    def detect(self, text: str) -> list[Entity]:
        messages = [{"role": "user", "content": ZERO_SHOT_PROMPT + text}]
        key = self.cache.key(self.model, messages, 0.0)
        raw = self.cache.get(key)
        if raw is None:
            raw = self.client.complete(messages, self.model, 0.0)
            self.cache.put(key, raw)
        return self.parse(text, raw)

    @staticmethod
    def parse(text: str, raw: str) -> list[Entity]:
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            items = json.loads(raw).get("entities", [])
        except (json.JSONDecodeError, AttributeError):
            return []
        entities = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            label, value = item.get("label"), str(item.get("text") or "").strip()
            if label not in EntityType.__members__ or not value:
                continue
            # whole occurrences only: "Li" must not label the start of "Lille"
            for match in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", text):
                entities.append(Entity(EntityType(label), match.start(), match.end(), value,
                                       1.0, "mistral"))  # fmt: skip
        return resolve_overlaps(entities)


# Methods that send document text to a third-party API: never run on real documents.
API_METHODS = {"mistral"}

METHODS: dict[str, Callable[[], object]] = {
    "rules": RuleDetector,
    "presidio": PresidioBaseline,
    "gliner": GlinerBaseline,
    "hybrid": HybridBaseline,
    "mistral": MistralZeroShot,
}
