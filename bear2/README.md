# BEAR v2 (branch `bear2`)

photos -> `run.py` -> agent2_results.md (same 5-field contract) -> `assemble.py` -> agent3_results.txt (4-field contract) -> validator -> make_xlsx -> results.xlsx

1. `stage1_read.py`   gemini-3.1-flash-lite: every candidate reading + alt readings, part description, item count. No number found -> re-read rotated 90/180/270.
   Model setups are fixed in `configs.py` (default / beta / experimental) and picked as a whole, never per agent: the drop-down on the web page, or `BEAR_CONFIG=beta` for the `bear` command. Experimental = Claude Haiku 5.5 with `agents/agent1_instructions_v10_haiku.md` (results in that file); beta = Luna Decisions photo check.
2. `stage2_numbers.py` eBay UK exact-match search per reading (raw / normalised / 5-5 hyphenated / split-code joined). No UK listing = not a sellable number.
3. `stage3_listing.py` Jev: choose number when >1 reading survives (fail if conf<0.5 unless it is the sole vision "primary"); Jev noul per listing = VETO (<0.2) for pairs/sets/other assemblies; used-first; consensus price; sell price = smallest x.99 >= price-0.01, floor 19.99; Jev picks the best-named title among listings at that sell price. Price + URL always from the same listing.
4. `assemble.py` deterministic Agent 3: vehicle, location (filename), part number, price, URL, image, sort, FAILED/NULL rows are code. One qwen3.8-flash call per job only cleans titles into names (guard-railed, mechanical fallback).

Run:  `python3 bear2/run.py <photo_dir> "<VEHICLE>" <out_dir>`   Score: `python3 bear2/score.py <out_dir>/agent2_results.md`
Spend ledger: bear2/spend.jsonl (gitignored). Hard stop at $4.00 in common.py.
