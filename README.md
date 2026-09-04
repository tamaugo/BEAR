# eBay Car Part Pipeline

Identifies car parts from photographs and prices them against live eBay.co.uk listings.
Three AI agents chained through the [`pi`](https://pi.dev) agent harness — there is no custom
backend, and **each agent's `.md` file *is* its system prompt.**

Status: **working end to end.** A full run on the 9-photo test set produces correctly formatted,
correctly priced output with real eBay data.

## The three agents

| Agent | Job | Model |
|---|---|---|
| **1 — Part Reader** | Reads OEM part numbers off photographs. Absolute confidence or a clean fail; never guesses. | `google/gemini-3.1-flash-lite` |
| **2 — eBay Lookup** | Searches eBay.co.uk for each number. UK sellers, exact match, active listings. **Fetches only — never alters the data.** | `meta/muse-spark-1.3:minimal` |
| **3 — Compiler** | Owns *every* transformation: strips vehicle names and seller noise, normalises part numbers, applies pricing rules, writes the output file. | `meta/muse-spark-1.3:minimal` |

That division of labour is deliberate. Keeping all text rules in Agent 3 means running a different
vehicle only ever requires changing Agent 3's rule set.

## Layout

```
agents/          canonical instruction files (the live system prompts)
  archive/       every previous version, kept for history
tests/
  photos/        the 9 test photographs
  fixtures/      dummy inputs and expected outputs
  results/       output from the live run
  ground-truth.md  what each photo should produce
tools/           cost model
harness/         the pi installation — internal layout must not be reorganised
```

`harness/.pi/agents/` holds working copies of the three agent files, kept in sync with `agents/`.
Only their changelog footers differ.

## Running it

```bash
cd harness
cp -n ../tests/photos/* photos/ 2>/dev/null || true   # first run only
export EBAY_APP_ID="..." && export EBAY_CERT_ID="..."
pi
```

Then `/run-pipeline` inside the session. Outputs land in `harness/output/`.

**Launch with no flags.** Do not pass `-ne` (it strips the `subagent` tool the pipeline needs) or
`--tools` (a strict allowlist that would disable the built-in read/write tools).

## Configuration that is load-bearing

Two files outside this repo make the pipeline work. Reference copies are in
`harness/pi-config-reference/`; recreate them on a new machine.

- **`~/.pi/agent/models.json`** — caps `meta/muse-spark-1.3` at 16,384 max output tokens. Without
  it, pi requests the model's advertised 943,718-token ceiling, which exceeds a typical OpenRouter
  key limit and returns a 402 before any work happens.
- **`harness/.pi/settings.json`** (tracked) — force-unloads the global `pi-interactive-subagents`
  extension for this project. It and the harness both register a tool called `subagent`, and pi
  refuses to start on a duplicate. Do **not** fix this by uninstalling the global package.

## Gotchas worth knowing before you change anything

- Agent frontmatter **must** have both `name:` and `description:`. The loader silently skips any
  file missing either, so the agent simply does not exist.
- `tools:` must be a bracket-less comma-separated string (`tools: a, b`), never a YAML array — the
  parser produces an array, but the consuming code calls `.split(",")` on it.
- **Every agent needs an explicit `tools:` line.** Without one it inherits every tool including
  `subagent`, and will recursively delegate its own job to itself.
- Avoid `meta/muse-spark-1.2` with a thinking suffix: its reasoning endpoint requires account-wide
  paid-model training. `claude-haiku-4.5` is Batch-API-only on this account.

## Known limitations

Active listings only — sold-price data needs eBay Marketplace Insights, which is not approved.
`getRateLimits` is a stub. Cost scales quadratically with batch size, because each agent processes a
whole batch in one conversation; chunking at ~10 parts would fix it and is deferred. Part location
is inferred from seller-written text and is not reliable.
