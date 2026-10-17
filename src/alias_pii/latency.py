"""CPU latency of a detector, for the eliminatory rule of the model choice (docs/TRAINING.md):
under one second per page on a standard 4-core CPU, after int8 quantisation.

    python -m alias_pii.latency --model <checkpoint> --data <dataset> --threads 4

A page is 3,000 characters cut from the test documents laid end to end (about one A4 page of
prose). The first pages warm the model up and are not timed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from alias_pii.benchmark import load

PAGE = 3000


def pages(documents: list[dict], n: int, size: int = PAGE) -> list[str]:
    """`n` pages of `size` characters from the documents' texts laid end to end."""
    text = "\n\n".join(d["text"] for d in documents)
    return [text[i * size : (i + 1) * size] for i in range(min(n, len(text) // size))]


def measure(detector, texts: list[str], warmup: int = 3) -> dict:
    """Seconds per page: mean, median and 95th percentile over the timed pages."""
    for text in texts[:warmup]:
        detector.detect(text)
    times = []
    for text in texts[warmup:]:
        start = time.perf_counter()
        detector.detect(text)
        times.append(time.perf_counter() - start)
    times.sort()
    return {
        "pages": len(times),
        "mean_s": statistics.fmean(times),
        "median_s": statistics.median(times),
        "p95_s": times[max(0, round(0.95 * len(times)) - 1)],
        "passes": statistics.fmean(times) < 1.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CPU latency per page of a fine-tuned model.")
    parser.add_argument("--model", required=True, help="checkpoint folder")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--pages", type=int, default=53, help="3 warm-up pages + 50 timed")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--quantize", choices=["none", "all", "no-head", "mlp"], default="all")
    args = parser.parse_args()

    import torch

    from alias_pii.train import TrainedDetector

    torch.set_num_threads(args.threads)
    mode = None if args.quantize == "none" else args.quantize
    detector = TrainedDetector(args.model, quantize=mode)
    result = measure(detector, pages(load(args.data / "test.jsonl"), args.pages))
    result.update(model=args.model, threads=args.threads, quantize=args.quantize)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
