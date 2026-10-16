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
batch 16, warm-up 10 %, weight decay 0.01, seed 0. Labels are BIO over the eight Alias types
(17 tags). A token takes the label of the span containing its first non-space character; long
documents are read in overlapping windows and, at prediction time, each token keeps the
prediction of the window where it sits farthest from an edge (`alias_pii.tagging`).

## Choice rule

1. **Eliminatory:** under one second per page on a standard 4-core CPU (GitHub Actions
   `ubuntu-latest`), after int8 quantisation; measured there after training, not on the
   training GPU. (Changed on 16/10, before any training: heavy runs never use the laptop.)
2. **Main criterion:** best strict recall on `PERSON`, `ADDRESS` and `BIRTH_DATE`, averaged over
   French and English (`choice_recall` in the results file).
3. **Tie-break** (gap under one point): lowest leak rate combined with the rules, then fastest.

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
