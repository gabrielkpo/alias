---
title: Alias
emoji: 🫥
colorFrom: gray
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Mask personal data (FR/EN) in the browser before an LLM
models:
  - Gabrielkph/alias-mmbert-small
---

# Alias, public demo

Paste a French or English text: Alias highlights the personal data it finds (names, addresses,
e-mails, phones, IBANs, national IDs, birth dates, file numbers) and gives the text back with
stable aliases (`[PERSON_1]`, `[IBAN_1]`), ready to send to an LLM.

**The detector runs in your browser.** The page downloads the model once (about 570 MB, kept by
the browser for later visits) and the ONNX runtime, then masks the text locally: the text is never
sent anywhere, and the page's content security policy allows no host but Hugging Face (model
files) and jsDelivr (runtime). Still, use fictitious data: this is a demo.

Detector: checksum and keyword rules plus a fine-tuned mmBERT-small
([model](https://huggingface.co/Gabrielkph/alias-mmbert-small)), the same as the Python package,
ported to JavaScript and checked against it on GitHub Actions. Code, results and limits:
[github.com/gabrielkpo/alias](https://github.com/gabrielkpo/alias).

## Files

- `index.html`, `app.js`, `style.css`: the page; `app.js` loads transformers.js 4.3.1.
- `alias.js`: the detector's logic (rules, token windows, masking), ported from `src/alias_pii`.
- `test/`: unit tests (`npm test`) and the parity check against Python (`.github/workflows/demo.yml`);
  not uploaded to the Space.
