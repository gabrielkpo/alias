"""Hand annotation of the real test sets, entirely on this machine (step 7).

Real documents are the only honest measure of Alias, and they hold real personal data: they stay
in `data/real/` (ignored by Git), are never sent to a third party and never train a model. The
annotation needs no tool beyond a text editor:

1. `prepare` reads each document (.txt, .md, .docx, PDF), pre-annotates it with a local detector
   and writes `<name>.ann.txt`, where every span found reads `[[LABEL|value]]`:

       python -m alias_pii.annotate prepare --input <folder> --out data/real/fr --language fr

2. The annotator opens each `.ann.txt`, removes wrong spans (keeps the value, drops the
   brackets), fixes boundaries and labels, and wraps what was missed, following the guidelines
   of docs/DATASET.md §2. The pre-annotation only saves typing: every span is checked by hand.
3. `collect` reads the edited files back into `test.jsonl` (the dataset format), checking that
   only the markup changed:

       python -m alias_pii.annotate collect --dir data/real/fr --language fr

The benchmark then reads it once, at the end: `--data data/real/fr --split test` (API methods are
refused on real documents).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from alias_pii.entities import Entity, EntityType

_LABELS = "|".join(t.value for t in EntityType)
MARK = re.compile(rf"\[\[({_LABELS})\|(.*?)\]\]", re.DOTALL)
SUFFIX = ".ann.txt"


class AnnotationError(ValueError):
    """An annotated file that cannot be read back; the message names the file and the place."""


def to_markup(text: str, entities: list[Entity]) -> str:
    """The text with each span wrapped as `[[LABEL|value]]` (spans sorted, non-overlapping)."""
    if "[[" in text or "]]" in text:
        raise AnnotationError("the text already holds '[[' or ']]', which the markup uses")
    parts, cursor = [], 0
    for e in sorted(entities, key=lambda e: e.start):
        if e.start < cursor:
            continue
        parts += [text[cursor : e.start], f"[[{e.type.value}|{text[e.start : e.end]}]]"]
        cursor = e.end
    return "".join(parts) + text[cursor:]


def from_markup(marked: str) -> tuple[str, list[dict]]:
    """The plain text and its spans (`start`, `end`, `label`) from an annotated text."""
    parts, spans, cursor, length = [], [], 0, 0
    for m in MARK.finditer(marked):
        before = marked[cursor : m.start()]
        parts.append(before)
        length += len(before)
        value = m.group(2)
        if not value.strip() or value != value.strip():
            line = marked.count("\n", 0, m.start()) + 1
            raise AnnotationError(f"line {line}: empty value or spaces at its ends: {m.group(1)}")
        spans.append({"start": length, "end": length + len(value), "label": m.group(1)})
        parts.append(value)
        length += len(value)
        cursor = m.end()
    parts.append(marked[cursor:])
    text = "".join(parts)
    for token in ("[[", "]]"):
        if token in text:
            line = text.count("\n", 0, text.index(token)) + 1
            raise AnnotationError(f"line {line}: '{token}' left over (unknown label or typo?)")
    return text, spans


def _inside_real(path: Path) -> bool:
    """Under a `data/real/` folder, the one Git ignores; any other folder named `real` (say
    `docs/real/`) would let real documents be committed."""
    parts = path.resolve().parts
    return any(parts[i : i + 2] == ("data", "real") for i in range(len(parts) - 1))


def prepare(paths: list[Path], out: Path, detector) -> list[Path]:
    """One `.ann.txt` per readable document in `out`; returns the files written."""
    from alias_pii.readers import read_document

    out.mkdir(parents=True, exist_ok=True)
    written = []
    for path in paths:
        document = read_document(path)
        for warning in document.warnings:  # what the reader could not read: annotate by hand
            print(f"{path.name}: {warning}")
        target = out / (path.stem + SUFFIX)
        if target.exists():
            print(f"{target.name}: already there, kept (it may hold hand annotations)")
            continue
        target.write_text(to_markup(document.text, detector.detect(document.text)), "utf-8")
        written.append(target)
    return written


def collect(folder: Path, language: str) -> list[dict]:
    """Every `.ann.txt` of `folder` as dataset documents."""
    documents = []
    for path in sorted(folder.glob("*" + SUFFIX)):
        try:
            text, spans = from_markup(path.read_text("utf-8"))
        except AnnotationError as error:
            raise AnnotationError(f"{path.name}: {error}") from None
        name = path.name.removesuffix(SUFFIX)
        documents.append({"text": text, "spans": spans, "language": language,
                          "source": f"real:{name}"})  # fmt: skip
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description="Annotate the real test sets by hand, locally.")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="pre-annotate documents into .ann.txt files")
    p.add_argument("--input", type=Path, required=True, help="folder of documents")
    p.add_argument("--out", type=Path, required=True, help="a folder under data/real/")
    p.add_argument("--language", choices=["fr", "en"], required=True)
    p.add_argument("--model", help="checkpoint for rules + model (default: rules only)")
    c = commands.add_parser("collect", help="read the edited .ann.txt files into test.jsonl")
    c.add_argument("--dir", type=Path, required=True)
    c.add_argument("--language", choices=["fr", "en"], required=True)
    args = parser.parse_args()

    folder = args.out if args.command == "prepare" else args.dir
    if not _inside_real(folder):
        parser.error("real documents stay under data/real/ (ignored by Git)")
    if args.command == "prepare":
        from alias_pii.readers import SUPPORTED_SUFFIXES

        if args.model:
            from alias_pii.detector import RulesAndModel

            detector = RulesAndModel.from_checkpoint(args.model)
        else:
            from alias_pii.rules import RuleDetector

            detector = RuleDetector()
        paths = sorted(p for p in args.input.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
        written = prepare(paths, args.out, detector)
        print(f"{len(written)} files to check by hand in {args.out}")
    else:
        documents = collect(args.dir, args.language)
        with (args.dir / "test.jsonl").open("w", encoding="utf-8") as out:
            for document in documents:
                out.write(json.dumps(document, ensure_ascii=False) + "\n")
        spans = sum(len(d["spans"]) for d in documents)
        print(f"{len(documents)} documents, {spans} spans -> {args.dir / 'test.jsonl'}")


if __name__ == "__main__":
    main()
