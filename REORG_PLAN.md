# Plan: tidy up the BEAR repo

Status: **proposal only.** No files have moved yet. Each phase below becomes its own
pull request, and each one is checked against the "must not break" list before it is
opened. Delete this file when the last phase merges.

## The short version

The repo holds **two products**, and only one of them is still in use:

| | BEAR 0.2 (current) | BEAR 0.1 (retired) |
|---|---|---|
| Launched by | `bear` → `bin/bear` → `bear2/run.py` | `BEAR` zsh function in `tools/bear.zsh` → `pi` in `harness/` |
| Code | `bear2/` (11 small Python files) | `harness/.pi/`, `agents/`, prompt-driven agents |
| Still works on this Mac? | Yes | No. `~/.zshrc` sources `tools/bear.zsh` from `~/Desktop/BEAR WITH JEV/`, which no longer exists, so typing `BEAR` falls through to the 0.2 `bear` command (macOS file names ignore case) |

Most of the mess comes from 0.1 files still sitting next to 0.2 files, with 0.2
borrowing three scripts out of 0.1's folders. The plan is to:

1. Pull the three borrowed scripts into the 0.2 folder so 0.2 stands on its own.
2. Archive 0.1 behind a git tag, then remove it from `main`.
3. Write one README that describes the product as it is today.

## Why it feels bloated: what's actually wrong

1. **0.2 depends on 0.1's folders.** The live pipeline reaches into the old ones:
   - `bear2/common.py` adds `tools/` to the import path to load `jev_client.py`.
   - `bear2/assemble.py` and `bear2/image_hints.py` run `harness/make_xlsx.py` and
     `tools/agent3_validator.py` by path.

   As a result, `harness/` and `tools/` look like legacy folders, but removing either
   one breaks `bear`. That's why nothing ever got cleaned up.

2. **23 retired prompt files.** `agents/` holds 9 "current" versions plus 11
   archived ones, and `harness/.pi/agents/` holds 3 more working copies. Only 0.1 reads them. 0.2 doesn't read any of them. Git
   history already keeps every version, so the copies add nothing.

3. **Three launchers, and two of them are dead.**
   - `bin/bear` is the real one.
   - `tools/bear.zsh` is the 0.1 launcher. Its fallback path is
     `~/Desktop/ebay-pipeline`, which doesn't exist.
   - `tools/bear-dev.zsh` hard-codes `~/Desktop/independent-BEAR`, which also doesn't
     exist.

4. **The README describes both products at once.**
   - It opens with "0.2 quick start", which still says `git checkout bear2` even
     though that branch was merged.
   - It then switches to a long "Legacy pi pipeline (BEAR 0.1)" section with
     different commands (`BEAR`, `/run-pipeline`, tmux) and a different install
     path (`~/Desktop/ebay-pipeline`).
   - `harness/AGENTS.md` points to design docs in `/Users/tamaugo/Desktop/` that
     aren't in the repo.

5. **`.gitignore` contradicts itself.**
   - It says `docs/` is "deliberately excluded", but `docs/` is tracked. Any *new*
     doc you add there gets silently ignored. (That's also why this plan sits at the
     repo root.)
   - It still lists 0.1-only paths like `harness/photos/`, `harness/agents/` and
     `harness/test_*.sh`.

6. **Development scripts are mixed in with the product.**
   - `bear2/score.py`, `bear2/cmp_s1.py` and `bear2/finish.py` are evaluation tools
     that `bear` never runs. `finish.py` even loads the 0.1 Agent 3 prompt.
   - `tools/image_search_test.py` (Google Vision experiment) is referenced nowhere.
   - `tools/cost_model*.py` model the cost of 0.1.

7. **Tests are split by era but not labelled.** `tests/` mixes 0.2's ground truth
   with 0.1 fixtures, 0.1 results write-ups and 0.1 tests (`test_jev_decisions.mjs`
   tests a pi extension). `tools/test_agent3_validator.py` lives outside `tests/`.

## Must not break (the contract every phase is checked against)

- `./install.sh` still links `~/.local/bin/bear` → `<repo>/bin/bear`.
- `bear`, `bear <folder> "<vehicle>"`, `bear check`, `bear update`, `bear version`
  and `bear help` behave exactly as today.
  - `bin/bear` doesn't move.
  - `VERSION`, `requirements.txt` and `.venv/` stay at the repo root.
- Credentials work as today: Keychain service names `openrouter-api-key`,
  `ebay-app-id` and `ebay-cert-id`, and `.env` at the repo root.
- Results still go to `<photo folder>/bear-results-YYYYmmdd-HHMMSS/` with the same
  files (`results.xlsx`, `agent2_results.md`, `agent3_results.txt`, `trace.json`).
- `BEAR_RUN_CAP_USD` still works. The spend ledger and eBay cache stay where they
  are (`bear2/spend.jsonl`, `bear2/cache/`), so no cache or spend history is lost.
- `bear update` (a `git pull`) on any other machine still works. Since `bin/bear`
  never moves, pulling a reorganised `main` is enough.

**Deliberately not done:** renaming `bear2/`. The folder name is wired into
`bin/bear`, the cache and ledger paths, and every command in the docs. Renaming it
gains almost nothing and is the single change most likely to break a running setup.
It can be its own PR later if you want it.

## Target layout

