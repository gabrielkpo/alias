---
title: Alias
emoji: 🫥
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: Mask personal data (FR/EN) before a text goes to an LLM
---

# Alias, public demo

Paste a French or English text: Alias highlights the personal data it finds (names, addresses,
e-mails, phones, IBANs, national IDs, birth dates, file numbers) and gives the text back with
stable aliases (`[PERSON_1]`, `[IBAN_1]`), ready to send to an LLM.

**Fictitious data only.** This demo runs on a shared server: do not paste real personal data.
The text is not logged or stored, but the place for real documents is your own machine (Docker
image, see the repository).

Detector: rules plus a fine-tuned mmBERT-small
([model card](https://github.com/gabrielkpo/alias/blob/main/docs/MODEL_CARD.md)). Code, results
and limits: [github.com/gabrielkpo/alias](https://github.com/gabrielkpo/alias).
