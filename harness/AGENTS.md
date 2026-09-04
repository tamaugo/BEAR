# eBay Car Part Pipeline — Test Harness

Isolated test environment for the 3-agent car part identification & pricing pipeline. Project-local `pi-agent-harness` install (see `.pi/settings.json`) — deliberately separate from any other Pi project on this machine, so config here never mixes with unrelated work.

This is a **test rig**, not the production pipeline docs. The source of truth for the pipeline's design, tuning history, and business rules is the main project folder: `/Users/tamaugo/Desktop/` (see `pipeline overview.md` and `car_part_pipeline_spec v1.md` there).

## What's here
- `.pi/agents/agent1-part-reader.md` — Agent 1, locked and validated (Phase 1 complete).
- `.pi/agents/agent2-ebay-lookup.md` — Agent 2, rebuilt for the confirmed pipeline contract, **not yet tested live** — blocked on a real eBay API tool (see the note at the top of that file). Model as of 2026-09-03: **Meta Muse Spark 1.3, standard tier** with pi's `:minimal` thinking suffix (switched from Claude Haiku 4.5 for capability; the cheaper Contributor tier was tried and rejected because it requires enabling paid-model training account-wide). Swap the single `model:` line in that file to A/B against another slug.
- `.pi/prompts/run-pipeline.md` — `/run-pipeline`, the orchestration command that chains Agent 1 → Agent 2 (Agent 3 doesn't exist yet, so the chain stops there for now).
- `photos/` — drop test images here.
- `output/` — where `agent1_results.md` / `agent2_results.md` land after a run.

## Coordinator (root session) model
Not set via agent frontmatter — set the main session's model with `/model` inside `pi`. Candidate: `meta/muse-spark-1.2-contributor` (cheap, strong tool-use-relevant benchmarks per our research) — but its ~23s time-to-first-token may be annoying for a coordinator making many quick dispatch decisions per job. Swap via `/model` if so; no config file change needed.

## Before this actually works end to end
1. Confirm the global `~/.pi/agent/auth.json` OpenRouter key is set (it already exists on this machine — just confirm it covers OpenRouter, not only another provider). Never paste the key itself into a chat with Claude to check this.
2. Build the real eBay API tool for Agent 2 (`ebay_search`, `getRateLimits`) — OAuth2 client-credentials against eBay's Browse API (production access already available), Marketplace Insights for sold data if/when that access is approved. Nothing calls real eBay yet.
3. Run `pi doctor` (or whatever this harness's equivalent health check is) once the above is in place, and fix whatever it flags before a real job.

## Launching pi in this project (2026-09-04)

Just `pi`. No flags. Do **not** use `-ne` — it would strip the `subagent` tool the pipeline needs.

`.pi/settings.json` force-unloads the global `pi-interactive-subagents` extension for this project
only, resolving a `subagent` tool-name collision with the project-local agent harness. Without that
entry, pi will not start here and every spawned subagent dies with `(no output)`. Do not remove it,
and do not "fix" the collision by uninstalling the global package — it belongs to the user's
separate Obs-Learning project.
