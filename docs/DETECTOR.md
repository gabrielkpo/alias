# The Alias detector: rules + model (step 5)

`alias_pii.detector.RulesAndModel` runs the rule layer and the fine-tuned mmBERT-small on the
whole text and keeps every span of both (union). Overlapping spans are merged into one, typed
after the strongest (`entities.resolve_overlaps`, the same function masking uses), so a value
either one finds is masked and nothing of an overlapped value is left in clear.

Why both: on documents written by an LLM it never saw (step 4, out of distribution), the model
alone leaked 14 % of birth dates and found 76 % of national IDs. The rules prove the formats with
a checksum (IBAN, NIR) and now also catch a birth date when a keyword announces it ("né(e) le",
"date de naissance", "naissance :", "date of birth", "DOB", "born on", before or after the date).
A date without such a keyword is left to the model: an invoice or meeting date is not personal.

## Decision rule (written before measuring)

Measured on the **validation** splits only (the test splits were read once in step 4): the
synthetic one (4,200 documents) and the LLM-written one (200 documents, docs/DATASET.md). Methods:
`rules`, `model`, `rules+model`.

1. `rules+model` becomes the Alias detector if, on **both** validation sets, its leak rate is
   lower than the model's alone and its strict precision is no more than 2 points lower.
2. Speed: under 2 seconds per 3,000-character page at the 95th percentile on 4 CPU cores
   (application framing, criterion of the V1), measured on a Kaggle CPU session.
3. Otherwise the results are reported as they are and the choice goes back to Gabriel.

## How it is measured

On a Kaggle CPU session (nothing heavy on a laptop), with the synthetic and LLM-written datasets
(private) and the mmBERT-small checkpoint from the step 4 training kernel:

```
python -m alias_pii.benchmark --data <validation folder> --split validation \
    --methods "rules,model:<checkpoint>,rules+model:<checkpoint>"
python -m alias_pii.latency --model <checkpoint> --data <synthetic> --threads 4 --rules
```

## Results

Pending: filled in from the Kaggle run.
