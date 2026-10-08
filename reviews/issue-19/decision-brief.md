# Issue 19: part-name cleanup and a reusable resilience framework

Status: consultation draft, 8 October 2026. No option is preferred or selected. This document proposes behavior; it does not change BEAR's runtime or close the issue.

## What happened and why

[Issue 19](https://github.com/tamaugo/BEAR/issues/19) reports messy names after the Mitsubishi Shogun job `part-numbers-20261008-163403`. Qwen's provider returned HTTP 429 through the retries. The code then continued with a mechanical name cleaner designed around Hyundai/i40 vocabulary.

The chain is: one batch name request → exhausted retries → empty names map → `safe_name` mechanical fallback → spreadsheet export. The fallback removes digit-bearing words but leaves punctuation, and its vehicle removal list is specific to Hyundai/i40. An isolated execution of the existing fallback on illustrative titles reproduced:

| Illustrative title | Existing fallback result |
|---|---|
| MITSUBISHI SHOGUN PAJERO 2.8 RELAY OMRON #233 | Mitsubishi Shogun Pajero . Relay Omron # |
| VAUXHALL CORSA D STARTER MOTOR BOSCH 1.3 SXI CORSA 566800 | Vauxhall Corsa D Starter Motor Bosch . Sxi Corsa |
| MITSUBISHI SHOGUN BUZZER RELAY PAJERO 2.8 GLS TD 125BHP | Mitsubishi Shogun Buzzer Relay Pajero . Gls Td |

The first two illustrative strings reproduce the reported symptoms; they are not a transcription of the complete original listing titles. Luna research also located the saved job's messy exported names. The issue separately reports a possibly wrong starter-motor match. Name cleanup cannot establish whether that listing or part number is correct; that needs a separate matching investigation. A generic relay being listed for another vehicle can be legitimate, so do not discard a listing just because its title mentions another make.

Both Default and Luna/Beta currently share the same Qwen name cleaner. Luna/Beta changes the weak-photo check, with Gemini as its existing fallback. A names-only repair therefore applies to both setups. Closed, unmerged [PR 18](https://github.com/tamaugo/BEAR/pull/18) contains a previous Gemini-backup/mechanical-clean proposal and a reported 18-row validation; it is reference evidence, not an approved implementation or proof of quality on every vehicle.

There is another current failure path: an HTTP-successful JSON response can contain a non-map `names`, missing IDs, or non-string values. The existing code does not fully validate this shape, and some shapes can crash export. Every option must define how invalid or partial results are handled.

Code evidence: `bear2/assemble.py:58-87,98-114`; `bear2/common.py:143-188`; `bear2/configs.py:13-31`; `bear2/stage2b_rescue.py:88-126`. The retry loop makes six attempts; normally 60 seconds of HTTP-error backoff, with each Retry-After-adjusted delay capped at 30 seconds, plus request durations. Longer waiting alone cannot repair a sustained upstream outage.

## Price assumptions and evidence

The owner's reference totals for 20 photos are **Default $0.050000** and **Luna $0.037000**, computed as $0.05 × 0.74. These are supplied reference figures, not newly measured controlled runs. Costs below cover model inference only: human review, implementation effort, hardware, and any funding/tax fees are not priced.

Published standard rates checked on 8 October 2026:

| Model | Input per 1M tokens | Output per 1M tokens | Illustrative 20-name batch |
|---|---:|---:|---:|
| [Qwen 3.8 Flash](https://openrouter.ai/qwen/qwen3.8-flash) | $0.15 | $0.47 | $0.000441 |
| [Gemini 3.1 Flash Lite](https://openrouter.ai/google/gemini-3.1-flash-lite) | $0.25 | $1.50 | $0.000950 |

The illustration assumes **one batch of 20 successful listing titles**, **2,000 input tokens total including prompt/examples**, and **300 billed output tokens total**. It assumes no cache discount, extra reasoning, request charges, or provider premium. Twenty photos can yield fewer than twenty successful listings; title lengths and actual outputs vary. Input/output volumes are assumptions, not measured token counts. The current `max_tokens=3000` is not the assumed output use; if all 3,000 tokens were billed, Gemini's output alone would cost $0.0045. Verify actual billed reasoning and supported parameters before adoption.

Formula: `(input tokens × input rate + billed output tokens × output rate) / 1,000,000`. Batch Qwen `Q=$0.000441`; batch Gemini `G=$0.000950`. For each setup, `multiple=new total/reference total` and `percentage=(multiple−1)×100`.

Replacement/savings illustrations assume the supplied baseline contains one modeled successful Qwen cleanup of Q. The baselines are not itemized, so this subtraction is an assumption. Recovery illustrations conservatively add the new call to the reference without giving credit for the failed primary. A pure 429 may not produce a billed completion; timeouts can leave billing uncertain. Failed attempts are absent from BEAR's local success ledger, so it cannot establish their charges. These illustrations are neither spending ceilings nor probability forecasts.

Local evidence: `bear2/spend.jsonl` contains one Oct 8 Gemini `clean_names` success charged **$0.00060125**, and Qwen successes charged $0.00028666 and $0.00011514 that day. The ledger does not record token counts or establish that these tests used exactly 20 names. Do not label $0.00060125 as a measured 20-photo price. Failed-attempt/provenance instrumentation needs improvement before making reliability or savings claims.

## Six options for the owner

The options can be combined where their behavior is compatible. Each includes a mechanism, benefit, drawback, cost, scope, and verification requirement. Warnings and validation are common requirements, not evidence that an option guarantees good names.

### A. Improve the mechanical fallback

- **Mechanism:** keep Qwen as primary; on outage or invalid names, use a generic vehicle-aware mechanical cleaner and mark affected names for review.
- **Scope:** remove the job's vehicle words, known make/model/trim aliases, exact part number and seller noise; normalize punctuation and repeats; preserve meaningful component words and filename-side rules.
- **Pros:** no extra model calls; local fallback stays available during provider outages; behavior is reproducible and easy to inspect.
- **Cons:** dictionaries need maintenance; unfamiliar models can remain; broad stripping can remove useful component words. Rules cannot reliably resolve ambiguous titles by themselves.
- **Default cost:** $0.050000 per 20 photos, **0% / 1.000000×** reference in the no-extra-call illustration.
- **Luna cost:** $0.037000, **0% / 1.000000×** reference. Unbilled failed cleanup can make actual spending lower; no speculative credit is shown.
- **Quality check:** fixtures for Shogun/Pajero, Corsa, Honda relays, Hyundai/i40, side codes and legitimate numeric component names; flag empty or questionable names rather than inventing a component.
- **Framework fit:** define a tested local degradation path for optional output stages; use different failure rules for critical photo reads and listing checks.

### B. Use Gemini as the primary name cleaner

- **Mechanism:** replace the batch Qwen cleanup call with Gemini 3.1 Flash Lite; validate results, then use a generic mechanical fallback if Gemini fails.
- **Scope:** change only title-to-name cleanup in both setups; keep the reader and the Luna/Default photo-check selection independent.
- **Pros:** avoids the observed Qwen upstream bottleneck; reuses a model already integrated in BEAR; closed PR 18 reports clean examples on the affected job.
- **Cons:** Gemini can also be unavailable; relying on it for photos and names correlates failures; a single successful job does not establish general naming quality.
- **Default cost:** replace Q with G: $0.050509, **+1.018% / 1.010180×** reference.
- **Luna cost:** $0.037509, **+1.376% / 1.013757×** reference. The cleanup itself is **+115.420% / 2.154195×** Qwen in this token illustration; the whole job increases much less.
- **Quality check:** test JSON/ID/string validation, no invented components, preservation of appropriate acronyms and seller component wording, and forced Gemini outages; confirm supported reasoning controls and actual billed tokens.
- **Framework fit:** model replacement is one configurable stage policy; approval depends on evidence and total-run cost, not token rates alone.

### C. Add an application-owned backup model

- **Mechanism:** keep Qwen first, try Gemini after eligible transient failures or invalid output, and finish with generic cleanup plus visible review status when both fail.
- **Scope:** define eligible errors and a bounded total deadline; handle partial outputs per row and retry unresolved names without letting models alter other fields.
- **Pros:** preserves normal Qwen cost/behavior; BEAR can detect semantic/schema failures as well as API errors; another model family offers a second recovery path.
- **Cons:** more policy and adapter code; two models can both fail; repeated successful-but-invalid answers can incur extra charges and latency.
- **Default cost:** healthy $0.050000 (**0% / 1×**); one extra Gemini recovery illustration $0.050950 (**+1.900% / 1.019000×**).
- **Luna cost:** healthy $0.037000 (**0% / 1×**); one extra Gemini recovery illustration $0.037950 (**+2.568% / 1.025676×**).
- **Quality check:** force 429, network failure, malformed JSON, partial maps, wrong types and two-model failure; validate every recovered row and preserve numbers/prices/URLs/images.
- **Framework fit:** explicit per-stage adapters and budgets apply beyond names; never use Chat fallback directly for a Decisions call without a compatible contract and adapter.

### D. Use OpenRouter's managed model fallback

- **Mechanism:** use an ordered Qwen/Gemini `models` list for eligible API-level recovery, followed by BEAR's own schema/name validation and generic local fallback.
- **Scope:** applicable to compatible OpenRouter Chat requests. [Model fallback documentation](https://openrouter.ai/docs/guides/routing/model-fallbacks) covers rate limits and provider failures; it does not validate BEAR's part-name semantics.
- **Pros:** less custom API-error failover code; gateway routing can recover within one client request; model list and provider price limits are configurable.
- **Cons:** both choices still depend on OpenRouter; HTTP 200 bad names need BEAR handling; supported parameter/provider filters can reduce availability; do not assume a second Qwen provider exists.
- **Default cost:** healthy $0.050000 (**0% / 1×**); conservative one-Gemini recovery illustration $0.050950 (**+1.900% / 1.019000×**).
- **Luna cost:** healthy $0.037000 (**0% / 1×**); conservative recovery $0.037950 (**+2.568% / 1.025676×**). If the failed Qwen attempt is unbilled, the modeled replacement total is the same as B, subject to baseline assumptions.
- **Quality check:** verify actual returned model/provider and usage in the ledger, unsupported-parameter behavior, malformed successful outputs and full-gateway outage.
- **Framework fit:** a transport strategy inside the broader stage policy. [Provider price filters](https://openrouter.ai/docs/guides/routing/provider-selection) constrain token rates, not the job's total spending.

### E. Clean mechanically first, then escalate uncertain jobs

- **Mechanism:** apply deterministic cleanup first and call Gemini only when the result is uncertain; the cost illustration escalates the complete title batch for that job.
- **Scope:** use conservative acceptance rules and a maintained evaluation set; label acceptance as a heuristic, not proof that the component is correctly named.
- **Pros:** avoids a model call on jobs accepted locally; model inference focuses on ambiguous cases; simple titles can complete during outages.
- **Cons:** missed ambiguity silently hurts quality unless surfaced; more rules and evaluation work; unseen vehicle words can fool the acceptance test.
- **Default cost:** if an assumed **20% of jobs** escalate, average $0.049749, **−0.502% / 0.994980×** reference. This is not a claim that 20% of rows fail.
- **Luna cost:** average $0.036749, **−0.678% / 0.993216×** reference. At 100% escalation: $0.050509 Default (**+1.018% / 1.010180×**) and $0.037509 Luna (**+1.376% / 1.013757×**).
- **Quality check:** measure false acceptance, escalation frequency and name fidelity across makes before using the assumed frequency for budgeting; the savings formula is `baseline−Q+f×G`.
- **Framework fit:** use cheap deterministic work before optional inference only when its output contract and failure behavior are safe for that stage.

### F. Add visible review and a deferred names-only repair

- **Mechanism:** expose affected rows and cleaning status, retain the paid lookup results, and let the operator approve manual names or rerun only cleanup later; optionally hold names until review.
- **Scope:** visible web/export warning and an auditable repair record. A warning alone leaves names messy; this option manages review rather than guaranteeing automatic immediate cleanup.
- **Pros:** operator can see degradation; preserves the rest of the job; stage-only replay avoids another full photo/read/lookup run.
- **Cons:** delays completion and requires attention; human labor is unpriced; queue state, deduplication and safe atomic export replacement need implementation.
- **Default cost:** warning/manual path $0.050000 (**0% / 1×**, inference only); one extra later Qwen call $0.050441 (**+0.882% / 1.008820×**).
- **Luna cost:** warning/manual path $0.037000 (**0% / 1×**); one extra Qwen replay $0.037441 (**+1.192% / 1.011919×**). Repeated attempts or Gemini replay must be costed separately.
- **Quality check:** verify review visibility, resume after restart, no duplicate billing from duplicate repair actions, and exact preservation of listing identity and filenames.
- **Framework fit:** reusable saved-stage resume and human review controls for degraded results, with stricter holds for critical uncertainty.

## Comparison for the price graph

Each row states its own scenario. These are model illustrations for 20 photos; they are not equally likely forecasts or measured reliability outcomes.

| Option/scenario | Default USD | Change / multiple | Luna USD | Change / multiple |
|---|---:|---:|---:|---:|
| Current reference | 0.050000 | 0% / 1× | 0.037000 | 0% / 1× |
| A: no extra calls | 0.050000 | 0% / 1× | 0.037000 | 0% / 1× |
| B: replace Qwen with Gemini | 0.050509 | +1.018% / 1.010180× | 0.037509 | +1.376% / 1.013757× |
| C: one added Gemini recovery | 0.050950 | +1.900% / 1.019000× | 0.037950 | +2.568% / 1.025676× |
| D: conservative Gemini recovery | 0.050950 | +1.900% / 1.019000× | 0.037950 | +2.568% / 1.025676× |
| E: average, 20% of jobs escalate | 0.049749 | −0.502% / 0.994980× | 0.036749 | −0.678% / 0.993216× |
| F: one extra Qwen replay | 0.050441 | +0.882% / 1.008820× | 0.037441 | +1.192% / 1.011919× |

C/D add no extra model call on healthy jobs. F's warning/manual path adds no inference. If a failed primary was unbilled, do not double count it: reconcile against actual usage instead of blindly adding the conservative recovery figures. When a common extra cost is added, Luna's dollar advantage remains $0.013 but its percentage saving becomes smaller than 26% (for example, C/D recovery totals imply about 25.515%).

## Framework to use for future BEAR changes

This is a proposed repository decision framework to discuss and adopt, rather than a change to private agent memory or a selected runtime policy. It applies to Default, Luna/Beta, Experimental, future configurations, Chat, Decisions, eBay, deterministic processing and export.

1. **State the problem and evidence.** Record a reproducible input, observed output, failure class and verified cause. Separate output quality from provider availability and listing identity. Distinguish measured evidence, inference, assumptions and unknowns.
2. **Write the stage contract.** List fields the stage can produce, validation rules, criticality and copy-through fields it must preserve. Cosmetic names can be marked degraded; photo-number uncertainty and failed listing verification must never become guessed successful results.
3. **Classify failures before recovery.** Transient 429/5xx/network problems may permit bounded recovery. Invalid schema/semantic results need validation and selective repair. Authentication/configuration errors, insufficient credits and BEAR's spend-cap stop are terminal policy failures, not reasons to spend through another model. Treat permanent errors according to their actual endpoint semantics.
4. **Define each option in at least six information-bearing lines.** Mechanism, affected setups/stages, pros, cons, latency/quality evidence, cost for both baselines, uncertainty and a measurable verification plan. Present alternatives without a preferred badge or preselected choice. Compatible options may be combined, with a fresh combined cost.
5. **Separate stage policy from model selection.** Primary/backups, eligible errors, output adapters, total deadline, per-attempt timeout, max attempts, concurrency, Retry-After handling and local degradation belong to a stage policy. Chat, Decisions and eBay APIs need different adapters. Capability validation must happen before failover.
6. **Budget the entire run.** Show normal/recovery/worst bounded-policy scenarios with rates, token assumptions, call counts, frequency, absolute USD, percentage and multiplier for each setup. For a hard budget, reserve a conservative per-attempt cost bound from bounded input/output volumes and allowed rates before every attempt; reconcile concurrent reservations and possibly billed timeouts. Label an expected-cost estimate as a soft budget if those bounds cannot be enforced. A token-rate filter is not a job cap. Never multiply the whole photo run by a name-cleaner rate ratio.
7. **Carry provenance to the operator.** Save actual model/provider, attempt count, fallback reason, usage, affected IDs and review status. Make meaningful warnings visible in results and the web page without exposing credentials. Record unknown charges separately from confirmed zero-cost failures.
8. **Resume the smallest failed stage.** Retain source listing facts and successful paid results. Use deduplication and atomic output replacement. Keep the existing four-field downstream row contract unless a reviewed schema change is deliberately chosen; attach diagnostics via compatible metadata/status surfaces.
9. **Verify normal and degraded behavior.** Force outages, malformed/partial/non-string model results, cap stops and unknown vehicle words; test component-word preservation and filename-location rules. Check exact equality of part numbers, prices, URLs and images after name repair. Validate all completed artifacts before presenting success.
10. **Consult, record the owner's choice, and implement through a PR.** Record the selected option/combination, quality tolerance, review behavior, latency budget and recovery budget. Start implementation only after that consultation. The owner merges; agents never change `main` directly or merge PRs.

## Steps forward

1. Completed: the owner chose visual style A (Swiss Grid), and Sonnet produced the 22-slide HTML consultation deck using `frontend-slides`. This visual choice does not select solution A; all six solutions remain open for consultation. The original public skill at https://github.com/zarazhangrui/frontend-slides was read for this session without installing a persistent plugin.
2. Review the completed slides and this six-option brief, then identify any combination to develop; none is selected in this draft.
3. Agree whether uncertain names can ship with a warning or must wait for review, and set a recovery deadline and extra-cost limit for each setup.
4. After the owner's decision, implement stage contracts, selected recovery behavior, diagnostics and meaningful forced-failure checks on a fresh branch as appropriate.
5. Re-run the saved Shogun job's names stage and a multi-make evaluation set; measure tokens, total costs, latency and degraded-row counts for both setups. Investigate the separate starter-match concern independently.
6. Open the implementation PR into `main`, link issue 19, and give the owner the PR for review and merge. This analysis PR does not resolve or close issue 19.

Roles used for this analysis: GPT-6.1 Sol/high lead; GPT-6 Luna/medium read-only scout; GPT-6 Astra/medium advisor/reviewer; Claude Sonnet 5.5/high slide design. No paid BEAR inference calls were made for this consultation.
