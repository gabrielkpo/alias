# Realistic test sets from open sources (step 7)

Every number so far is on text we generated (synthetic grid, public corpora converted, LLM-written
documents). Step 7 measures Alias on documents written by people, close to its target sectors:
banking, public administration, defence, health, insurance, HR, legal. Gabriel chose on 11/11 to
take them from **open sources** rather than personal papers (the hand-annotation tool of the
draft `feat/real-sets` stays for later).

## Rules

- Raw source texts are never committed: download scripts and conversion code are, the texts live
  in `data/raw/` and `data/open/` (ignored by Git).
- Only aggregate scores are published, with each source cited under its licence.
- A test split is read **once**, after the detector is frozen, by hand
  (`.github/workflows/open-sets.yml`, never on a push). Its validation split, when the source has
  one, checks the chain first.
- The sources are public and their personal values are either already replaced by their
  publisher or refilled with fake ones by us, so the measure may run on GitHub or Kaggle machines
  (never on a laptop).
- Each source is scored only on the labels it annotates (`labels` in the converted file); regions
  it annotates but Alias cannot be scored on are ignored (`ignore`). Masking, hence the leak
  rate, uses every prediction.

## Sources

| Set | Language, sector | What it brings | State |
|---|---|---|---|
| TAB, Text Anonymization Benchmark (Pilán et al., 2022), MIT | EN, legal (European Court of Human Rights judgments) | real judgments, hand-annotated for anonymisation | measured |
| French court decisions, DILA open data (CASS, CAPP, JADE), Licence Ouverte | FR, labour, banking, insurance, health, administration | real prose; the court's placeholders ("M. [C] [I]", "[Adresse 1]") refilled with fake identities give exact labels | planned |
| Official templates (service-public.fr letters, CERFA forms, payslip, RIB) filled with fake identities | FR, administration, banking, HR, tax; defence only this way | real layouts with every hard type (IBAN, NIR, birth date) | planned |
| CFPB consumer complaint narratives | EN, banking | real complaints, scrubbed to "XXXX": slots typed by hand then refilled | planned |

Considered and left out: synthetic sets (ai4privacy, NVIDIA Nemotron-PII), named-entity corpora
without personal-data labels, sources whose licence forbids it (UK Find Case Law bulk analysis),
and real personal data published for another purpose (French *Journal officiel* nominative
decrees, BODACC). No annotated defence corpus is public.

## TAB, label mapping

Converted by `python -m alias_pii.open_sets tab` from the first annotator of each document.

| TAB | Alias | Note |
|---|---|---|
| PERSON | PERSON | honorific left out ("Mr", "Judge"), initials kept, as in Alias's own labels; a lone initial ("A", "Mr A") is ignored |
| CODE shaped like an application number ("40593/04") | IDENTIFIER | it identifies the applicant's file |
| other CODE (an article reference, a plate number) | ignored | |
| DATETIME announced by "born" in the same clause | BIRTH_DATE | mostly a year ("born in 1965"): Alias learnt full dates, so this is a hard case |
| LOC, ORG, DEM, MISC, QUANTITY, other DATETIME | not scored | TAB's LOC are cities and countries, not postal addresses |

Test split: 127 documents, 951 PERSON, 285 IDENTIFIER and 158 BIRTH_DATE spans (validation
split: 127 documents, 1,051 / 427 / 159).

## TAB, how the test split is read (written before reading it)

The validation split checked the chain and showed how to read the scores. On PERSON the model's
span usually includes the English honorific ("Mr Cengiz Polat" where TAB, and Alias's written
convention, label "Cengiz Polat"): Alias's own English training data is inconsistent on this
(29 PERSON spans with the honorific inside, 10 without, on the synthetic validation split), so
the strict score there measures that convention gap more than detection. Hence, for TAB:

- **Main measures: leak rate** (a value still readable in full after masking) **and overlap
  precision and recall** (same label, any common character), per label and overall.
- Strict precision and recall are reported too, with this caveat.
- Expected weak spots, from the validation split: application numbers ("40593/04", IDENTIFIER)
  leak almost always, since the model does not take a case number for a person's file; birth
  dates are mostly a year alone ("born in 1965"), which it rarely masks.
- The test split is read **once**, with the detector of `main` at `99f533c` and the published
  model, by `gh workflow run open-sets.yml -f set=tab -f split=test`. Nothing in the detector is
  changed after seeing it; what it shows goes to the next variant's validation, not back to TAB.

## A nod to Mistral (bonus)

Masking Mistral AI's own public legal pages (legal notice, privacy policy) with Alias, by a
script that downloads them and prints the masked text: their texts are not committed.

## Results

### TAB, test split (read once, 11/11)

127 English judgments of the European Court of Human Rights, code `99f533c` (variant 3 detector),
published model, GitHub CPU machine (run 43064671338). Overlap scores and leak rate are the main
measures (see above); strict scores in the last column.

| Label | Gold spans | Overlap precision | Overlap recall | Leak rate | Strict P / R |
|---|---|---|---|---|---|
| PERSON | 951 | 0.894 | 0.925 | **12.5 %** | 0.117 / 0.121 |
| BIRTH_DATE (mostly a year) | 158 | 0.935 | 0.259 | 74.7 % | 0.065 / 0.019 |
| IDENTIFIER (application numbers) | 285 | 1.000 | 0.053 | 94.7 % | 0 / 0 |
| all | 1,394 | 0.899 | 0.671 | 36.4 % | 0.112 / 0.085 |

How to read it:

- **Names hold up on real legal English**: 12.5 % of names still readable after masking, against
  3 % on the synthetic validation split and 8 % on the LLM-written one (docs/DETECTOR.md). The misses seen on
  the validation split are real-text cases: fragments of Turkish place names taken for names
  ("Di", "ır" in "Diyarbakır"), a name cut ("eson" for "Gleeson"), initials ("G.D.").
- **The two weak spots announced before reading are confirmed.** A year of birth alone is not
  masked (Alias learnt full dates), and a court application number is not taken for a person's
  file. Both are gaps of Alias's scope as much as of the model: a year alone or a case number is
  a quasi-identifier, which Alias does not claim to cover yet.
- The rules add nothing here (no IBAN, national ID or keyword birth date in these judgments).
- Strict scores are low because the model includes "Mr" in names (the training-data
  inconsistency above), not because names are missed.
