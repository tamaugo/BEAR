# BEAR-Jev Pipeline Spec — v2 (2026-09-28)

The car-parts pipeline after the Jev integration. This replaces the cost/
model portions of the original pipeline overview; all agent behaviour rules
still live in the agents/ instruction files (the source of truth for *how*
each stage works — this document covers *what runs, what it costs, and what
it returns*).

---

## 1. The stack

| Stage | Model (OpenRouter) | Role | Pricing (live, 2026-09-28) |
|---|---|---|---|
| Agent 1 — Part Reader | `google/gemini-3.1-flash-lite` | Vision: extract EVERY candidate number off each photo (generous, no fail-on-doubt) | $0.25 / $1.50 per MTok |
| **Jev — Part Decision** | `typesafe/jev-1.13` via `jev_decide` | `choice` over Agent 1's candidates + `noul` format check; confidence < 0.60 → fail line | $0.042/MTok input, **output free** |
| Agent 2 — eBay Lookup | `mistralai/mistral-nemo` | Mechanic: `ebay_search` per part number, Step A condition filter, Step B consensus/median price | $0.019 / $0.030 per MTok |
| **Jev — Listing Resolve** | `typesafe/jev-1.13` via `jev_decide` | `choice` among price-carrier listings only; supplies name+URL; falls back to clearest-title on error/low confidence | as above |
| Agent 3 — Compiler | `qwen/qwen3.8-flash` (no suffix) | Text transformation per the tuned v4 prompt; deterministic post-validator runs on its file afterwards | $0.15 / $0.47 per MTok |

Failure semantics are unchanged end-to-end: the three failure strings keep
their exact wording and field shapes; Agent 2/3's pipe contracts are
byte-identical to v4; `make_xlsx.py` untouched.

## 2. What changed vs the original pipeline

1. **Agent 1 no longer judges.** It extracts all plausible numbers; Jev picks
   the genuine OEM part number with calibrated confidence (0.99 on the
   reference case). The old "any doubt → fail" rule (which threw away good
   photos) became a threshold, not a guess.
2. **Agent 2 no longer resolves.** The market-facing price rule (Step A/B)
   stays deterministic; only the listing *selection* moved to Jev, restricted
   to listings already carrying the consensus price — the £12.95-vs-£181.49
   bug class is now structurally impossible, not just discouraged.
3. **Agent 2's model dropped 60×** ($1.25 → $0.019 input): the judgment left
   with Jev, so the remaining job is tool mechanics — a tiny model suffices
   (live-verified at $0.0004/job for 10 parts).
4. **Agent 3's model dropped ~8×** ($1.25 → $0.15 input) *and* got more
   accurate: fixture-validated 15/15/15/15 after the tuned prompt
   (three worked examples diagnosed from cross-model failure data) +
   `tools/agent3_validator.py`, which repairs deterministic slips
   (sort, row-shift remap, price floor/format) and marks anything needing
   human eyes. An agent with no failstate now has a mechanical safety net.
5. **Jev replaces ~3 judgment calls per part** that used to burn reasoning
   tokens on the expensive model, at ~$0.00002 per decision.

## 3. Cost model (all arithmetic in `tools/cost_model_jev.py`)

Full-pipeline LLM spend per job (Agent 1 + Agent 2 + Jev + Agent 3, cached
realistic case, GBP at $0.79):

| Job size | Agent 1 | Agent 2 | Jev | Agent 3 | **Total** | **Per part** |
|---|---|---|---|---|---|---|
| 10 parts | $0.0044 | $0.0004 | $0.0003 | $0.0016 | **$0.0066 (£0.005)** | £0.0005 |
| 35 parts | $0.0143 | $0.0012 | $0.0009 | $0.0021 | **$0.0185 (£0.015)** | £0.0004 |
| 60 parts | $0.0243 | $0.0020 | $0.0015 | $0.0026 | **$0.0304 (£0.024)** | £0.0004 |
| 80 parts | $0.0322 | $0.0027 | $0.0020 | $0.0029 | **$0.0398 (£0.032)** | £0.0004 |

Note the shape change: cost now scales **linearly** with batch size (the old
sequential conversation re-sent its transcript and grew quadratically; the
remaining quadratic component lives on a $0.019/MTok model, so it no longer
matters). Agent 1 is now the biggest line item — vision tokens are the main
thing you pay for.

**Old vs new (the stages the fork changed, Agent 2+3+Jev vs old Agent 2+3):**

| Job size | Old (muse 1.3 ×2) | New (nemo + qwen + Jev) | Saving |
|---|---|---|---|
| 10 parts | £0.053 | £0.002 | 29.9× |
| 35 parts | £0.231 | £0.003 | 70.1× |
| 60 parts | £0.524 | £0.005 | 108.8× |
| 80 parts | £0.842 | £0.006 | 139.4× |

The saving *widens* with batch size because the old stack's quadratic term
sat on the expensive model.

## 4. Return on investment

Same formula as before, same £28.00 return per priced part-batch:

```
Net Profit = £28.00 − spend
ROI        = (Net Profit ÷ spend) × 100
```

| | Spend | Net profit | ROI |
|---|---|---|---|
| **Original pipeline** (the 60p reference) | £0.60 | £27.40 | **4,566.67%** |
| **BEAR-Jev, 80-part job** | £0.0315 | £27.9685 | **88,788.89%** |
| **BEAR-Jev, 60-part job** | £0.0240 | £27.9760 | **116,566.67%** |
| **BEAR-Jev, 35-part job** | £0.0146 | £27.9854 | **191,680.82%** |

Per 60-part job the LLM spend falls from **60p to ~2.4p** — a **25× cost
reduction** on the pipeline's inference bill, while Agent 3's output accuracy
went *up* (11/15 → 15/15 on the corrected fixture) and the two
highest-stakes judgment calls gained calibrated confidence scores.

(ROI percentages are a ratio artefact at tiny denominators — the honest
one-line summary is: **the same job that cost 60p now costs ~2.4p**, and the
spend is now too small to be a constraint on volume.)

## 5. What is still true from the original spec

- One photo = one part; `NULL` photos are held back by the coordinator and
  never billed a vision or eBay call.
- UK listings only, exact-match only, active listings only.
- eBay free tier: 5,000 calls/day; two searches per part number (raw +
  normalised) ≈ 160 calls for an 80-part job — comfortably within quota.
- `getRateLimits` remains a stub; fine at test volume.
- The operator's vehicle string is passed verbatim; Agent 3 still owns every
  transformation of listing text.
- Cost still scales with batch size — but linearly now, and a 10× batch
  costs ~10× the (tiny) base instead of ~4× per-part inflation.

## 6. Validation status

| Component | Evidence |
|---|---|
| Jev client + question sets | live calls, $0.00002/decision, request IDs logged |
| Agent 1 v9-jev | Jev picked the true OEM number, confidence 0.99 |
| Agent 2 v7-jev | Jev chose used £12.95 over New £181.49 (prob 0) |
| Agent 3 tuned + validator | 15/15/15/15 on corrected fixture; validator repairs verified by self-tests |
| qwen3.8-flash in pi | CONFIRMED clean (test prompt, 2026-09-28) |
| Full pipeline end-to-end | **pending — first real Mac run** |

*All prices from OpenRouter's public models API on 2026-09-28; re-run
`tools/cost_model_jev.py` (adjust `PRICES`) whenever models or prices change.*
