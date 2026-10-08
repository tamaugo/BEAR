# BEAR change consultation framework

Proposed for the owner's review. Use this framework when presenting future BEAR behavior changes, recovery policies or model choices. It applies to every setup and stage, including Default, Luna/Beta, Experimental, Chat, Decisions, eBay, deterministic processing and exports.

## Decision brief

For each proposed change, provide:

1. The observed problem, reproducible inputs, evidence and cause; distinguish confirmed facts from assumptions and unknowns.
2. The affected stage and output contract, including fields that must be preserved and whether degraded output can be delivered.
3. Neutral, materially different alternatives. Do not label a preferred option or preselect the owner's choice. Options can be combined if their contracts are compatible.
4. At least six information-bearing lines per option: mechanism/scope, pros, cons, quality/latency evidence, Default cost, Luna cost, uncertainties and verification requirements. Expand beyond six where needed.
5. Pricing for a stated workload, normally 20 photos: source date, model rates, token counts, call counts, cache/reasoning assumptions, normal and recovery scenarios, and any unknown human or infrastructure cost.
6. Absolute cost, percentage change and cost multiple for both setups, compared with the same workload's current reference. Show why stage-specific costs differ from the whole-run total.
7. Failure behavior and a measurable evaluation plan. Do not invent accuracy, provider-independence, availability or expected fallback frequency.
8. Steps forward and explicit questions requiring the owner's decision before implementation.

## Cost arithmetic

For a token-priced call: `call USD = (input tokens × input USD/M + billed output tokens × output USD/M) / 1,000,000`, plus any separate billed items. Include billed reasoning in output usage where applicable.

`cost multiple = new workload cost / reference workload cost`.

`percentage change = (cost multiple − 1) × 100`. For example, 4× the current cost means +300%, not +400%.

Use measured baselines where available. Label owner-supplied reference figures and synthetic token/frequency assumptions. Subtract a replaced stage's cost only when the baseline contains it, or state that this is an explicit modeling assumption. Account for possibly billed timeouts and paid invalid outputs. Single-call estimates are not retry-envelope spending ceilings.

For issue 19, the owner references are $0.05 per 20 photos Default and $0.037 Luna (26% cheaper). Future briefs must refresh their own baselines rather than assuming these remain current.

## Resilience contract

- Define primary/backups, API adapters, eligible failures, validation, max attempts, per-attempt timeout, total deadline and concurrency independently for each stage and setup.
- Distinguish transient provider/network errors from invalid outputs, authentication/configuration errors, insufficient credit and BEAR's budget stop. Terminal policy errors must not trigger spending through another model.
- Validate response schema, expected IDs, types and stage semantics before accepting results. Recover partial output selectively. Chat, Decisions and eBay are different interfaces; require compatible adapters before switching.
- Define safe degradation for every stage. Optional name text may be marked for review. Critical part-number or listing uncertainty must never turn into an invented successful result.
- For a hard budget, reserve a conservative per-attempt bound from bounded input/output volumes and allowed rates before every attempt, including concurrent requests; reconcile actual model/provider and usage. Label estimates as soft budgets when those bounds cannot be enforced. Provider token-rate limits do not impose a run-level spending cap.
- Retain provenance, affected-row warnings and review status in operator-visible surfaces while keeping credentials private. Preserve existing downstream row contracts unless an explicit schema change is reviewed.
- Resume only the failed stage; retain successful paid work. Use deduplication and atomic output replacement for repair actions.
- Test normal operation and forced 429/network/invalid/partial failures, unknown vehicle words and budget stops. Compare exact part numbers, prices, URLs and images before/after cosmetic repairs.

## Consultation and delivery

Present the complete brief and requested visuals before asking the owner to select an option or combination. Record the selected behavior, quality tolerance, degraded-output/review choice, recovery latency and extra-cost budget. Implementation follows that decision and the repository's pull-request workflow. The owner merges; agents do not change `main` directly or merge PRs.

The worked example is [issue 19's consultation](reviews/issue-19/decision-brief.md), with [machine-readable cost illustrations](reviews/issue-19/costs.json). No issue-19 solution has been selected by this framework.
