"""Reference outputs of the Python detector, for demo/test/parity.mjs to compare the browser port.

Texts: generated validation documents (fictitious identities, `synthetic.generate`) plus edge
cases (accents, emoji, tabs, non-breaking spaces, a text starting with a newline, a long text read
in several windows). For each text it writes the rules' spans of the detector's types, the
tokenizer's ids and offsets and, with `--model`, the full detector's spans (rules + model).
Offsets are converted to UTF-16 units, as JavaScript counts them.

    python demo/test/parity_cases.py --tokenizer Gabrielkph/alias-mmbert-small --out cases.json
    python demo/test/parity_cases.py --tokenizer <folder> --model <folder> --out cases.json

The model run is CPU inference: it runs on GitHub Actions (.github/workflows/demo.yml).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alias_pii.detector import RULE_TYPES, RulesAndModel
from alias_pii.rules import RuleDetector
from alias_pii.synthetic import generate

EDGE_CASES = [
    "\nJean Dupont, né le 12/03/1985.",
    " Leading space: Marie Curie, 1 85 05 78 006 084 91.",
    "Tabs\tand non-breaking spaces: IBAN FR76 3000 6000 0112 3456 7890 189 🙂 ok",
    "Émoji 👩🏽‍💻 and CJK 東京 near jean.dupont@example.com, DOB: 2 novembre 1956.",
    "Customer ID: AB-123456, SSN 123-45-6789, NINO AB 12 34 56 C, date of birth as July 2, 1969",
    "15/04/1965 : date de naissance de Paul Martin ; GB82 WEST 1234 5698 7654 32",
    "Écrire à Jean Dupont, 14 rue des Lilas, 69003 Lyon. " * 120,  # several windows
]


def utf16(text: str) -> list[int]:
    """Code point index -> UTF-16 index, for every position 0..len(text)."""
    positions, unit = [0], 0
    for char in text:
        unit += 2 if ord(char) > 0xFFFF else 1
        positions.append(unit)
    return positions


def spans(text: str, entities) -> list[list]:
    to16 = utf16(text)
    return [[e.type.value, to16[e.start], to16[e.end]] for e in entities]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tokenizer", required=True, help="Hugging Face id or folder")
    parser.add_argument("--model", help="checkpoint folder: also run the full detector")
    parser.add_argument("--documents", type=int, default=300, help="generated documents")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer)
    rules = RuleDetector()
    detector = RulesAndModel.from_checkpoint(args.model) if args.model else None
    texts = [e.text for e in generate(args.documents, split="validation", seed=0)] + EDGE_CASES
    cases = []
    for text in texts:
        encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        to16 = utf16(text)
        case = {
            "text": text,
            "ids": encoded["input_ids"],
            "offsets": [[to16[s], to16[e]] for s, e in encoded["offset_mapping"]],
            "rules": spans(text, [e for e in rules.detect(text) if e.type in RULE_TYPES]),
        }
        if detector is not None:
            case["detector"] = spans(text, detector.detect(text))
        cases.append(case)
    args.out.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    print(f"{len(cases)} cases -> {args.out}")


if __name__ == "__main__":
    main()
