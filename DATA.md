# Data card

Every data source Alias uses, under which licence, for what, where it lives and whether it leaves
the machine. Nothing in this table is committed to the repository: datasets are rebuilt from code,
and reports are published as aggregate scores only. Details: docs/DATASET.md and
docs/REALISTIC_SETS.md.

| Source | Licence | Use | Where it lives | Leaves the machine |
|---|---|---|---|---|
| Faker and format generators (fake identities, valid checksums) | MIT (Faker) | grid documents for training, validation and test | `data/synthetic/`, rebuilt from a seed | yes, to GitHub and Kaggle machines for builds and training: no real person |
| LLM-written documents (Mistral, placeholders filled with fake identities) | generated text | training and an out-of-distribution test set | `data/llm/`, `data/cache/` | the prompts go to the Mistral API: they hold placeholders, no real value |
| WikiNER French (`Jean-Baptiste/wikiner_fr` mirror) | CC BY 4.0 | person names in real sentences (names of public figures) | `data/raw/`, then the build | yes, as public data |
| gretel `synthetic_pii_finance_multilingual` (French and English files) | Apache-2.0 | synthetic financial documents | `data/raw/`, then the build | yes, as public data |
| TAB, Text Anonymization Benchmark (European Court of Human Rights judgments) | MIT | measure on real documents, read once | `data/open/`, downloaded at a fixed commit by the `open-sets` workflow | yes, to GitHub machines: public data |
| French court decisions, DILA open data | Licence Ouverte | planned measure on French real documents | not downloaded yet | public data |
| Hand-annotated real texts | the owner's | final measure only | `data/real/`, ignored by Git | **never**: no third party, no notebook service, no LLM API |

Baselines run on the same data: Presidio with spaCy models, GLiNER multi PII and Mistral
zero-shot (the API sees synthetic and public text only). The published model was trained on the
synthetic, LLM-written and public sets above; no model trained on real data is published.
