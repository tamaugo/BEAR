# Plan: tidy up the BEAR repo

Status: **proposal only.** No files have moved yet. Each phase below becomes its own
pull request (phase 0 is a tag, not a PR), and each one is checked against the "must
not break" list before it is opened. Delete this file when the last phase merges.

## The short version

The repo holds **two products**, and only one of them is still in use:

| | BEAR 0.2 (current) | BEAR 0.1 (retired) |
|---|---|---|
| Launched by | `bear` → `bin/bear` → `bear2/run.py` | `BEAR` zsh function in `tools/bear.zsh` → `pi` in `harness/` |
| Code | `bear2/` (11 small Python files) | `harness/.pi/`, `agents/`, prompt-driven agents |
| Status on this Mac | In use | Retired. `pi` is still installed, but the `BEAR` launcher is broken: `~/.zshrc` sources `tools/bear.zsh` from `~/Desktop/BEAR WITH JEV/`, which no longer exists, so typing `BEAR` falls through to the 0.2 `bear` command (macOS file names ignore case) |

Most of the mess comes from 0.1 files still sitting next to 0.2 files, with 0.2
borrowing three scripts out of 0.1's folders. The plan is to:

1. Tag today's `main` so 0.1 can be restored exactly, working, whenever needed.
2. Pull the three borrowed scripts into the 0.2 folder so 0.2 stands on its own.
3. Remove 0.1 from `main`.
4. Write one README that describes the product as it is today.

## Why it feels bloated: what's actually wrong

1. **0.2 depends on 0.1's folders.** The live pipeline reaches into the old ones:
   - `bear2/common.py:11` adds `tools/` to the import path to load `jev_client.py`.
     `bear2/stage2b_rescue.py:16` and `bear2/stage3_listing.py:15` also
     `import jev_client`, and only work because `common.py` is imported first.
   - `bear2/assemble.py:113,115` and `bear2/image_hints.py:108` run
     `tools/agent3_validator.py` and `harness/make_xlsx.py` by path.

   As a result, `harness/` and `tools/` look like legacy folders, but removing either
   one breaks `bear`. That's why nothing ever got cleaned up.

2. **23 retired prompt files.** `agents/` holds 9 "current" versions plus 11
   archived ones, and `harness/.pi/agents/` holds 3 more working copies. Only 0.1
   reads them. Git history already keeps every version, so the copies add nothing.

3. **Three launchers, and two of them are dead.**
   - `bin/bear` is the real one.
   - `tools/bear.zsh` is the 0.1 launcher. Its fallback path is
     `~/Desktop/ebay-pipeline`, which doesn't exist.
   - `tools/bear-dev.zsh` hard-codes `~/Desktop/independent-BEAR`, which also doesn't
     exist.

4. **The README describes both products at once.**
   - It opens with an accurate 0.2 quick start (`~/Desktop/bear`, `./install.sh`,
     `bear`).
   - It then switches to a long "Legacy pi pipeline (BEAR 0.1)" section with
     different commands (`BEAR`, `/run-pipeline`, tmux) and a different install
     path (`~/Desktop/ebay-pipeline`).
   - `harness/AGENTS.md` points to design docs in `/Users/tamaugo/Desktop/` that
     aren't in the repo.

5. **`.gitignore` contradicts itself.**
   - It says `docs/` is "deliberately excluded", but `docs/` is tracked. Any *new*
     doc you add there gets silently ignored. (That's also why this plan sits at the
     repo root.)
   - It lists many individual 0.1 harness paths (`harness/photos/`,
     `harness/agents/`, `harness/test_*.sh`, ...).

6. **Development scripts are mixed in with the product.**
   - `bear2/score.py`, `bear2/cmp_s1.py` and `bear2/finish.py` are evaluation tools
     that `bear` never runs. `finish.py` even loads the 0.1 Agent 3 prompt.
   - `tools/image_search_test.py` (Google Vision experiment) is referenced nowhere.
   - `tools/cost_model*.py` model the cost of 0.1.

