# BEAR today (2026-11-13)

What BEAR does now, in one page. Rules for working on it are in [`AGENTS.md`](../AGENTS.md); setting up
and running the server is in [`discordbot/SETUP.md`](../discordbot/SETUP.md); how every Discord post
looks is in [`discordbot/FRONTEND.md`](../discordbot/FRONTEND.md). Older plans and research are in
[`history/`](history/): they explain why things are as they are, but may be out of date.

## What it does

BEAR runs as a Discord bot on a Debian VM. Each car has its own channel, with the car (make first)
in the channel topic.

1. `/newfolder name:Q184` starts a folder. People upload the part-number photos below it; each photo is one part.
2. `/run` waits until uploads stop, downloads the photos and runs BEAR on them (up to 2 folders at once, the rest queue).
3. **Read:** Gemini 3.1 Flash Lite reads every possible part number on each photo, re-reading rotated if it finds none.
   A photo already read (byte-identical, same model, prompt and car) reuses its saved read if it found a number.
4. **Check on eBay:** every reading is searched on eBay UK; a number nobody lists is not used. Hard reads get
   look-alike-letter rescues, and weak ones must pass a photo check (Gemini 3.5 Flash) before they count.
5. **Choose and price:** Jev (OpenRouter's Decisions API) picks the number and vetoes wrong listings; the price is
   the market consensus rounded up to x.99, never below 19.99.
6. **Name:** Qwen 3.8 Flash turns the listing title into a short part name (25 parts per call). If it fails, the
   bot retries only the names twice before reporting.
7. The card in the channel ends green with the spreadsheet, or red with what to do.

Unpriced photos get up to 3 eBay search-by-image suggestions, shaded, to check by eye.
`#part-id` is separate: a photo posted there gets Jev's top 3 part numbers to pick from (`partid/`). A part
with no number is marked 🚫 and looked up on eBay by its photo; `/sheet` lists the look-alikes under it.

**Cost:** about 0.12p a part (Nov 2026). Each folder has its own cap, `BEAR_RUN_CAP_USD`. The spend
ledger (`spend.jsonl` in each run folder) records cost and token counts per call.

## When something goes wrong

eBay and Jev busy spells are retried; if a service stays down, BEAR fails fast and says which one in
the FAILED row (eBay Lookup / Jev / Model / Photo Read Unavailable). One bad photo is its own FAILED row.
Error codes go to the error channel with the fix:

| Code | Meaning |
|---|---|
| D01–D07 | Discord side: no car in the topic, no folder, no photos, a photo type BEAR can't read, a download failed, renaming failed |
| N01–N03 | The name model was busy, not answering, or gave unusable names (after two names-only retries) |
| K01 / K02 | Out of OpenRouter credit / the folder hit BEAR's spend cap |
| E01 | Most parts failed because eBay, Jev or a model was down (spreadsheet still posted) |
| V01 | The final check flagged rows in a posted spreadsheet: check them before listing |
| T01 | The run took over 2 hours |
| R01 | Anything else (log attached) |

A restart in the middle of a run marks its card "stopped by a restart": `/run` it again.

## Where things are

| Where | What |
|---|---|
| `bear2/` | The `/run` pipeline (`run.py` and its stages, `assemble.py` for names and the spreadsheet) |
| `discordbot/` | The bot (`bot.py`), its wording (`look.py`), rules and error codes (`folders.py`), deploy files |
| `partid/`, `discordbot/partid_*.py` | #part-id |
| `tools/` | The final check (`agent3_validator.py`) and the Jev client |
| `tests/` | Six offline tests, run by GitHub on every pull request and by `setup.sh` on every update |
| `docs/history/` | Earlier plans, research, validation and the old front end ↔ back end contract |

Settings live in `/opt/bear/.env` on the server; the full list is at the top of `discordbot/bot.py`.
The owner updates the server with `bash /opt/bear/discordbot/deploy/setup.sh`.
