# Public demo: in the browser, on a static Hugging Face Space

The demo shows Alias in a few seconds without installing anything: <https://huggingface.co/spaces/Gabrielkph/alias>.

## Why in the browser

Decision (2026-11-11): publish the demo. Docker Spaces (the first plan, `space/`) now need a paid
Hugging Face subscription on the free CPU tier; static Spaces stay free. The detector therefore
runs in the visitor's browser instead, which also fits the project: the text never leaves the
page, not even to a demo server.

- **Model**: [`Gabrielkph/alias-mmbert-small`](https://huggingface.co/Gabrielkph/alias-mmbert-small),
  the checkpoint chosen at step 4, trained on synthetic and public data only (card:
  docs/MODEL_CARD.md). The repository also holds `onnx/model.onnx`, its float export
  (`alias_pii.onnx_export`, opset 17, run on Kaggle), which gave the same predictions as
  PyTorch on the validation splits. Not quantised: int8 destroys this model's
  precision.
- **Runtime**: transformers.js 4.3.2 (ONNX Runtime Web, WebAssembly), loaded from jsDelivr.
- **Detector**: `demo/alias.js` ports the Python detector (rules of the proven types, token
  windows of 512 with a stride of 128, overlap merging, masking with stable aliases).
- **Privacy**: the page's content security policy allows requests to Hugging Face and jsDelivr
  only; the text is never part of a request. No analytics, no cookie.

## Putting the values back

The page stops at the masked text: the visitor sends it to the LLM they use, with their own
request, and pastes the answer back. `restore` in `demo/alias.js` (the port of
`masking.restore`) replaces each alias of this exchange by its value, kept in the page's memory
only; an alias already literal in the input or invented by the LLM is left as it is and listed,
and an alias the answer dropped is listed too. "Try an example answer" fills in what an LLM could
answer to "Summarise this document" about the example, so the step can be tried without an LLM.
No API key, no credit, no server (decision, 2026-11-11).

## Checks

- `cd demo && npm test`: unit tests of the port, fictitious values only.
- `.github/workflows/demo.yml`, on GitHub CPU machines: the Python detector and the port on 300
  generated validation documents plus edge cases (accents, emoji, tabs, non-breaking spaces,
  several windows). Token ids, token offsets and rule spans must be identical; the full detector
  must give the same spans on at least 99 % of the texts.
- `.github/workflows/space-e2e.yml` (by hand, weekly, and on changes to the test): headless
  Chromium opens the published Space, loads the model and masks the page's fictitious example
  twice; it fails if a value stays in clear, if a request goes to a host other than Hugging Face
  and jsDelivr or carries the text, or on a console error or CSP violation. Screenshot, timings
  and report in the run's artifact (`demo/test/space_e2e.py`).

Known differences with Python, documented in `demo/alias.js`: positions count UTF-16 units, the
rules' phone matcher (libphonenumber) is not ported (phones come from the model), and a phone's
alias key is its digits rather than E.164.

## Cost for a visitor

About 600 MB downloaded on the first visit (the browser keeps it). The time per page in a browser
(single-threaded WebAssembly) is not measured yet; the page shows it after each run.

## Deploying the Space

The public demo changes only with a release. Merging release-please's release PR publishes the
release (tag `vX.Y.Z`, changelog); `release-please.yml` then calls `deploy-space.yml` with that
tag, which uploads the page's five files (`demo/index.html`, `app.js`, `alias.js`, `style.css`,
`README.md`) to the Space, tags the Space commit with the same version, waits until the Space
serves them, and runs the end-to-end check. Merges to `main` in between are tested by CI but not
deployed. To roll back, or to deploy by hand: `gh workflow run deploy-space.yml -f ref=v0.2.0`.

The job runs in the GitHub environment `huggingface` (deployments listed with the Space URL,
limited to `main`) and needs the secret `HF_TOKEN`, a fine-grained Hugging Face token with write
access to the Space `Gabrielkph/alias` only; without it the workflow deploys nothing and says so.
The page shows its version and the model's in the footer. The model is pinned to the tag `v1.0`
of `Gabrielkph/alias-mmbert-small` (in `demo/app.js`, and in the CI downloads), so new weights
reach the demo only through a release that changes that tag.

A change of the model id or of the transformers.js version goes in `demo/app.js`; Dependabot
proposes the npm version, and the CDN version in `app.js` must follow.

## The Docker Space (`space/`)

Still usable with a paid Hugging Face plan: it runs the Python API and page with `--demo` (the
server sees the text, but logs nothing). Variables `ALIAS_REF` and `MODEL_REPO`.
