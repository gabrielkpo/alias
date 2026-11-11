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
| TAB, Text Anonymization Benchmark (Pilán et al., 2022), MIT | EN, legal (European Court of Human Rights judgments) | real judgments, hand-annotated for anonymisation | converted |
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

## A nod to Mistral (bonus)

Masking Mistral AI's own public legal pages (legal notice, privacy policy) with Alias, by a
script that downloads them and prints the masked text: their texts are not committed.

## Results

Not measured yet.
