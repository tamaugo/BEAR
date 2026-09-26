# BEAR

This is an autonomous researching eBay agent stack that gathers price data and name all from a car parts part number

## Overview

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
BEAR
```

That is the whole thing. **B**atch **e**Bay **A**gentic **R**etrieval — it cds into the harness,
loads the eBay credentials, pre-flights the known failure modes and starts pi inside tmux. Then type
`/run-pipeline` in the session. Outputs land in `harness/output/`.

`BEAR check` runs the pre-flight without launching. `BEAR raw` skips tmux.

**Launch with no flags** if you ever start pi by hand. Do not pass `-ne` (it strips the `subagent`
tool the pipeline needs) or `--tools` (a strict allowlist that would disable the built-in read/write
tools the orchestration uses).

### Setting BEAR up on a new machine

The function itself lives in `tools/bear.zsh` and is version controlled, but the hook that activates
it is a line in `~/.zshrc`, which is not. On a fresh clone you need both steps.

**1. Source it from your shell profile.** Adjust the path if the repo is not on your Desktop:

```bash
echo 'source "$HOME/Desktop/ebay-pipeline/tools/bear.zsh"' >> ~/.zshrc && source ~/.zshrc
```

**2. Store the eBay credentials once, in the macOS Keychain.** Each command prompts silently, so the
secret never appears on screen or in shell history:

```bash
security add-generic-password -a "$USER" -s ebay-app-id  -w
security add-generic-password -a "$USER" -s ebay-cert-id -w
```

BEAR loads them into the environment on every launch, so they do not need re-exporting per terminal
tab — and child agents inherit them from pi, which they must. Keychain is used rather than a
plaintext line in `~/.zshrc` deliberately: this repo is public, and secrets should not sit in a
dotfile that might get shared or backed up.

To replace a stored value, delete it first — `add-generic-password` will not overwrite silently:

```bash
security delete-generic-password -a "$USER" -s ebay-cert-id
```

Use `EBAY_APP_ID` / `EBAY_CERT_ID` environment variables instead if you ever want a one-off run with
different keys; an explicit export always beats the Keychain.

**Caveat:** the `source` line hard-codes a path. Move this folder and `BEAR` silently stops working
until `~/.zshrc` is updated.

### What the pre-flight checks

Not generic health checks — these are the four things that have actually broken this project:

- **eBay credentials present in the launching shell.** Warns if the App ID looks like the 36-char
  Dev ID, or the Cert ID is not `PRD-` prefixed. Reports lengths only, never values.
- **`~/.pi/agent/models.json` output-token cap** — without it every Agent 2 and 3 call returns a 402.
- **The subagent extension collision fix** in `.pi/settings.json` — without it every spawned agent
  dies silently with `(no output)`.
- **Harness and agent files present and parseable.**

A failed pre-flight stops rather than launching into a run that would die partway through.

## Real job data

Real customer photographs and job output live **outside this repo**, at `~/Desktop/ebay-jobs/`, one
folder per vehicle. That separation is deliberate: this repo goes to GitHub, and customer data must
not follow it there. See that folder's README for the job convention and pre-run checklist.

Only the 9-photo test set in `tests/photos/` belongs in version control.

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
