# Results in detail

The table is in the README. What follows comments it, with the limits of these measures.

## Synthetic test split (4,200 documents)

- Rules find every e-mail, IBAN and phone number of this split, and 89 % of national IDs, but
  nothing that needs context (names, addresses, birth dates). The first part is partly built in:
  the dataset's quality gates keep only documents where the rules find every labelled e-mail and
  phone (docs/DATASET.md), so this does not measure the rules on unfiltered text. They also mask
  company mailboxes, switchboards and invoice numbers, which Alias leaves in clear: precision
  0.58 on `EMAIL`, 0.42 on `IDENTIFIER`.
- GLiNER finds names, addresses and birth dates (recall 0.80, 0.91, 1.00) but misses most IBANs and
  national IDs (0.24 and 0.06): rules and a model complement each other.
- The hybrid (rules for validated formats, GLiNER for names, addresses and birth dates) gets
  recall 0.85 and halves the leak rate (12.6 %). What leaks most is names (17 %) and
  identifiers (42 %): the targets for the trained model.
- GLiNER takes about 1.1 s for a 3,000-character page: above the one-second budget set for the
  model choice.
- Mistral asked to list the personal data, without training, leaks 10.1 % on the first 1,000
  test documents (a subset: the other rows read all 4,200, so the comparison is indicative). It
  sits between the hybrid baseline and the fine-tuned model, and the text leaves the machine.
- The fine-tuned mmBERT-small leaks ten times less than the best baseline. It was chosen among
  three candidates (docs/TRAINING.md); int8 quantisation destroyed its precision, so it runs
  unquantised, at about one second per page on 4 CPU cores.

## Out of distribution

- On 200 documents written by Mistral, a generator absent from training, the model keeps recall
  0.93, precision 0.94 and leak rate 3.5 %, against 0.91, 0.90 and 8.1 % for rules + GLiNER. Its
  weak spots there are birth dates (14 % leaked) and national IDs (recall 0.76). Mistral
  zero-shot reaches 0.93, 0.89 and 4.1 % on the same documents, which it wrote itself.
- Rules + model (docs/DETECTOR.md): the rules add IBANs and national IDs (checksum) and birth
  dates announced by a keyword to the model's spans. On the validation splits it equals the model
  on synthetic text and leaks a little less on LLM-written text (5.1 % against 5.2 %; national
  IDs 4 % against 6 %). Adding every rule type cost 18 points of precision for no leak gained.
- **Real documents** (docs/REALISTIC_SETS.md): on the 127 English judgments of the Text
  Anonymization Benchmark (European Court of Human Rights), read once, 12.5 % of names stay
  readable after masking (overlap recall 0.93, precision 0.89). Years of birth alone and court
  application numbers mostly stay in clear (75 % and 95 %): quasi-identifiers Alias does not
  cover yet. French real-world sets come next.

## Limits of these measures

- The synthetic splits are not fully separate: some phrase templates and some fake names appear
  in training and test (docs/DATASET.md). The LLM-written and TAB sets do not share templates with
  training and are the fairer measures.
- Each model was trained once (one seed), without confidence intervals: differences of a few
  tenths of a point between candidates are within noise.
- The benchmark reports are generated, not committed: rerun them with
  `uv run python -m alias_pii.benchmark` or the `Compute` workflow. Versioned run records are
  planned.

A value counts as leaked only when it is readable in full (exactly or without separators): a
name masked by half does not count, which the overlap and strict recalls show instead.
