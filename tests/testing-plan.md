# Testing plan and cost analysis (2026-10-08)

How we use the TEST MATERIAL photo set to improve BEAR, what it costs, and the order
to do things in. Written before any testing starts.

## The test set

- Source: `~/Downloads/TEST MATERIAL /` on the owner's Mac (operator data, never commit
  the photos).
- 42 folders, 2,645 photos (2.3 GB), 8 vehicles: Shogun x9 folders, M6 x8, i40 x8,
  Partner x6, S-Max x5, Focus x4, A4 x1, DS4 x1. Folder name = location, vehicle code,
  date (e.g. `Q260 FFOCUSMK3-3 26-09`).
- About 1,500 photos are expected to show a part; the rest are other angles.
- Not every folder will be used. The set is most valuable kept as a library for testing
  new cases later (new vehicles, new part types, new rules), not only for one big run.

## What it costs

### BEAR (API spend, paid by the owner)

Measured from `bear2/spend.jsonl` (13 runs, 2-7 Oct 2026):

| Setup | Per photo | 1,000 photos | All 1,500 part photos |
|---|---|---|---|
| Default | $0.0015-0.0022 | about $2 | about $3 |
| Beta (Luna photo check) | about 26% less | about $1.50 | about $2.20 |
| Model comparison run (several models on the same photos) | $0.009-0.014 | about $10-14 | about $15-20 |

- Most of the spend is the photo read (Gemini Flash Lite), then the photo double-check.
  Jev, name cleaning and eBay image matching are close to free.
- The per-run cap is $1 (`BEAR_RUN_CAP_USD`). That covers about 450 photos on Default,
  so folder-by-folder runs are fine; raise the cap for one big run.
- A testing programme of ~50 iterations (quick set plus confirmations) is roughly
  $30-60 of API spend. This is the cheapest part of the work.

### eBay (free, but rate limited)

- Each photo uses roughly 10-15 eBay searches. A pass over 1,500 photos is about
  15,000-22,000 calls.
- The free tier is about 5,000 calls a day (confirm with the Analytics API
  `getRateLimits`). The free Application Growth Check can raise it.
- Results are cached for 24 hours, so re-running a folder the same day is nearly free.
  Plan on about 300-400 new photos a day until the frozen eBay copy below exists.

### AI assistant (subscription)

- Claude Pro is $20/month. Claude chat and Claude Code share one allowance that
  refills every 5 hours, with a weekly cap. Max is $100 (5x Pro) or $200 (20x).
- ChatGPT Plus is $20/month and includes Codex, which reads this repo's `AGENTS.md`, so
  the same branch/PR rules apply. T3 Code can hand tasks from a Claude chat to Codex.
- Decision: **stay on Pro + ChatGPT Plus ($40/month) for now.** The ~£100 Max tier only
  if the owner's boss pays for it. On Pro the loop does not break when the allowance
  runs out; it pauses until the reset.
- Keep assistant usage low: the assistant never looks at photos. BEAR's cheap models
  read photos; the assistant reads score tables and the specific failures.

## The plan, in order

1. **Answer key first.** "Is the output equal to the expected output" needs expected
   outputs. Today only the i40 set has one
   (`tests/fixtures/ground_truth_hyundai_i40_2026-09-30.json`, about 18 photos).
   Run BEAR on Default over a trimmed batch, then the owner corrects the spreadsheet
   (right/wrong, correct part number) like the i40 PDF. Start with 200-300 photos
   across all 8 vehicles; grow it over time.
2. **Frozen eBay copy for tests.** Listings and prices change daily, so two runs on
   different days are not comparable. Test runs reuse a saved copy of the eBay results.
   This also removes the eBay daily-limit problem after the first pass.
3. **Two photo sets.** A quick set (~200 photos, ~$0.40 a run) for trying ideas, and a
   held-back set used only to confirm a winner, so prompts are not tuned to these exact
   photos.
4. **Allow for luck.** Model answers vary run to run (the i40 test moved between 16/18
   and 17/18). Only call a change a win when the difference is bigger than that noise:
   larger set or repeat runs.
5. **One-command test runner.** Runs BEAR on a set, scores it against the answer key
   (extends `bear2/score.py`), and appends one line to an experiment log: what changed,
   accuracy, cost, kept or rejected. The assistant reads only that log and the failures.
   The log is the memory between chats, so each new chat picks up where the last left off.
6. **The loop.** Try one change (rule, prompt in `agents/*.md`, model) on the quick set.
   Keep it only if accuracy is equal or better and it is no more expensive; cheaper with
   equal accuracy wins. Confirm on the held-back set before it becomes the default.
   Lower accuracy is an experiment only, never the default.

## Status

- 2026-10-08: plan written. Owner is running BEAR on a trimmed batch of three folders to
  start the answer key.
