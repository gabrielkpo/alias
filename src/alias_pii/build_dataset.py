"""Build the synthetic dataset and its datasheet (docs/DATASET.md §8 and §9).

    uv run --group data python -m alias_pii.build_dataset --out data/synthetic \\
        --train 30000 --validation 3000 --test 3000 --seed 0

Writes `train.jsonl`, `validation.jsonl`, `test.jsonl` and `DATASHEET.md` in `--out`. Every
document goes through the quality gates; rejected and duplicate documents are counted, not kept.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from alias_pii import quality
from alias_pii.documents import LABELS, SPLITS, Document, GridGenerator

VERSION = "0.2"


def build_split(split: str, n: int, seed: int) -> tuple[list[Document], Counter, int]:
    """`n` documents of a split that pass every gate, the rejections by reason, and the number of
    near duplicates removed."""
    generator = GridGenerator(split, seed)
    kept: list[Document] = []
    keys: set[str] = set()
    rejected: Counter = Counter()
    duplicates = attempts = 0
    while len(kept) < n:
        attempts += 1
        if attempts > 20 * n + 100:
            raise RuntimeError(f"{split}: too many rejected documents: {dict(rejected)}")
        document = generator.document()
        problems = quality.check(document.text, document.spans, document.negatives)
        if problems:
            rejected.update(quality.summarise([problems]))
            continue
        key = quality.near_duplicate_key(document.text)
        if key in keys:
            duplicates += 1
            continue
        keys.add(key)
        generator.balancer.record(document.spans)
        kept.append(document)
    return kept, rejected, duplicates


def write_jsonl(documents: list[Document], path: Path) -> None:
    with path.open("w", encoding="utf-8") as out:
        for document in documents:
            out.write(json.dumps(asdict(document), ensure_ascii=False) + "\n")


def datasheet(splits: dict, seed: int) -> str:
    """Markdown datasheet: composition per split and per axis, and quality-gate results."""
    lines = [
        f"# Alias synthetic dataset, version {VERSION}",
        "",
        f"Generated on {datetime.now(UTC):%Y-%m-%d} from seed {seed} by `alias_pii.build_dataset`.",
        "Specification: `docs/DATASET.md`. Not committed: regenerate it.",
        "",
        "## Size and quality gates",
        "",
        "| Split | Documents | Spans | Rejected by the gates | Near duplicates removed |",
        "|---|---|---|---|---|",
    ]
    for split, (documents, rejected, duplicates) in splits.items():
        spans = sum(len(d.spans) for d in documents)
        lines.append(
            f"| {split} | {len(documents)} | {spans} | {sum(rejected.values())} | {duplicates} |"
        )
    lines += ["", "## Labels (share of spans)", "", "| Label | " + " | ".join(splits) + " |",
              "|---|" + "---|" * len(splits)]  # fmt: skip
    shares = {}
    for split, (documents, _, _) in splits.items():
        counts = Counter(s.label for d in documents for s in d.spans)
        total = sum(counts.values()) or 1
        shares[split] = {
            label: f"{counts[label]} ({counts[label] / total:.1%})" for label in LABELS
        }
    for label in LABELS:
        lines.append(f"| `{label}` | " + " | ".join(shares[s][label] for s in splits) + " |")
    for axis in ("language", "doc_type", "layout", "domain", "locale", "person_origin"):
        header = f"| {axis} | " + " | ".join(splits) + " |"
        lines += ["", f"## Documents by {axis.replace('_', ' ')}", "", header]
        lines.append("|---|" + "---|" * len(splits))
        counts = {s: Counter(getattr(d, axis) for d in docs) for s, (docs, _, _) in splits.items()}
        for value in sorted(set().union(*(c.keys() for c in counts.values()))):
            lines.append(f"| {value} | " + " | ".join(str(counts[s][value]) for s in splits) + " |")
    rejections = Counter()
    for _, rejected, _ in splits.values():
        rejections.update(rejected)
    lines += ["", "## Rejections by reason", ""]
    lines += [f"- {reason}: {count}" for reason, count in rejections.most_common()] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Alias synthetic dataset.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--train", type=int, default=30000)
    parser.add_argument("--validation", type=int, default=3000)
    parser.add_argument("--test", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sizes = {"train": args.train, "validation": args.validation, "test": args.test}
    splits = {split: build_split(split, sizes[split], args.seed) for split in SPLITS}
    for split, (documents, _, _) in splits.items():
        write_jsonl(documents, args.out / f"{split}.jsonl")
    (args.out / "DATASHEET.md").write_text(datasheet(splits, args.seed), encoding="utf-8")


if __name__ == "__main__":
    main()
