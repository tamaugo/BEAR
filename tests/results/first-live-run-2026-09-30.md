# First live production run — BEAR-Jev (2026-09-30)

Batch: 19 parts (real customer photos, user's Mac, `/run-pipeline`, branch `jev-integration`).

## Results (operator-reported, verbatim)

- 19 parts in
- 1 image never had a part number (NULL-type input)
- 3 Agent 1 fails (reported as FAILED lines)
- 1 part number was **upside down** in the photo — missed by the pipeline
- 1 part had a number **very visible** — the pipeline never saw it
- 1 listing was **wrong** (Agent 2/Jev resolve picked a mismatched listing)

Derived counts: 15 photos carried a real number; 13 read correctly (86.7% extraction recall);
2 extraction misses (13.3%). Of the 13 reads, 1 went to a wrong listing (Agent 2 stage).

## Operator's assessment (verbatim intent)

"Cheaper but not better — the introduction of Jev has seemed to worsen the results. This was never
intended. Double-check what Jev is doing, what is its role, and do the other models still have
their reasoning in their md file saying to think about what number they should pick?"

## Investigation findings (2026-09-30)

**Jev's role (what it actually is):** Jev never sees any photo. It is a text-in/typed-decision-out
model used at exactly two points: (1) Agent 1 — pick the genuine part number AMONG the candidate
strings the vision model extracted, plus a format check (it can only choose what extraction
found); (2) Agent 2 — pick which listing gets named/linked among the already-price-filtered
candidates. It cannot read images, generate text, or recover a number extraction missed.

**User's suspicion CONFIRMED — the models' own judgment was stripped from the MD files:**
- Agent 1 v8 (original): "Never guess: absolute confidence or fail… If unsure which is primary,
  fail… Any doubt at any step → output the fail string." Google grounding assisted VERIFICATION.
- Agent 1 v9-jev (mine): "you no longer judge confidence yourself… do not fail an image at this
  step — extraction is cheap and reliable… do not pre-filter beyond the cheap ignores," and
  grounding demoted to "Step 1 extraction only."
- Agent 2 v6 → v7: Step C's judgment ("clearest, most unambiguous part name") moved from the
  model's reasoning to Jev; the base model dropped to a non-reasoning mechanic (intended).

**Root cause of the live regression:** v9 was built on an UNTESTED assumption — "extraction is
cheap and reliable." Real photos prove otherwise: 2 of the 3 Agent 1 failures are EXTRACTION
failures (one number upside down — orientation is unhandled in v8 AND v9; one number clearly
visible but never extracted). v8's scrutiny ("any doubt → fail", verification-grade reading)
made the vision model dig harder; v9's tone explicitly told it NOT to judge, and Jev cannot
recover what extraction never surfaced. Judgment moved to Jev, but extraction scrutiny was
demoted rather than strengthened — the wrong half of the pair to weaken.

**The wrong listing:** two candidate paths — (a) a plausible-but-wrong number passed Agent 1's
gate (Jev picks among extracted candidates and cannot see the photo, so "right format, wrong
part" is invisible to it), and eBay then listed the wrong part; (b) Jev picked a wrong title
among equal-price carriers. Needs output/agent1_results.md + agent2_results.md from the run to
attribute definitively.

**Honest caveat:** there is no v8 baseline on this same 19-part batch, so "worse" is not yet a
strict measurement — but the demotion mechanism is verifiable in the files and matches the
failure pattern exactly.

**Fix direction (proposed, awaiting go-ahead):** v9.1 restores v8's extraction scrutiny
(char-by-char reading discipline, orientation handling incl. upside-down/rotated text,
make-format sanity check back in the vision model's hands, grounding back to verification)
while KEEPING Jev as the calibrated gate — Jev judges among candidates, but extraction must be
ruthless again. Also enrich Agent 1's Jev state with per-candidate reading context.

