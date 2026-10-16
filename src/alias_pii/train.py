"""Fine-tune a multilingual encoder for token classification (step 4, docs/TRAINING.md).

    uv run --group train python -m alias_pii.train --model jhu-clsp/mmBERT-small \\
        --data data/synthetic --out models/mmbert-small

The same settings are used for the three candidates (Gabriel's decision of 16/10): 3 epochs,
windows of 512 tokens with a 128-token overlap, learning rate 3e-5, batch 16, warm-up 10 %. The
choice rule is fixed before training (README): it reads the validation split only; the test
split is read once, at the end, by `alias_pii.benchmark`. Each run appends one line to
`results/training.jsonl` (configuration, data and code versions, validation scores).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from alias_pii.benchmark import load, run
from alias_pii.entities import Entity
from alias_pii.tagging import IGNORE, TAG_ID, TAGS, merge_windows, spans_from_tokens, token_labels

CHOICE_LABELS = ("PERSON", "ADDRESS", "BIRTH_DATE")


@dataclass
class Config:
    model: str
    epochs: int = 3
    max_length: int = 512
    stride: int = 128
    learning_rate: float = 3e-5
    batch_size: int = 16
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    seed: int = 0


def encode(tokenizer, document: dict, config: Config) -> list[dict]:
    """Model inputs and BIO labels for every window of one document."""
    encoded = tokenizer(
        document["text"],
        truncation=True,
        max_length=config.max_length,
        stride=config.stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
    )
    spans = [(s["start"], s["end"], s["label"]) for s in document["spans"]]
    windows = []
    for i, offsets in enumerate(encoded["offset_mapping"]):
        windows.append(
            {
                "input_ids": encoded["input_ids"][i],
                "attention_mask": encoded["attention_mask"][i],
                "labels": token_labels(document["text"], offsets, spans),
            }
        )
    return windows


class TrainedDetector:
    """A fine-tuned checkpoint as a detector (`detect(text)`), for masking and the benchmark."""

    def __init__(self, path: str, max_length: int = 512, stride: int = 128, device: str = "cpu"):
        import torch
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.model = (
            AutoModelForTokenClassification.from_pretrained(path, **_loading_options(path))
            .to(device)
            .eval()
        )
        self.max_length, self.stride, self.device = max_length, stride, device

    def detect(self, text: str) -> list[Entity]:
        encoded = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            stride=self.stride,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
            padding=True,
            return_tensors="pt",
        )
        offsets = encoded.pop("offset_mapping").tolist()
        encoded.pop("overflow_to_sample_mapping", None)
        with self.torch.no_grad():
            logits = self.model(**{k: v.to(self.device) for k, v in encoded.items()}).logits
        predicted = logits.argmax(-1).tolist()
        windows = [
            ([tuple(o) for o in offs], tags) for offs, tags in zip(offsets, predicted, strict=True)
        ]
        return spans_from_tokens(text, merge_windows(windows))


def _loading_options(model: str) -> dict:
    """ModernBERT models (mmBERT) compile their MLP with torch.compile by default, which crashes
    under the Trainer on Kaggle GPUs ("FX to symbolically trace a dynamo-optimized function",
    then SIGSEGV). Turn it off; other architectures load unchanged."""
    from transformers import AutoConfig

    if AutoConfig.from_pretrained(model).model_type == "modernbert":
        return {"reference_compile": False}
    return {}


def _version(path: Path) -> str:
    digest = hashlib.sha256()
    for split in ("train", "validation"):
        digest.update((path / f"{split}.jsonl").read_bytes())
    return digest.hexdigest()[:12]


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def validation_scores(detector, documents: list[dict]) -> dict:
    """Validation measures used by the choice rule: strict recall on PERSON, ADDRESS and
    BIRTH_DATE averaged over French and English, plus overall scores."""
    summary = run("model", detector, documents).summary()
    by_language = summary["by"]["language_label"]
    per_language = {}
    for language in ("fr", "en"):
        recalls = [
            by_language[f"{language}/{label}"]["recall"]
            for label in CHOICE_LABELS
            if f"{language}/{label}" in by_language
        ]
        per_language[language] = sum(recalls) / len(recalls) if recalls else 0.0
    return {
        "choice_recall": (per_language["fr"] + per_language["en"]) / 2,
        "choice_recall_by_language": per_language,
        "all": summary["by"]["all"]["all"],
        # measured on the training device (GPU on Kaggle): the CPU budget is checked separately
        "ms_per_1000_chars_training_device": summary["ms_per_1000_chars"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune an Alias candidate model.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16, help="lower it on a laptop")
    parser.add_argument("--limit", type=int, default=0, help="first N documents (smoke test)")
    parser.add_argument("--results", type=Path, default=Path("results/training.jsonl"))
    args = parser.parse_args()
    if "real" in args.data.resolve().parts:
        parser.error("training uses synthetic and public data only, never real documents")

    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
    )

    config = Config(model=args.model, epochs=args.epochs, batch_size=args.batch_size)
    train_docs = load(args.data / "train.jsonl")
    validation_docs = load(args.data / "validation.jsonl")
    if args.limit:
        train_docs, validation_docs = (
            train_docs[: args.limit],
            validation_docs[: args.limit // 10 + 1],
        )
    tokenizer = AutoTokenizer.from_pretrained(config.model)
    windows = [w for d in train_docs for w in encode(tokenizer, d, config)]
    model = AutoModelForTokenClassification.from_pretrained(
        config.model,
        num_labels=len(TAGS),
        id2label=dict(enumerate(TAGS)),
        label2id=TAG_ID,
        **_loading_options(config.model),
    )
    training = TrainingArguments(
        output_dir=str(args.out / "checkpoints"),
        num_train_epochs=config.epochs,
        learning_rate=config.learning_rate,
        per_device_train_batch_size=config.batch_size,
        warmup_ratio=config.warmup_ratio,
        weight_decay=config.weight_decay,
        seed=config.seed,
        save_strategy="epoch",
        save_total_limit=1,
        logging_steps=50,
        fp16=torch.cuda.is_available(),
        report_to=[],
    )
    trainer = Trainer(
        model=model,
        args=training,
        train_dataset=Dataset.from_list(windows),
        data_collator=DataCollatorForTokenClassification(tokenizer, label_pad_token_id=IGNORE),
    )
    checkpoints = sorted(
        (args.out / "checkpoints").glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[-1])
    )
    trainer.train(resume_from_checkpoint=str(checkpoints[-1]) if checkpoints else None)
    trainer.save_model(str(args.out / "final"))
    tokenizer.save_pretrained(str(args.out / "final"))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    scores = validation_scores(
        TrainedDetector(str(args.out / "final"), device=device), validation_docs
    )
    record = {
        "date": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
        "commit": _commit(),
        "data": _version(args.data),
        "train_documents": len(train_docs),
        "train_windows": len(windows),
        "config": asdict(config),
        "validation": scores,
    }
    args.results.parent.mkdir(parents=True, exist_ok=True)
    with args.results.open("a", encoding="utf-8") as out:
        out.write(json.dumps(record) + "\n")
    print(json.dumps(scores, indent=1))


if __name__ == "__main__":
    main()
