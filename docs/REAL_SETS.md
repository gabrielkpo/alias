# Real test sets (step 7, draft)

The synthetic and LLM-written numbers measure Alias on text we generated. The real sets measure
the gap with documents people actually write. They are small (a few dozen documents per
language), annotated by hand, and read **once**, at the end, like a test split.

## Rules

- Real documents stay in `data/real/` (ignored by Git). They are never committed, never sent to a
  third party (no Kaggle, no Colab, no LLM API; the benchmark refuses API methods there) and
  never train a model.
- Only aggregated measures leave the machine (precision, recall, leak rate per type); never a
  value, a sentence or a file name that could identify someone.
- Documents come with their owner's agreement: one's own papers, or documents shared for this.

## What to gather (target)

French and English, about 30 documents each, varied: letters and e-mails, forms, invoices and
statements, HR and health documents, contracts. Every Alias type should appear several times per
language; birth dates and national IDs, the weakest out of distribution, at least ten times.

## How to annotate

`alias_pii.annotate` (see its docstring): `prepare` pre-annotates each document with the local
detector into an editable `.ann.txt` where spans read `[[LABEL|value]]`; the annotator fixes them
in a text editor following docs/DATASET.md §2; `collect` reads them back into `test.jsonl` and
checks that only the markup changed. A second pass on a sample, a few days later, estimates the
annotator's own consistency.

## How it is measured

On this machine, CPU only, after the model and rules are frozen:

```
python -m alias_pii.benchmark --data data/real/fr --split test \
    --methods rules,model:<checkpoint>,rules+model:<checkpoint>
```

The README then reports the real numbers next to the synthetic ones, with their size (a few
dozen documents: wide confidence intervals, said as such).
