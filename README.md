## BEAR — Discord server edition

This branch runs BEAR on a Debian 13 VM, fully managed through a Discord bot. Each car gets its own channel: create its photo folder with `/newfolder`, flag the part-number photo with 💸, then start the run with `/run`. The bot posts the finished spreadsheet back to the channel. Up to 2 folders can run at the same time. The Mac `bear` command and the `bear ui` web page are not on this branch; they live on `main`.

**Cost:** about 0.2p per part (measured). Each folder has its own spend cap, `BEAR_RUN_CAP_USD` in `.env` on the server ($3 in the template).

- Setup guide: [discordbot/SETUP.md](discordbot/SETUP.md)
- Design: [discordbot/PLAN.md](discordbot/PLAN.md)
- Research: [discordbot/RESEARCH.md](discordbot/RESEARCH.md)
- Changes: [CHANGELOG.md](CHANGELOG.md)

Offline tests (free, no network):

```
python3 tests/test_names_offline.py      # part names and the finished line layout
python3 tests/test_discord_offline.py    # the Discord bot's folder rules and error codes
.venv/bin/python tests/test_discord_flow_offline.py   # the whole bot flow in dev mode (needs discord.py)
```

### How 0.4 works

1. **Read** — a vision model reads every candidate part number (plus alternates), describes the part and counts items; if no number is found it re-reads the photo rotated 90/180/270.
2. **Numbers** — each reading is searched on eBay UK (exact match, several normalised forms). No UK listing means it is not a sellable number.
3. **Listing** — Jev picks the number when more than one survives, vetoes listings for pairs/sets/other assemblies, prefers used items, takes the consensus price, and sets the sell price to the smallest x.99 at or above it (floor 19.99).
4. **Assemble** — deterministic code builds the final rows (vehicle, location from filename, part number, price, URL, image, sort, FAILED/NULL rows); one cheap model call only tidies titles into names.
5. **Names** — Discord runs have no first-line check. If the name model fails, the run stops with an error code (`BEAR-N01`–`N03`) instead of writing messy names; swap the model with `BEAR_NAME_MODEL` in the server's `.env` (Qwen by default, or Gemini / Claude Haiku 5.5).

---


### Image matching (since 0.3)
- **Unpriced photos** (FAILED / NO PART NUMBER) get up to 3 eBay search-by-image suggestions as shaded rows directly under their row in `results.xlsx` (scanned order kept; ranked toward the job's car). Shown as \"listed £x\", never a BEAR price. Check by eye.
- **Weak or failed reads**: if a visually similar listing carries a part number within 1-2 characters of what was read off the part, that number is tried and must still pass the photo-vs-listings check. Example: cast bracket read `3M51-6030-BA` (no listings) -> image search found `6M51-6030-BA`.
- Free (eBay API only). Measured: right part in the image-search top 50 for 5/9 known photos, so it is a hint, not a verdict.

The legacy BEAR 0.1 pi pipeline and the Mac edition live on the `main` branch, not this one.

The server state from before the October 2026 cleanup is preserved as the git tag `server-pre-cleanup`.
