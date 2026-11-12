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

## Run it (development version)

```
uv run --extra app --extra model python -m alias_pii.bridge --model <checkpoint>
```

The checkpoint can also come from `ALIAS_MODEL`. Without a model the bridge does not start: the
rules alone mask e-mails, phone numbers, IBANs, national IDs, file numbers and dates of birth
announced as such, but no names or addresses. `--rules-only` starts it that way on purpose,
with a warning in the log. `GET /health` and the `X-Alias-Detector` header of each answer name
the detector in use (`rules+model` or `rules`).

The Mistral key comes from `MISTRAL_API_KEY`, or else from the `Authorization` header the tool
sends. The packaged command (`alias-pii serve`, key in the macOS keychain, ONNX detector without
PyTorch), the Docker image and the macOS app come next.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8001/v1", api_key="unused-if-the-bridge-has-one")
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
- **Not yet**: streaming answers (`"stream": true` is refused with 501 until the next version),
  tool calls (`tools`, `tool_calls`: refused with 501, since their arguments would go unmasked)
  and embeddings.
- **Edge case**: an alias-shaped token typed in a later message (`[PERSON_1]` written by hand
  after the bridge gave that alias in an earlier message) is never restored, as in `restore`.
- <a id="limits"></a>**Limits**: no detector is perfect; what the detector misses (a name it
  does not recognise) reaches Mistral in clear. The leak rates measured so far are in the README.
- **Outside the entity types**: payment card numbers are not detected, nor any value outside the
  eight entity types (person, address, e-mail, phone, IBAN, national ID, birth date, file
  number); they pass to Mistral in clear.