7. **Tests are split by era but not labelled.** `tests/` mixes 0.2's ground truth
   with 0.1 fixtures, 0.1 results write-ups and 0.1 tests
   (`test_agent3_model_fixture.py`, `test_jev_questions_agent2.py`, and
   `test_jev_decisions.mjs`, which tests a pi extension).
   `tools/test_agent3_validator.py` lives outside `tests/`.

8. **Some clones can't update.** The remote `bear2` branch has been deleted (only
   `main` and feature branches exist). A clone that followed the old README is still
   on `bear2`, so `bear update` (`git pull --ff-only`) already fails there today.

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
- `bear update` (a `git pull`) keeps working on any clone that tracks `main`. Since
  `bin/bear` never moves, pulling a reorganised `main` is enough. Clones still on the
  deleted `bear2` branch need a one-time switch first (phase 0).
- Nothing that is ignored today becomes committable: real job photos and secrets
  stay covered by `.gitignore` (phase 4).

**Deliberately not done:** renaming `bear2/`. The folder name is wired into
`bin/bear`, the cache and ledger paths, and every command in the docs. Renaming it
gains almost nothing and is the single change most likely to break a running setup.
It can be its own PR later if you want it.

## Target layout

```
bin/bear                  launcher (unchanged)
install.sh                installer (unchanged)
VERSION  requirements.txt  .env.example  .gitignore  README.md  AGENTS.md  CLAUDE.md
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

The repo goes from 85 tracked files today (84 plus this plan) to 28, and every
file left is either used by `bear` or documents it.

## Phases (in this order)

### Phase 0: tag 0.1 and fix stranded clones (no code changes)

- Tag **today's** `main`, before anything moves, as `bear-0.1-final`. This is the
  last commit where 0.1 works as-is: its `harness/.pi/prompts/run-pipeline.md:190,205`
  runs `../tools/agent3_validator.py` and `make_xlsx.py` from `harness/`, and
  phase 1 moves those files. Tagging any later commit would capture a broken 0.1.
- Push it with `git push origin bear-0.1-final`. A local tag only exists on one Mac.
  **I'll ask you before pushing**, because the tag is public on GitHub.
- On any clone still on the deleted `bear2` branch, switch it to `main` once:
  `git checkout main && git branch -u origin/main`. After that, `bear update` works
  again. Phase 3 adds this line to the README.

**Why first:** the tag has to point at a commit where 0.1 still runs, and stranded
clones need to be on `main` before they can pull any of the later phases.

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
- Check, but don't expect to change, two more files that `import jev_client`:
  `stage2b_rescue.py` and `stage3_listing.py`. They currently rely on `common.py`'s
  path tweak. After the move they find `jev_client` because it sits next to them
  (each one adds `bear2/` to the path itself).
- `jev_client.py` finds `.env` via `parent.parent`. That still resolves to the repo
  root from `bear2/`, so no change is needed. I'll confirm it anyway.
- Move `tools/test_agent3_validator.py` → `tests/` and point its import at `bear2/`.
- `run.py:3`'s docstring mentions `make_xlsx.py`. That's harmless; it gets updated
  only if the wording becomes wrong.

**Why first (after the tag):** until this is done, nothing else can be removed
safely. It's also the riskiest phase, so it goes in on its own and is easy to review.

**Verification:** a full live run can't prove "same output". The eBay disk cache
expires after 24 hours (`max_age_h=24` in `common.py`), image-search results are
cached in memory only, and the vision and Jev calls aren't cached at all (stage 1
retries at temperature 0.3). Differences could come from the models rather than
the move, and the run costs real money. So the check is split in two:

- **Deterministic check (the real proof):** take an existing run folder's
  `agent3_results.txt` and `agent2_results.md`. Run the validator and `make_xlsx`
  on copies of them from the old tree (`main`) and from the phase 1 branch. The
  repaired `agent3_results.txt` must be byte-identical, and the `results.xlsx`
  cells must match (compared by cell value, since the zip file's timestamps
  differ).
- **Live smoke test:** one `bear2/run.py` run on the Hyundai i40 test photos with
  `--s1 <saved stage1.json>`, so stage 1 is pinned and no vision calls happen. It
  passes if it finishes, writes all the expected files and `results.xlsx` opens.
  Small price differences from live eBay data are expected and not a failure.
- Also: `bear check`, `python3 tests/test_agent3_validator.py`, a smoke import of
  every `bear2/` module, and a `grep` confirming no remaining `tools/` or `harness/`
  paths in `bear2/`.

### Phase 2: remove BEAR 0.1 from `main`

- Remove `harness/`, `agents/`, `tools/` (whatever's left after phase 1), the 0.1
  tests, fixtures and results, and `bear2/finish.py`.
- Move `bear2/score.py` and `bear2/cmp_s1.py` → `bear2/dev/` and fix their paths.

**Why:** 0.1 is retired. 0.2 replaced it, and its launcher no longer works on this
Mac (although `pi` itself is still installed). Keeping it in the tree is what makes
the repo confusing for people and for AI agents (they keep reading 0.1 prompts as if
they were live). The phase 0 tag means nothing is lost.

**Note:** `git rm harness/` only removes tracked files. Ignored local files under
`harness/` (`.env`, `photos/`, `photos-base/`, `node_modules`) stay on disk, which is
why phase 4 keeps them ignored.

**Verification:** the phase 1 checks again. A whole-repo `grep` for `harness/`,
`tools/` and `agents/` should match only `docs/` and `.gitignore` (the ignore rules
are deliberately kept; see phase 4).

### Phase 3: one honest README, and the docs

- README covers the 0.2 product only:
  - install, run, check, update
  - where results go, and cost
  - how it works (short)
  - credentials
  - where real job data lives
  - the one-line fix for clones stuck on the old `bear2` branch (phase 0)
- Drop the "Legacy pi pipeline (BEAR 0.1)" section. Leave a one-line pointer to the
  `bear-0.1-final` tag.
- Move `bear2/README.md` → `docs/how-it-works.md` and fold in the useful Jev and
  validator notes from `tools/README.md`.
- Move the dated handoff, debrief and spec notes into `docs/history/`. Add a short
  note at the top of each saying that the `tools/` and `harness/` paths they mention
  refer to the `bear-0.1-final` layout. The notes themselves stay as written.

**Why:** the README is the first thing anyone (or any agent) reads. Right now half
of it describes a product that no longer runs.

### Phase 4: housekeeping

- `.gitignore`:
  - remove the stale `docs/` exclusion
  - replace the many per-file `harness/...` rules with a single `harness/` line.
    The old rules are **not** just deleted: any machine that still has
    `harness/photos/` or `harness/photos-base/` (real job photos) would otherwise
    commit them on the next `git add -A`. One `harness/` line keeps all of it
    ignored.
  - keep every secret and job-data safety net (`.env*`, `*.env`, `jobs/`, `*_job/`,
    `bear2/cache/`, `bear2/spend.jsonl`, `bear2/runs/`)
- Delete this plan file.
- **Outside the repo** (your call, I won't touch it without asking): the
  `source ".../BEAR WITH JEV/tools/bear.zsh"` line in `~/.zshrc` points at a folder
  that's gone and can be removed.

**Why:** this stops new docs from being silently ignored, and shrinks the 0.1 rules
to one line without ever letting customer photos or secrets become committable.

## Risks and how they're handled

| Risk | Mitigation |
|---|---|
| A moved script breaks `bear` mid-job | Phase 1 is isolated, checked deterministically (validator and `make_xlsx` output identical before and after) plus a pinned-stage-1 smoke run, and contains nothing else |
| Someone needs the 0.1 pi pipeline again | `git checkout bear-0.1-final` restores it exactly, because the tag is made before phase 1 moves anything and is pushed to GitHub |
| Customer photos or secrets left in `harness/` get committed later | Phase 4 keeps a single `harness/` ignore rule instead of deleting the old rules |
| A clone is still on the deleted `bear2` branch | Phase 0 switches it to `main` once; the README documents the fix |
| Another machine has an old clone on `main` | `bin/bear` never moves, so `bear update` (git pull) keeps working; untracked cache and ledger stay in `bear2/` |
| Losing local cache or spend history | `bear2/` isn't renamed, so `bear2/cache/` and `bear2/spend.jsonl` stay put |
