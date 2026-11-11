"""Realistic test sets from open sources (step 7, docs/REALISTIC_SETS.md).

Converts an open corpus into Alias's evaluation format, one JSON object per line:

    {"text": ..., "spans": [{"start", "end", "label"}], "language": "en", "source": "tab:<id>",
     "labels": ["PERSON", ...], "ignore": [[start, end], ...]}

`labels` lists the Alias types the source annotates: the benchmark scores only those, so a
detector is not penalised for an e-mail the source never labelled. `ignore` lists regions the
source annotates but Alias cannot be scored on (a case-law reference, a lone initial): a scored
prediction there counts neither as right nor as wrong.

Sources (downloaded by hand into data/raw/, never committed):

- `tab`: the Text Anonymization Benchmark (Pilán et al., 2022; MIT licence), English judgments
  of the European Court of Human Rights annotated for anonymisation.
  https://github.com/NorskRegnesentral/text-anonymization-benchmark

    python -m alias_pii.open_sets tab --source data/raw/tab --split test --out data/open/tab
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# TAB PERSON spans keep the honorific ("Mr C. Whomersley"); Alias labels the name only.
_HONORIFIC = re.compile(
    r"^(?:(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sir|Dame|Lord|Lady|Judge|Justice|Mme|Mlle|M)\.?\s+)+"
)
# An application number to the Court ("40593/04") identifies the applicant's file.
_APPLICATION = re.compile(r"^\d{1,6}/\d{2}$")
# A date is a birth date when "born" announces it ("was born in 1965", "born on 13 February 1980").
_BORN = re.compile(r"\bborn\s+(?:in|on)\s+$", re.IGNORECASE)
TAB_LABELS = ["PERSON", "IDENTIFIER", "BIRTH_DATE"]


def _is_name(value: str) -> bool:
    """A name, not a lone initial: TAB keeps "A" or "B.C-D." for applicants the Court named so."""
    return re.search(r"[^\W\d_]{2}", value) is not None


def tab_document(document: dict) -> dict:
    """One TAB document in Alias's format, from its first annotator (TAB documents have one to
    ten; the first is used for every document, so the choice is fixed and not tuned)."""
    text = document["text"]
    annotator = sorted(document["annotations"])[0]
    spans, ignore = [], []
    for mention in document["annotations"][annotator]["entity_mentions"]:
        start, end = mention["start_offset"], mention["end_offset"]
        value = text[start:end]
        kind = mention["entity_type"]
        if kind == "PERSON":
            if not _is_name(value):
                ignore.append([start, end])
                continue
            honorific = _HONORIFIC.match(value)
            if honorific:
                start += honorific.end()
            spans.append({"start": start, "end": end, "label": "PERSON"})
        elif kind == "CODE":
            if _APPLICATION.match(value.strip()):
                spans.append({"start": start, "end": end, "label": "IDENTIFIER"})
            else:
                ignore.append([start, end])
        elif kind == "DATETIME" and _BORN.search(text[max(0, start - 20) : start]):
            spans.append({"start": start, "end": end, "label": "BIRTH_DATE"})
    # One annotator may label the same span twice (two mentions of one entity): keep it once.
    unique = {(s["start"], s["end"], s["label"]): s for s in spans}
    return {
        "text": text,
        "spans": sorted(unique.values(), key=lambda s: (s["start"], s["end"])),
        "language": "en",
        "source": f"tab:{document['doc_id']}",
        "labels": TAB_LABELS,
        "ignore": sorted(ignore),
    }


def convert_tab(source: Path, split: str) -> list[dict]:
    with (source / f"echr_{split}.json").open(encoding="utf-8") as f:
        return [tab_document(d) for d in json.load(f)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert an open corpus to Alias's format.")
    parser.add_argument("corpus", choices=["tab"])
    parser.add_argument("--source", type=Path, required=True, help="the downloaded corpus")
    parser.add_argument("--split", default="test", choices=["train", "dev", "test"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    documents = convert_tab(args.source, args.split)
    args.out.mkdir(parents=True, exist_ok=True)
    name = "validation" if args.split == "dev" else args.split
    with (args.out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
        for document in documents:
            f.write(json.dumps(document, ensure_ascii=False) + "\n")
    labels = {}
    for document in documents:
        for span in document["spans"]:
            labels[span["label"]] = labels.get(span["label"], 0) + 1
    print(f"{len(documents)} documents -> {args.out / f'{name}.jsonl'}: {labels}")


if __name__ == "__main__":
    main()