```
bin/bear                  launcher (unchanged)
install.sh                installer (unchanged)
VERSION  requirements.txt  .env.example  README.md  AGENTS.md  CLAUDE.md
bear2/                    the product: everything `bear` runs
  run.py  common.py  stage1_read.py  stage2_numbers.py  stage2b_rescue.py
  stage3_listing.py  assemble.py  image_hints.py
  jev_client.py           <- moved from tools/
  make_xlsx.py            <- moved from harness/
  agent3_validator.py     <- moved from tools/
  dev/                    evaluation scripts, never run by `bear`
    score.py  cmp_s1.py
tests/
  test_agent3_validator.py          <- moved from tools/
  fixtures/ground_truth_hyundai_i40_2026-09-30.json
docs/
  how-it-works.md         <- today's bear2/README.md, expanded
  history/                handoff, debrief, Jev spec (dated notes, kept for context)
```

Removed from `main` (still recoverable from the `bear-0.1-final` tag):
`harness/`, `agents/`, `tools/bear.zsh`, `tools/bear-dev.zsh`, `tools/cost_model*.py`,
`tools/jev_questions.py`, `tools/image_search_test.py`, `tools/README.md` (its Jev
notes move into `docs/how-it-works.md`), `bear2/finish.py`, the 0.1 tests, fixtures
and `tests/results/`, `tests/ground-truth.md` (0.1 format; the JSON ground truth
replaces it).

The repo goes from 84 tracked files to about 28, and every file left is
either used by `bear` or documents it.

## Phases (one PR each, in this order)

### Phase 1: make 0.2 self-contained (the only phase that touches running code)

- `git mv` these three files into `bear2/`:
  - `tools/jev_client.py`
  - `tools/agent3_validator.py`
  - `harness/make_xlsx.py`
- Update the paths that point at them:
  - `common.py`: drop `sys.path.insert(... "tools")`, since `jev_client` now sits
    next to it.
  - `assemble.py`: validator and `make_xlsx` paths.
  - `image_hints.py`: `make_xlsx` path.
- `jev_client.py` finds `.env` via `parent.parent`. That still resolves to the repo
  root from `bear2/`, so no change is needed. I'll confirm it anyway.
- Move `tools/test_agent3_validator.py` → `tests/` and fix its import path.

**Why first:** until this is done, nothing else can be removed safely. It's also the
riskiest phase, so it goes in on its own and is easy to review.

**Verification:**
- `bear check`
- `python3 tests/test_agent3_validator.py`
- `grep` confirms no remaining `tools/` or `harness/` paths in `bear2/`
- A full `bear` run on the Hyundai i40 test photos, compared against a run from
  `main` taken just before: same rows, same prices, same `results.xlsx` columns.
  eBay searches come from the disk cache, so the comparison costs almost nothing.

### Phase 2: retire BEAR 0.1

- Tag the current `main` as `bear-0.1-final` so the whole pi setup can always be
  restored with `git checkout bear-0.1-final`.
- Remove `harness/`, `agents/`, `tools/` (whatever's left after phase 1), the 0.1
  tests, fixtures and results, and `bear2/finish.py`.
- Move `bear2/score.py` and `bear2/cmp_s1.py` → `bear2/dev/` and fix their paths.

**Why:** 0.1 can't run on this machine as things stand, and 0.2 replaced it. Keeping
it in the tree is what makes the repo confusing for people and for AI agents (they
keep reading 0.1 prompts as if they were live). The tag means nothing is lost.

**Verification:** same as phase 1. A whole-repo `grep` for `harness/`, `tools/` and
`agents/` should match only docs/history.

### Phase 3: one honest README, and the docs

- README covers the 0.2 product only:
  - install, run, check, update
  - where results go, and cost
  - how it works (short)
  - credentials
  - where real job data lives
- Drop the stale `git checkout bear2` step and the 0.1 section. Leave a one-line
  pointer to the `bear-0.1-final` tag.
- Move `bear2/README.md` → `docs/how-it-works.md` and fold in the useful Jev and
  validator notes from `tools/README.md`.
- Move the dated handoff, debrief and spec notes into `docs/history/`.
- Coordinate with the open PR #4 (install location `~/Desktop/bear`) so the two
  README changes don't fight. Ideally #4 merges first and this phase builds on it.

**Why:** the README is the first thing anyone (or any agent) reads. Right now it
gives two contradictory sets of instructions.

### Phase 4: housekeeping

- `.gitignore`:
  - remove the stale `docs/` exclusion
  - remove the 0.1 harness patterns
  - keep every secret and job-data safety net (`.env*`, `jobs/`, `*_job/`,
    `bear2/cache/`, `bear2/spend.jsonl`, `bear2/runs/`)
- Delete this plan file.
- **Outside the repo** (your call, I won't touch it without asking): the
  `source ".../BEAR WITH JEV/tools/bear.zsh"` line in `~/.zshrc` points at a folder
  that's gone and can be removed.

**Why:** this stops new docs from being silently ignored, and removes rules for
folders that no longer exist.

## Risks and how they're handled

| Risk | Mitigation |
|---|---|
| A moved script breaks `bear` mid-job | Phase 1 is isolated, checked with a full before/after comparison run, and contains nothing else |
| Someone needs the 0.1 pi pipeline again | `git checkout bear-0.1-final` restores it exactly |
| Another machine has an old clone | `bin/bear` never moves, so `bear update` (git pull) keeps working; untracked cache and ledger stay in `bear2/` |
| Conflicts with open PRs #4 (README) and #5 (`bear2/run.py` progress) | Ideally both merge before phase 1 starts. Phase 1 doesn't edit `run.py`, and phase 3 waits for #4 |
| Losing local cache or spend history | `bear2/` isn't renamed, so `bear2/cache/` and `bear2/spend.jsonl` stay put |
