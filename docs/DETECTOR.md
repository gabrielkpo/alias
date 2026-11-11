# The Alias detector: rules + model (step 5)

`alias_pii.detector.RulesAndModel` runs the rule layer and the fine-tuned mmBERT-small on the
whole text. All the model's spans are kept; the rules add the spans of the types they prove
(a checksum for IBANs and national IDs, a keyword for a birth date). Overlapping spans are merged
into one, typed after the strongest (`entities.resolve_overlaps`, the same function masking
uses), so nothing of an overlapped value is left in clear. How this variant came after a first
one that failed the decision rule is told below.

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

Validation splits, Kaggle CPU session (4 cores), code `949db2d`. Strict precision and recall,
leak rate (gold values still readable in full after masking):

| Method | Synthetic: P / R / leak | LLM-written: P / R / leak |
|---|---|---|
| rules | 0.625 / 0.389 / 60.3 % | 0.928 / 0.395 / 59.4 % |
| model (mmBERT-small) | 0.974 / 0.977 / 1.4 % | 0.932 / 0.932 / 5.2 % |
| rules (every type) + model | 0.792 / 0.972 / 1.4 % | 0.928 / 0.934 / 4.9 % |

**The first variant, every rule type added, fails the decision rule.** On the LLM-written
documents it leaks less (4.9 % against 5.2 %: national IDs 4 % instead of 6 %, identifiers 3 %
instead of 5 %) for 0.4 point of precision. On the synthetic split it leaks the same and loses 18
points of precision: the rules' e-mails, phones and identifiers also catch company mailboxes,
switchboards and invoice numbers (precision 0.62, 0.80 and 0.38 there), which the model had
learnt to leave in clear.

Speed, seconds per 3,000-character page on 4 CPU cores: model 1.41 mean, 1.72 p95; rules +
model 1.42 mean, 1.74 p95. Both pass the application's 2 s p95; the rules cost almost nothing.

### Second variant, defined after the first failed

Written down here before its measure, and reported as a change made after seeing results (as
the int8 rule in docs/TRAINING.md): the rules only add the types they **prove**, IBAN and
national ID (checksum) and birth date (keyword), the types where the model is weakest out of
distribution. E-mails, phones and identifiers are left to the model.

It becomes the Alias detector if, on both validation splits, its leak rate is not higher than
the model's alone and lower on at least one, with strict precision no more than 2 points lower.
Because it was designed after seeing the validation numbers, Gabriel may still choose otherwise.

Results (code `2bbb262`, same validation splits):

| Method | Synthetic: P / R / leak | LLM-written: P / R / leak |
|---|---|---|
| model (mmBERT-small) | 0.974 / 0.977 / 1.4 % | 0.932 / 0.932 / 5.2 % |
| **rules (IBAN, national ID, birth date) + model** | **0.974 / 0.977 / 1.4 %** | **0.933 / 0.934 / 5.1 %** |

It passes: identical to the model on the synthetic split, a little better on the LLM-written one
(national IDs leak 4 % instead of 6 %, precision 1.00). **It is the Alias detector.** The gain is
small and said as such: the model already finds most of what the rules prove. Birth dates still
leak 11 % on the LLM-written documents: the dates missed carry no keyword, and some of their gold
labels are doubtful (a contract or meeting date labelled as a birth date by the LLM writer). The
rules matter most where the model has not been measured yet: real documents (step 7).

### Third variant: identifiers announced by a person's-file keyword

Written down here before its measure. The public demo's own example left its file number in
clear ("dossier n° 2024/00421"): identifiers are the model's call since the second variant, and
it misses this one. The identifier rule was left out as a whole because of its precision (0.38 on
the synthetic split), but that precision depends on the keyword. Measured with the rules alone
on the validation splits (exact span = true positive):

| Keyword (normalised) | Synthetic: rule spans, precision | LLM-written: rule spans, precision |
|---|---|---|
| file, dossier, adherent, matricule, contrat, sinistre, licence, license | 475, 1.00 | 9, 1.00 |
| claim, customer, passport, passeport, employee | 125, 0.94 | 6, 1.00 |
| client, patient | absent | 12, 1.00 |
| order, commande, facture, invoice, ticket, reference | 2,460, 0.00 | 24, 0.46 |
| account, compte, id, policy, police | 412, 0.22 | 33, 0.15 |

The first rows name a person's file; the others are mostly orders, invoices and bank accounts
(an account number next to "compte" is usually the IBAN, already proven by its checksum).

**Variant 3**: the second variant plus the rule's identifiers whose keyword names a person's file:
dossier, contrat, client, patient, adhérent, matricule, sinistre, passeport, permis, file,
claim, customer, passport, licence (license), employee, member (membership). `ref`, although
precise on the synthetic split (0.97), is left out: on real documents it announces invoices as
often as files.

**Decision rule.** Variant 3 replaces the second variant if, on both validation splits, its
leak rate is not higher and its strict precision is no more than 0.5 point lower. Caveat written
now: the keywords were chosen by looking at the validation splits (the test splits stay unread),
so the measured gain will be optimistic; the list was chosen on the synthetic split and only
checked on the LLM-written one. Real documents (step 7) are the honest measure.

Results (Kaggle CPU session, code `5f6b725`, same validation splits). Before this run the
detector was also changed to filter the rules' raw spans before merging overlaps: the rules'
phone matcher reads some 10-digit claim numbers as US phones, and a dropped phone must not absorb
a kept identifier. The first run, before that change (code `884b11e`), gave the same numbers.

| Method | Synthetic: P / R / leak | LLM-written: P / R / leak |
|---|---|---|
| second variant | 0.9739 / 0.9773 / 1.40 % | 0.9332 / 0.9342 / 5.10 % |
| **third variant** | **0.9735 / 0.9773 / 1.40 %** | **0.9332 / 0.9342 / 5.10 %** |

It passes (leak unchanged on both splits, precision 0.04 point lower on the synthetic one, where
identifier precision goes from 0.988 to 0.985) and **is now the Alias detector**. The gain on the
validation splits is nil: the model already finds these identifiers there. What it fixes are
the ones the model misses, such as the demo's "dossier n° 2024/00421"; how often that happens on
real documents is for step 7 to say.
