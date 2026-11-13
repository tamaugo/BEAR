# Rules for anyone (human or AI) working on this repo

BEAR reads part numbers off photos of used car parts, prices them against live eBay UK listings
and posts a spreadsheet. It runs as a Discord bot on a Debian VM. The owner is not a programmer:
explain things in plain English, and keep pull request descriptions plain.

## Branches and pull requests

- **`discord-bear` is the live product** and the branch all work goes into. `main` is old and
  unsupported: don't branch from it or open pull requests into it.
- Start from an up-to-date `discord-bear`: `git fetch && git checkout -b <new-branch> origin/discord-bear`.
- **Never push to `discord-bear` and never merge a pull request** (no `gh pr merge`). The owner
  reviews and merges everything.
- First run `gh pr list --state open` and tell the owner what is still open. Don't quietly build
  on top of an unmerged branch.
- One pull request per piece of work, opened with `gh pr create --base discord-bear`, with a plain
  title and description. Give the owner the link. Merged branches are deleted: don't reuse them.

## How to work

- **Accuracy comes first.** The owner will pay more per part for better accuracy, up to about
  30p a part (today about 0.12p). Never make BEAR less accurate to make it cheaper.
- **Diagnose and propose before fixing** anything the owner didn't ask for: explain the cause,
  give options with a recommendation, and wait for the owner to choose.
- **No version bumps.** Don't change `VERSION` or `CHANGELOG.md`; the owner does that once a
  release is complete.
- **Keys never appear in chat, logs or code.** Never read or print `.env`.
- Say **"folder"**, never "box".
- **#part-id stays separate from the `/run` pipeline.** Its code is in `partid/`,
  `discordbot/partid_bot.py` and `discordbot/partid_sheet.py`. `partid/` deliberately has its own
  copy of the reader prompt. Never change `bear2/` for #part-id.
- Every change keeps the offline tests passing and adds a test for what it changes.

## Map

| Where | What it is | State |
|---|---|---|
| `bear2/` | The `/run` pipeline: `run.py` (stages 1-3), `stage1_read.py` (photo read), `stage2_numbers.py` + `stage2b_rescue.py` (eBay checks), `stage3_listing.py` (pick listing, price), `assemble.py` (part names, spreadsheet), `common.py` (eBay, OpenRouter, spend ledger) | Live |
| `bear2/simulate.py` | Fake run for dev mode (`BEAR_SIM`), no credits | Live (tests) |
| `bear2/score.py`, `cmp_s1.py` | Old scoring helpers | History |
| `discordbot/` | The bot: `bot.py` (commands, runs), `look.py` (every post's wording), `folders.py` (folders, error codes), `heartbeat.py`, `renames.py` | Live |
| `discordbot/partid_bot.py`, `partid_sheet.py`, `partid/` | #part-id channel | Live, separate |
| `discordbot/shadow.py`, `shadow_report.py` | Location shadow test | Dormant (off) |
| `discordbot/deploy/` | Server install and update (`setup.sh`, systemd service) | Live |
| `discordbot/*.md`, `docs/` | Plans, research, setup guide (`SETUP.md` is current) | Mostly history |
| `tools/` | `agent3_validator.py` (checks the finished lines), `jev_client.py` (Jev / Decisions API) | Live |
| `harness/make_xlsx.py` | Writes `results.xlsx` | Live |
| `legacy/` | Old code nothing imports | History |
| `tests/` | Offline tests | Live |

**Tests** (free, no network, need `discord.py` and Pillow): run each of
`tests/test_names_offline.py`, `test_discord_offline.py`, `test_discord_look_offline.py`,
`test_discord_flow_offline.py`, `test_partid_offline.py`, `test_agent3_validator.py` with
`python3`. All must end with "passed".

**Server updates:** the owner runs `bash /opt/bear/discordbot/deploy/setup.sh` on the VM. It pulls
`discord-bear`, runs the offline tests and restarts the bot. Assistants don't deploy; server access
is read-only and only when a task needs evidence.
