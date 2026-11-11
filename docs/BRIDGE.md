# Alias Bridge: your tools talk to Mistral, Mistral never sees the personal data

The bridge is a local endpoint with the same API as Mistral's chat completions. A tool written
for Mistral (a script, the `mistralai` or `openai` SDK, LibreChat, n8n…) keeps its code and only
changes its base URL:

```
https://api.mistral.ai/v1   ->   http://127.0.0.1:8001/v1
```

For each `POST /v1/chat/completions` the bridge masks every message, checks that no checksummed
value (IBAN, national ID) is still readable, forwards the request to Mistral with the user's
key, then puts the real values back in the answer. Nothing but counts is logged.

## Run it (development version)

```
uv run --extra app --extra model python -m alias_pii.bridge --model <checkpoint>
```

The Mistral key comes from `MISTRAL_API_KEY`, or else from the `Authorization` header the tool
sends. The packaged command (`alias-pii serve`, key in the macOS keychain, ONNX detector without
PyTorch), the Docker image and the macOS app follow (framing: brain `projets/cadrage-alias-bridge`).

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
  bridge keeps no state.
- **Message parts**: the text of `content`, or of its `{"type": "text"}` parts, is masked;
  `image_url` parts pass as they are.
- **Nothing unmasked goes through**: besides `messages` (keys `role`, `content`, `prefix`), a
  request may only hold settings without text of their own (`model`, `temperature`, `top_p`,
  `max_tokens`, `random_seed`, `n`, `presence_penalty`, `frequency_penalty`, `safe_prompt`,
  `stream`, `stop`, `response_format` of type `text` or `json_object`). Anything else (a message
  `name`, `prediction`, a JSON schema, `user`, another part type) is refused (400) rather than
  sent unmasked. A `stop` sequence holding personal data is refused too (422).
- **Check before sending**: if the rules still find an IBAN or a national ID in the masked text,
  the request is refused (422) and nothing is sent.
- **Restoring**: only the aliases of this request get their value back; an alias the answer
  invents is left as it is. Headers `X-Alias-Masked` and `X-Alias-Restored` give the counts.
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
  - a JSON document (in JSON mode, or an answer that is a JSON object or array) holding a mark
    anywhere, once its strings are joined, gets nothing back: a client may join its strings or
    show them in another order.

  The bridge cannot follow every transformation a tool applies before display (joining the items
  of a YAML list, for example); it protects the answer as returned and its JSON strings. The
  cost: an answer with code (a backslash, `List<String>`), an image, or a line such as
  `[PERSON_1]: director` (a valid reference definition) comes back with aliases left in place
  after that point, or everywhere for the definition. `X-Alias-Restored` then counts fewer
  aliases than the answer mentions.
- **JSON answers** (`response_format`): values go back inside the JSON string values, so the
  JSON stays valid whatever they hold; keys keep their aliases.
- **Local tools only**: the bridge spends the user's key, so a web page must not reach it. A
  request with an `Origin` header (sent by browsers, not by SDKs or scripts), a non-local `Host`
  (DNS rebinding) or a body that is not `application/json` is refused (403, 415).
- **Not yet**: streaming answers (`"stream": true` is refused with 501 until the next version),
  tool calls (`tools`, `tool_calls`: refused with 501, since their arguments would go unmasked)
  and embeddings.
- **Edge case**: an alias-shaped token typed in a later message (`[PERSON_1]` written by hand
  after the bridge gave that alias in an earlier message) is never restored, as in `restore`.
- **Limits**: no detector is perfect; what the detector misses (a name it does not recognise)
  reaches Mistral in clear. The leak rates measured so far are in the README.
