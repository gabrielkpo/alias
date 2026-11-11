# Public demo: in the browser, on a static Hugging Face Space

The demo shows Alias in a few seconds without installing anything: <https://huggingface.co/spaces/Gabrielkph/alias>.

## Why in the browser

Publishing was agreed by Gabriel on 11/11. Docker Spaces (the first plan, `space/`) now need a paid
Hugging Face subscription on the free CPU tier; static Spaces stay free. Gabriel chose to run the
detector in the visitor's browser instead, which also fits the project: the text never leaves the
page, not even to a demo server.

- **Model**: [`Gabrielkph/alias-mmbert-small`](https://huggingface.co/Gabrielkph/alias-mmbert-small),
  the checkpoint chosen at step 4, trained on synthetic and public data only (card:
  docs/MODEL_CARD.md). The repository also holds `onnx/model.onnx`, its float export, made on
  Kaggle with the export of the ONNX draft branch (`feat/onnx`, opset 17), which gave the same
  predictions as PyTorch on the validation splits. Not quantised: int8 destroys this model's
  precision.
- **Runtime**: transformers.js 4.3.2 (ONNX Runtime Web, WebAssembly), loaded from jsDelivr.
- **Detector**: `demo/alias.js` ports the Python detector (rules of the proven types, token
  windows of 512 with a stride of 128, overlap merging, masking with stable aliases).
- **Privacy**: the page's content security policy allows requests to Hugging Face and jsDelivr
  only; the text is never part of a request. No analytics, no cookie.

## Checks

- `cd demo && npm test`: unit tests of the port, fictitious values only.
- `.github/workflows/demo.yml`, on GitHub CPU machines: the Python detector and the port on 300
  generated validation documents plus edge cases (accents, emoji, tabs, non-breaking spaces,
  several windows). Token ids, token offsets and rule spans must be identical; the full detector
  must give the same spans on at least 99 % of the texts.

Known differences with Python, documented in `demo/alias.js`: positions count UTF-16 units, the
rules' phone matcher (libphonenumber) is not ported (phones come from the model), and a phone's
alias key is its digits rather than E.164.

## Cost for a visitor

About 600 MB downloaded on the first visit (the browser keeps it). The time per page in a browser
(single-threaded WebAssembly) is not measured yet; the page shows it after each run.

## Updating the Space

Upload `demo/index.html`, `app.js`, `alias.js`, `style.css` and `README.md` to the Space (the
tests and `package.json` stay in the repository). A change of the model id or of the
transformers.js version goes in `demo/app.js`; Dependabot proposes the npm version, and the CDN
version in `app.js` must follow.

## The Docker Space (`space/`)

Still usable with a paid Hugging Face plan: it runs the Python API and page with `--demo` (the
server sees the text, but logs nothing). Variables `ALIAS_REF` and `MODEL_REPO`.
