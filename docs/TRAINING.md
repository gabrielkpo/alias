# Training the Alias model (step 4)

Three multilingual encoders are fine-tuned for token classification in the same conditions, and
the best one becomes the Alias model. The choice rule was written before any training (README,
evaluation plan) and reads the **validation** split only; the test split is read once, at the
end, by `alias_pii.benchmark`.

## Candidates

| Model | Hugging Face id | Why |
|---|---|---|
| mmBERT-small | `jhu-clsp/mmBERT-small` | lightest, recent, long context |
| XLM-RoBERTa base | `FacebookAI/xlm-roberta-base` | proven multilingual reference, easy ONNX / int8 export |
| mDeBERTa-v3 base | `microsoft/mdeberta-v3-base` | often strongest on multilingual NER; GLiNER's backbone |

## Same settings for all three

`alias_pii.train.Config`: 3 epochs, windows of 512 tokens overlapping by 128, learning rate 3e-5,
batch 16 per device (reached in two passes of 8 with `--grad-accum 2` for mDeBERTa, which does
not fit a 16 GB T4 otherwise: same batch), warm-up 10 %, weight decay 0.01, seed 0. Labels are
BIO over the eight Alias types
(17 tags). A token takes the label of the span containing its first non-space character; long
documents are read in overlapping windows and, at prediction time, each token keeps the
prediction of the window where it sits farthest from an edge (`alias_pii.tagging`).

## Choice rule

1. **Eliminatory:** under one second per page on a standard 4-core CPU, after int8
   quantisation; measured on a Kaggle CPU session (4 cores), not on the training GPU.
2. **Main criterion:** best strict recall on `PERSON`, `ADDRESS` and `BIRTH_DATE`, averaged over
   French and English (`choice_recall` in the results file).
3. **Tie-break** (gap under one point): lowest leak rate combined with the rules, then fastest.

**Rule changed after the results (Gabriel's decision of 17/10), recorded here as such.** The
eliminatory rule assumed that int8 quantisation keeps the quality. It does not: PyTorch dynamic
int8 dropped mmBERT-small's precision from 0.970 to 0.337 on the test split, and the careful
modes (head kept in float, or only the feed-forward layers in int8) reached 0.71 at best on the
validation. The rule now reads "about one second per page, unquantised". Faster inference without
quality loss (ONNX Runtime) moves to step 6.

## Results

Validation split (synthetic), unquantised, from `results/training.jsonl`; CPU latency on a Kaggle
CPU session (4 cores), seconds per 3,000-character page:

| Model | Choice recall | French / English | Precision | Leak rate | Latency, float | Latency, int8 (all) |
|---|---|---|---|---|---|---|
| **mmBERT-small** | **0.976** | 0.984 / 0.968 | 0.974 | 1.4 % | 1.07 to 1.22 | 0.66 (quality lost) |
| XLM-RoBERTa base | 0.952 | 0.956 / 0.948 | 0.958 | 1.3 % | 1.49 to 1.73 | 0.83 (quality lost) |
| mDeBERTa-v3 base | 0.927 | 0.921 / 0.933 | 0.947 | 1.3 % | 2.63 | 1.44 |

mmBERT-small is chosen. mDeBERTa, often the strongest on multilingual NER, came last here and was
also the slowest. Its single test read (4,200 documents): precision 0.970, recall 0.980, leak
rate 1.1 %, against 0.63, 0.85 and 12.6 % for the best baseline (rules + GLiNER). These are
synthetic numbers; the real annotated sets are the next measure.

## Where it runs: Kaggle

Training uses the synthetic and public data only (never `data/real/`: the command refuses it).
It runs on a free Kaggle GPU, the same for the three candidates.

1. Build the dataset locally: `uv run --group data python -m alias_pii.build_dataset --out
   data/synthetic --raw data/raw` (see docs/DATASET.md).
2. Upload it as a **private** Kaggle dataset. The Kaggle API token is set up by the account owner
   in `~/.kaggle/kaggle.json`, never in the repository.
   ```
   kaggle datasets init -p data/synthetic   # then set the title and id in dataset-metadata.json
   kaggle datasets create -p data/synthetic  # private by default
   ```
3. In a Kaggle notebook with a GPU, attach that dataset, then:
   ```
   !pip install -q git+https://github.com/gabrielkpo/alias "transformers>=4.51,<5" datasets accelerate
   !python -m alias_pii.train --model jhu-clsp/mmBERT-small \
       --data /kaggle/input/<dataset> --out /kaggle/working/mmbert-small \
       --results /kaggle/working/training.jsonl
   ```
   Checkpoints are saved each epoch; rerunning the same command resumes from the last one.
4. Download `final/` and `training.jsonl`; append the line to `results/training.jsonl` in the
   repository.

## Results file

`results/training.jsonl` (versioned): one line per run with the date, code commit, a hash of the
train and validation files, the configuration and the validation scores. The losing candidates
stay in it: their numbers go into the README results table.

## Publication

The winning model may be published on Hugging Face with a model card (data, limits, measures,
WikiNER attribution, CC BY 4.0), only after Gabriel's explicit agreement once the results are
known. No model trained on real data is ever published.

## Smoke test

`--limit 300 --epochs 1` trains on 300 documents to check the whole chain before using GPU time.
It runs on GitHub's CPU machines, not on a laptop: `gh workflow run compute.yml -f
task=smoke-train`, or the `compute` label on a pull request.
