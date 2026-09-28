# tools/

## Jev (OpenRouter Decisions API) smoke test

`jev_client.py` is a stdlib-only client for OpenRouter's Decisions API
(`POST https://openrouter.ai/api/alpha/decisions`), which the pipeline will use to
route part-number/listing/name-cleaning decisions through the `typesafe/jev-1.13`
model instead of free-text prompting. `jev_questions.py` builds the three
pipeline-specific question sets (one per agent stage); `jev_client.py` itself only
knows how to send a request and parse the response.

### Setup

Copy `.env.example` to `.env` in the repo root and fill in `OPENROUTER_API_KEY`
(never commit `.env` -- it's gitignored). The client checks the real shell
environment first, then falls back to `.env`.

### Running the smoke test

```
python3 tools/jev_client.py --state '{"ticket":"test"}'
```

`--state` takes a JSON string (object, array, or plain string) -- whatever content
you want Jev to evaluate. If omitted, a small placeholder state is used instead.
`--model` overrides the model (default: `typesafe/jev-1.13`).

The smoke test sends a single cheap `noul` question ("does the state contain any
content at all?") -- just enough to prove the API key, network path, and response
parsing all work, without needing any real pipeline data.

### Output fields

```
model:      typesafe/jev-1.13-20260917     # exact model snapshot that answered
request id: gen-dec-...                    # OpenRouter's id for this request
answer[state_is_nonempty]: {'type': 'noul', 'noul': 0.98}
usage.cost: $0.000020                      # actual $ billed for this one request
```

Each entry under `answer[...]` is the raw answer object for that question key.
Its shape depends on the question's `type`:

- **noul** -- `{"noul": <float 0-1>}`. A yes/no-style probability; no confidence
  or probabilities fields.
- **choice** -- `{"choice": <string>, "confidence": <float>, "probabilities": {...}}`.
  `choice` is the winning option key from that question's `criteria`; `probabilities`
  gives every option's probability, `confidence` is the winning option's own value.
- **score** -- `{"score": <float>, "confidence": <float>, "legend": {...},
  "probabilities": {...}}`. `score` is a 0-based index into the question's ordered
  `criteria` list (not literally "N out of 10"); `legend` maps each index back to
  its criteria text so you can read the result without recomputing the mapping.

`usage.cost` (top-level, alongside `input_tokens`/`output_tokens`) is the real
dollar cost of that one request, as billed by OpenRouter.

### Errors

- **401** -- the API key is missing or wrong. Fails immediately, no retry.
- **402** -- the OpenRouter account is out of credits. Fails immediately, no retry.
- **429 / 5xx** -- retried up to 3 times with exponential backoff (1s, 2s, 4s)
  before raising.
