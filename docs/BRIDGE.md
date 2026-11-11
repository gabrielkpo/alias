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
  images and other parts pass as they are.
- **Check before sending**: if the rules still find an IBAN or a national ID in the masked text,
  the request is refused (422) and nothing is sent.
- **Restoring**: only the aliases of this request get their value back; an alias the answer
  invents is left as it is. Headers `X-Alias-Masked` and `X-Alias-Restored` give the counts.
- **JSON answers** (`response_format`): values go back inside the JSON strings, so the JSON stays
  valid whatever they hold.
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
