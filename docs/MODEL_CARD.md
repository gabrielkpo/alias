---
language: [fr, en]
license: mit
library_name: transformers
pipeline_tag: token-classification
base_model: jhu-clsp/mmBERT-small
tags: [pii, ner, anonymization, privacy]
---

# Alias mmBERT-small: personal data detection, French and English

Token classification model of [Alias](https://github.com/gabrielkpo/alias): it finds the personal
data in a French or English text so it can be masked before the text goes to an LLM. Fine-tuned
from `jhu-clsp/mmBERT-small`; in Alias it runs together with rules (checksums and keywords).

## Labels

BIO tags over eight types: `PERSON`, `ADDRESS`, `EMAIL`, `PHONE`, `IBAN`, `NATIONAL_ID` (French
NIR, US SSN, UK NINO), `BIRTH_DATE`, `IDENTIFIER` (a person's file, contract or customer number).
Company names, company addresses, switchboards and invoice numbers are not labelled. Long texts
are read in windows of 512 tokens overlapping by 128.

## Training data

Synthetic and public only, **no private documents or private persons' data**; the public
WikiNER corpus contains names of public figures:

- documents generated from a grid of types, domains and formats with fake identities (Faker,
  MIT), every span known by construction;
- WikiNER French (CC BY 4.0; Nothman et al., 2013), names converted to `PERSON`;
- gretel `synthetic_pii_finance_multilingual` (Apache-2.0), French and English.

3 epochs, learning rate 3e-5, batch 16, windows of 512 tokens (`alias_pii.train`). Chosen among
three candidates (mmBERT-small, XLM-RoBERTa base, mDeBERTa-v3 base) by a rule written before
training (docs/TRAINING.md in the repository).

## Results

| Set | Precision | Recall | Leak rate |
|---|---|---|---|
| Synthetic test split (4,200 documents, read once) | 0.970 | 0.980 | 1.1 % |
| 200 documents written by an LLM absent from training | 0.94 | 0.93 | 3.5 % |

Strict precision and recall (label and both boundaries); leak rate: share of personal values still
readable in full after masking. Also measured once on public real documents, English court
judgments of the TAB benchmark: see docs/REALISTIC_SETS.md in the repository. CPU, unquantised:
about one second per 3,000-character page on 4 cores. Dynamic int8 quantisation destroys its
precision.

## Limits

- Measured on synthetic and LLM-written text, and on one public set of real English judgments
  (TAB): other real documents, French ones especially, may hold forms it never saw.
- Out of distribution its weak spots are birth dates and national IDs. The Alias rules add
  national IDs (checksum), birth dates announced by a keyword and file numbers announced by a
  person's-file keyword ("dossier n°", "customer ID"); a birth date with no keyword can still be
  missed (11 % leaked on LLM-written validation text, docs/DETECTOR.md).
- No detector has perfect recall: Alias is a component, not an anonymity guarantee.

## Use

```python
# pip install "alias-pii[model] @ git+https://github.com/gabrielkpo/alias"
from huggingface_hub import snapshot_download

from alias_pii.detector import RulesAndModel
from alias_pii.masking import mask

detector = RulesAndModel.from_checkpoint(snapshot_download("Gabrielkph/alias-mmbert-small"))
print(mask("Écrire à Jean Dupont, 14 rue des Lilas, 69003 Lyon.", detector).text)
```
