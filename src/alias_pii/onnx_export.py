"""ONNX Runtime for the fine-tuned model: faster CPU inference without quantisation (step 6).

PyTorch dynamic int8 destroyed the model's precision (docs/TRAINING.md), so the speed-up is
sought in the runtime instead: the same float weights, exported to ONNX and run by ONNX Runtime
with its graph optimisations. The predictions must stay the same as PyTorch's; the benchmark
checks it on the validation split before any use.

    python -m alias_pii.onnx_export --model <checkpoint> --out <folder>
    python -m alias_pii.benchmark --split validation --methods model:<checkpoint>,onnx:<folder>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from alias_pii.entities import Entity
from alias_pii.tagging import merge_windows, spans_from_tokens

MODEL_FILE = "model.onnx"


def export(checkpoint: str, out: Path, opset: int = 17) -> Path:
    """Export a token-classification checkpoint to `out/model.onnx`, tokenizer and config next to
    it. Batch and sequence lengths stay dynamic (several windows of up to 512 tokens)."""
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    from alias_pii.train import _loading_options

    out.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = AutoModelForTokenClassification.from_pretrained(
        checkpoint, attn_implementation="eager", **_loading_options(checkpoint)
    ).eval()
    sample = tokenizer(["Jean Dupont habite à Lyon.", "Mail: a@example.com"], padding=True,
                       return_tensors="pt")  # fmt: skip
    axes = {0: "batch", 1: "sequence"}
    with torch.no_grad():
        torch.onnx.export(
            model,
            (sample["input_ids"], sample["attention_mask"]),
            str(out / MODEL_FILE),
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={"input_ids": axes, "attention_mask": axes, "logits": axes},
            opset_version=opset,
            dynamo=False,
        )
    tokenizer.save_pretrained(out)
    model.config.save_pretrained(out)
    return out / MODEL_FILE


class OnnxDetector:
    """The exported model as a detector, same windows and merging as `train.TrainedDetector`."""

    def __init__(
        self,
        path: str,
        max_length: int = 512,
        stride: int = 128,
        threads: int = 0,
        model_file: str = MODEL_FILE,
    ):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(
            str(Path(path) / model_file), options, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.max_length, self.stride = max_length, stride

    def detect(self, text: str) -> list[Entity]:
        encoded = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            stride=self.stride,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
            padding=True,
            return_tensors="np",
        )
        logits = self.session.run(
            ["logits"],
            {
                "input_ids": encoded["input_ids"].astype("int64"),
                "attention_mask": encoded["attention_mask"].astype("int64"),
            },
        )[0]
        predicted = logits.argmax(-1).tolist()
        offsets = encoded["offset_mapping"].tolist()
        windows = [
            ([tuple(o) for o in offs], tags) for offs, tags in zip(offsets, predicted, strict=True)
        ]
        return spans_from_tokens(text, merge_windows(windows))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a fine-tuned checkpoint to ONNX.")
    parser.add_argument("--model", required=True, help="checkpoint folder")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(export(args.model, args.out))


if __name__ == "__main__":
    main()
