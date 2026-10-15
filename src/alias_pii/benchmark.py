"""Benchmark harness: every detector on the same documents, the same measures (README, evaluation
plan).

    uv run --group data python -m alias_pii.benchmark --data data/synthetic --split test \\
        --methods rules --out reports

Measures, per label, per language and per source:
- **strict**: a prediction counts when its label and both boundaries match a gold span;
- **overlap**: same label and at least one character in common (boundary errors are forgiven);
- **leak rate**: share of gold values still readable once the predicted spans are masked, exactly
  or without separators (`masking.find_leaks`): the measure that matters for Alias;
- **latency**: milliseconds per 1,000 characters on this machine's CPU.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from alias_pii.entities import Entity, EntityType
from alias_pii.masking import find_leaks

LABELS = [t.value for t in EntityType]


class Detector(Protocol):
    def detect(self, text: str) -> list[Entity]: ...


@dataclass
class Counts:
    gold: int = 0
    predicted: int = 0
    strict: int = 0  # true positives, exact boundaries
    overlap_gold: int = 0  # gold spans hit by a same-label prediction
    overlap_predicted: int = 0  # predictions that hit a same-label gold span
    leaked: int = 0

    def add(self, other: Counts) -> None:
        for name in vars(self):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def scores(self) -> dict[str, float | int]:
        def ratio(a: int, b: int) -> float:
            return a / b if b else 0.0

        p, r = ratio(self.strict, self.predicted), ratio(self.strict, self.gold)
        po, ro = ratio(self.overlap_predicted, self.predicted), ratio(self.overlap_gold, self.gold)
        return {
            "gold": self.gold,
            "precision": p,
            "recall": r,
            "f1": ratio(2 * p * r, p + r),
            "overlap_precision": po,
            "overlap_recall": ro,
            "leak_rate": ratio(self.leaked, self.gold),
        }


@dataclass
class Result:
    method: str
    documents: int = 0
    characters: int = 0
    seconds: float = 0.0
    by: dict[str, dict[str, Counts]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(Counts))
    )

    def summary(self) -> dict:
        return {
            "method": self.method,
            "documents": self.documents,
            "ms_per_1000_chars": 1000 * self.seconds / max(1, self.characters) * 1000,
            "by": {
                axis: {value: counts.scores() for value, counts in sorted(groups.items())}
                for axis, groups in self.by.items()
            },
        }


def _mask(text: str, entities: Iterable[Entity]) -> str:
    out, cursor = [], 0
    for e in sorted(entities, key=lambda e: e.start):
        if e.start >= cursor:
            out += [text[cursor : e.start], f"[{e.type.value}]"]
            cursor = e.end
        elif e.end > cursor:  # overlapping predictions: mask the union
            cursor = e.end
    return "".join(out) + text[cursor:]


def score_document(text: str, gold: list[Entity], predicted: list[Entity]) -> dict[str, Counts]:
    """Counts per label for one document (key `ALL` holds the total)."""
    counts: dict[str, Counts] = defaultdict(Counts)
    # the same label on the same span counts once (Presidio can return US_SSN and UK_NINO there)
    predicted = list({(p.type, p.start, p.end): p for p in predicted}.values())
    exact = {(e.type, e.start, e.end) for e in gold}
    leaks = {(e.start, e.end) for e in find_leaks(_mask(text, predicted), gold)}
    for g in gold:
        c = counts[g.type.value]
        c.gold += 1
        c.overlap_gold += any(p.type == g.type and p.overlaps(g) for p in predicted)
        c.leaked += (g.start, g.end) in leaks
    for p in predicted:
        c = counts[p.type.value]
        c.predicted += 1
        c.strict += (p.type, p.start, p.end) in exact
        c.overlap_predicted += any(g.type == p.type and g.overlaps(p) for g in gold)
    total = Counts()
    for c in counts.values():
        total.add(c)
    counts["ALL"] = total
    return counts


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines]


def gold_entities(document: dict) -> list[Entity]:
    text = document["text"]
    return [
        Entity(EntityType(s["label"]), s["start"], s["end"], text[s["start"] : s["end"]])
        for s in document["spans"]
    ]


def run(method: str, detector: Detector, documents: list[dict]) -> Result:
    result = Result(method)
    for document in documents:
        text = document["text"]
        start = time.perf_counter()
        predicted = detector.detect(text)
        result.seconds += time.perf_counter() - start
        result.documents += 1
        result.characters += len(text)
        counts = score_document(text, gold_entities(document), predicted)
        source = document.get("source", "").split(":")[0]
        for axis, value in (("all", "all"), ("language", document["language"]), ("source", source)):
            for label, c in counts.items():
                key = value if label == "ALL" else f"{value}/{label}"
                result.by[axis if label == "ALL" else f"{axis}_label"][key].add(c)
    return result


def report(summaries: list[dict], split: str, n: int) -> str:
    """Markdown tables: overall, per label, per language, per source."""
    lines = [f"# Benchmark on `{split}` ({n} documents)", "",
             "Strict: label and both boundaries; overlap: same label, any common character; leak "
             "rate: gold values still readable after masking.", "",
             "| Method | Precision | Recall | F1 | Overlap recall | Leak rate | ms / 1,000 chars |",
             "|---|---|---|---|---|---|---|"]  # fmt: skip
    for s in summaries:
        a = s["by"]["all"]["all"]
        lines.append(f"| {s['method']} | {a['precision']:.3f} | {a['recall']:.3f} | {a['f1']:.3f} "
                     f"| {a['overlap_recall']:.3f} | {a['leak_rate']:.1%} | "
                     f"{s['ms_per_1000_chars']:.2f} |")  # fmt: skip
    for axis in ("all_label", "language", "source"):
        lines += ["", f"## By {axis.replace('all_label', 'label')} (precision / recall / leak)", "",
                  "| | " + " | ".join(s["method"] for s in summaries) + " |",
                  "|---|" + "---|" * len(summaries)]  # fmt: skip
        keys = sorted({k for s in summaries for k in s["by"].get(axis, {})})
        for key in keys:
            cells = []
            for s in summaries:
                c = s["by"].get(axis, {}).get(key)
                cells.append(
                    f"{c['precision']:.2f} / {c['recall']:.2f} / {c['leak_rate']:.0%}" if c else "-"
                )
            lines.append(f"| {key.removeprefix('all/')} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(methods: dict[str, Callable[[], Detector]] | None = None) -> None:
    from alias_pii.baselines import METHODS

    methods = methods or METHODS
    parser = argparse.ArgumentParser(description="Benchmark Alias detectors.")
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--split", default="test")
    parser.add_argument("--methods", default="rules", help=f"comma list of {sorted(methods)}")
    parser.add_argument("--limit", type=int, default=0, help="first N documents only")
    parser.add_argument("--out", type=Path, default=Path("reports"))
    args = parser.parse_args()
    documents = load(args.data / f"{args.split}.jsonl")
    if args.limit:
        documents = documents[: args.limit]
    summaries = []
    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.methods.split(","):
        summaries.append(run(name, methods[name](), documents).summary())
        print(f"{name}: done")
        # written after each method, so a failing baseline does not lose the others
        (args.out / f"benchmark-{args.split}.json").write_text(json.dumps(summaries, indent=1))
        (args.out / f"benchmark-{args.split}.md").write_text(
            report(summaries, args.split, len(documents)), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
