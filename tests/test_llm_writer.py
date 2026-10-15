import re

import pytest

from alias_pii.llm_writer import Cache, LLMWriter, build_split, fill


class FakeClient:
    """Writes a document that uses every placeholder listed in the prompt."""

    def __init__(self, extra: str = ""):
        self.calls = 0
        self.extra = extra

    def complete(self, messages, model, temperature):
        self.calls += 1
        names = re.findall(r"\{\{(\w+)\}\}", messages[1]["content"])
        lines = [f"Ligne {i} : {{{{{name}}}}}." for i, name in enumerate(names)]
        return "\n".join(["Objet : dossier", *lines, "Merci de votre retour.", self.extra])


def test_fill_records_exact_spans():
    text, spans, problems = fill(
        "A {{PERSON_1}} et {{ PERSON_1 }}.", {"PERSON_1": ("Ana Li", "PERSON")}
    )
    assert problems == []
    assert text == "A Ana Li et Ana Li."
    assert [text[s.start : s.end] for s in spans] == ["Ana Li", "Ana Li"]


def test_fill_rejects_missing_and_invented_placeholders():
    _, _, problems = fill("{{EMAIL_1}}", {"PERSON_1": ("Ana Li", "PERSON")})
    assert "PERSON_1: placeholder missing" in problems
    assert "EMAIL_1: placeholder invented" in problems


def test_writer_builds_checked_documents_and_uses_cache(tmp_path):
    client = FakeClient()
    docs, rejected, _ = build_split(LLMWriter("train", client, Cache(tmp_path), seed=1), 20)
    assert len(docs) == 20 and not rejected
    for doc in docs:
        assert "{{" not in doc.text
        assert doc.source.startswith("llm-v0.3:")
        assert all(doc.text[s.start : s.end].strip() for s in doc.spans)
    calls = client.calls
    build_split(LLMWriter("train", client, Cache(tmp_path), seed=1), 20)
    assert client.calls == calls  # every response came from the cache


def test_leak_outside_placeholders_is_rejected(tmp_path):
    writer = LLMWriter(
        "validation", FakeClient(extra="Contact : jean.dupont@example.org"), Cache(tmp_path)
    )
    document, problems = writer.document()
    assert document is None
    assert any("outside the labels" in p for p in problems)


def test_unknown_split():
    with pytest.raises(ValueError):
        LLMWriter("dev", FakeClient(), None)
