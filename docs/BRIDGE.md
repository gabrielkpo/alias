# Alias Bridge: your tools talk to Mistral, the personal data found stays on your machine

The bridge is a local endpoint with the same API as Mistral's chat completions. A tool written
for Mistral (a script, the `mistralai` or `openai` SDK, LibreChat, n8n…) keeps its code and only
changes its base URL:

```
https://api.mistral.ai/v1   ->   http://127.0.0.1:8001/v1
```

For each `POST /v1/chat/completions` the bridge masks every message, checks that no checksummed
value (IBAN, national ID) is still readable, forwards the request to Mistral with the user's
key, then puts the real values back in the answer. Nothing but counts is logged.

What the detector misses reaches Mistral in clear (see [Limits](#limits)).

## Run it

```
uv tool install "alias-pii[serve] @ git+https://github.com/gabrielkpo/alias"
alias-pii key set      # asks for the Mistral key, stores it in the macOS keychain
alias-pii serve        # http://127.0.0.1:8001/v1
```

`alias-pii serve` runs the published model on ONNX Runtime, without PyTorch: the first launch
downloads it once (about 600 MB, at a pinned revision, into the Hugging Face cache), later
launches read it from the disk. It listens on 127.0.0.1 only. `--model <folder>` (or
`ALIAS_MODEL`) uses a local ONNX export instead. Without a model the bridge does not run:
`--rules-only` starts it with the rules alone on purpose, with a warning in the log; they mask
e-mails, phone numbers, IBANs, national IDs, file numbers and dates of birth announced as such,
but no names or addresses. `GET /health` and the `X-Alias-Detector` header of each answer name
the detector in use (`rules+model` or `rules`).

The Mistral key comes from the keychain (`alias-pii key status`, `alias-pii key delete`), else
from `MISTRAL_API_KEY`, else from the `Authorization` header the tool sends; it is never shown,
logged or written in clear. When the bridge holds the key (keychain or variable), any program on
the machine could otherwise spend it: each tool must then send the bridge's **local token** as its
API key (`alias-pii key token` shows it; it is created once and kept in the keychain), and a
request without it gets 401. Mistral still receives the real key, never the token.

### In a container

```
docker build -f Dockerfile.bridge -t alias-bridge .
docker run --rm -p 127.0.0.1:8001:8001 --env-file bridge.env alias-bridge
```

The image holds the `serve` extra (no PyTorch) and the published model, downloaded at build
time: nothing is fetched at run time. There is no keychain in a container, so `bridge.env`
(never committed) gives `MISTRAL_API_KEY` and `ALIAS_TOKEN`, the local token tools send as their
API key (32 characters or more: `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
The bridge listens on every interface inside the container only with both set; publish it on
127.0.0.1. A tool in another container that reaches it by name (`http://alias-bridge:8001/v1` in
a compose file) needs that name in `ALIAS_ALLOWED_HOSTS` (comma-separated), since the bridge
refuses unknown `Host` names. `alias-pii fetch` downloads the model ahead of time outside a
container too.

The development version runs from a clone with
`uv run --extra app --extra model python -m alias_pii.bridge --model <checkpoint>` (PyTorch).

### The macOS app

Releases after 0.3.0 attach `Alias_<version>_aarch64.dmg` (Apple silicon, macOS 13 or later)
and its SHA-256. The app runs the bridge while it is open and stops it on quit; its window shows
whether the bridge runs and with which detector, stores or deletes the Mistral key in the
keychain, and shows the local token to give to tools. It needs no Python: the bridge is bundled
as one executable. The first launch downloads the model like `alias-pii serve`.

The app is not notarized by Apple (ad-hoc signature only), so macOS blocks its first launch:
allow it in System Settings, Privacy & Security, "Open Anyway". The `.dmg` is built and checked
on a GitHub macOS machine by the `macos-app` workflow, which launches the app, waits for its
bridge to answer with the model, then quits it and checks the bridge stopped.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8001/v1", api_key="<alias-pii key token>")
answer = client.chat.completions.create(
    model="mistral-small-latest",
    messages=[
        {
            "role": "user",
            "content": "Résume la lettre de Jean Dupont, IBAN FR76 3000 6000 0112 3456 7890 189.",
        }
    ],
)
print(answer.choices[0].message.content)  # Mistral saw [PERSON_1] and [IBAN_1]; you see the values
```

## How it behaves

- **Conversations**: one alias table per request, aliases given in order of appearance. A tool
  resends the whole history at each turn, so a value keeps its alias from turn to turn and the
  bridge keeps no state. Once a value has an alias, every other whole-word occurrence of it in
  the request (any case) gets the same alias, even where the detector missed it.
- **Message parts**: the text of `content`, or of its `{"type": "text"}` parts, is masked.
  An image may only come inline (`image_url` holding `data:image/...;base64,...`) and passes as
  it is: neither what it shows nor its metadata (author, location) is masked. An image given by
  URL is refused (400), since the URL itself could hold a name or an address.
- **Nothing unmasked goes through**: besides `messages` (keys `role`, `content`, `prefix`), a
  request may only hold settings without text of their own (`model`, `temperature`, `top_p`,
  `max_tokens`, `random_seed`, `n`, `presence_penalty`, `frequency_penalty`, `safe_prompt`,
  `stream`, `stop`, `response_format` of type `text` or `json_object`). Anything else (a message
  `name`, `prediction`, a JSON schema, `user`, another part type, an image URL) is refused (400)
  rather than sent unmasked. A `stop` sequence holding personal data is refused too (422).
- **Check before sending**: if the rules still find an IBAN or a national ID in the masked text,
  or an IBAN, national ID or phone number of the request is still readable with other
  separators (`01.99.00.12.34` for `01 99 00 12 34`), the request is refused (422) and nothing
  is sent.
- **Restoring**: only the aliases of this request get their value back; an alias the answer
  invents is left as it is. Headers `X-Alias-Masked` and `X-Alias-Restored` give the counts, and
  `X-Alias-Detector` the detector.
- **Links stay masked**: restored inside a link or an image, a value would leave the machine,
  for example if the answer follows instructions hidden in a pasted document. Markdown and HTML
  have too many forms to follow one by one, so the bridge errs on the side of masking:
  - from a link or URL mark (`](`, `//`, `www.`) to the end of its paragraph, aliases keep their
    alias form; the text before the mark (link text included) and other paragraphs get the
    values back;
  - from the first image (`![`), `<` followed by anything but a space, `=` or a digit, or
    backslash, nothing more is restored: an image is fetched as soon as it is shown, an HTML
    block can run across blank lines, and a client decoding the answer as JSON, JSON5 or YAML
    turns escapes into marks;
  - with a reference definition (`]:`) anywhere, nothing is restored: an image anywhere can use
    it, and its label may hold an alias;
  - an answer holding a JSON object or array (the whole answer, a ```json block or JSON within
    the text) gets nothing back when a mark can be formed from its strings: a client may take
    the JSON out, join its strings with or without the keys and in any order. So a string
    holding a mark, ending with `<`, or ending with the start of a mark (`]`, `/`, `w`) while
    another starts with its end (`(`, `:`, `/`, `.`) blocks every restore.

  The bridge cannot follow every transformation a tool applies before display. It protects the
  answer as returned and the strings of the valid JSON it holds. It does not cover a tool that
  repairs invalid JSON (a raw tab in a string, a missing closing brace, a trailing comma, as
  some lenient parsers do), then joins its strings and renders them as markdown, nor the items
  of a YAML list joined the same way: show such output as text, or turn off remote images. The
  cost: an answer with code (a backslash, `List<String>`), an image, or a line such as
  `[PERSON_1]: director` (a valid reference definition) comes back with aliases left in place
  after that point, or everywhere for the definition. `X-Alias-Restored` then counts fewer
  aliases than the answer mentions.
- **JSON answers** (`response_format`): values go back inside the JSON string values, so the
  JSON stays valid whatever they hold; keys keep their aliases.
- **Answers in parts** (a list of `text`, `thinking`... parts): the `text` parts get their
  values back, unless their joined text holds a link mark; other parts keep their aliases.
- **Errors**: Mistral unreachable or answering something that is not a JSON object gives 502, no
  answer within 120 s 504; a request body over 20 MB (inline images included) gives 413, counted
  as it arrives. Mistral's own errors are relayed as they are: they only hold masked text.
- **Local tools only**: the bridge spends the user's key, so a web page must not reach it. A
  request with an `Origin` header (sent by browsers, not by SDKs or scripts), a non-local `Host`
  (DNS rebinding) or a body that is not `application/json` is refused (403, 415).
- **Streaming** (`"stream": true`): the bridge asks Mistral for the whole answer, restores it
  like any other, then sends it back as server-sent events in Mistral's chunk format, ending
  with `[DONE]`. The text arrives all at once rather than word by word: the link rules need the
  whole answer (a definition at the end changes what may be restored at the start), so a
  streamed answer is restored exactly as a non-streamed one.
- **Not yet**: tool calls (`tools`, `tool_calls`: refused with 501, since their arguments would
  go unmasked) and embeddings.
- **Edge case**: an alias-shaped token typed in a later message (`[PERSON_1]` written by hand
  after the bridge gave that alias in an earlier message) is never restored, as in `restore`.
- **Measure against the real API**: `alias_pii.measure_bridge` sends fictitious documents through
  the bridge to Mistral and reports counts only (values leaked, aliases kept by the model and
  restored, tokens, cost, time added); it runs by hand on GitHub (`bridge-measure` workflow, key
  in the protected environment `mistral`), within a token budget. First run (2026-11-12, 50
  documents of the synthetic validation split, `mistral-small-latest`, asked for a summary):
  none of the 203 personal values reached Mistral in clear; of the 208 aliases sent, Mistral
  kept 178 in its summaries and all 178 came back restored, with no alias left in any answer;
  17,258 tokens in all; the bridge added 0.12 s per document (median). Record:
  [results/bridge-measure-2026-11-12.json](../results/bridge-measure-2026-11-12.json). On
  synthetic text the detector misses little; on real text it misses more (docs/RESULTS.md), and
  what it misses reaches Mistral in clear.
- <a id="limits"></a>**Limits**: no detector is perfect; what the detector misses (a name it
  does not recognise) reaches Mistral in clear. The leak rates measured so far are in the README.
- **Outside the entity types**: payment card numbers are not detected, nor any value outside the
  eight entity types (person, address, e-mail, phone, IBAN, national ID, birth date, file
  number); they pass to Mistral in clear.
