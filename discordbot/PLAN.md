# Discord BEAR — build plan

Status: **the bot and VM setup are built** (see [SETUP.md](SETUP.md)). Photo-quality testing
(§8) is still to do. Everything here was agreed with the owner in October 2026. The research
behind it (Discord limits, blind spots, sources) is in [RESEARCH.md](RESEARCH.md).

The Discord bot is a new, separate way to start BEAR. The Mac `bear` command and `bear ui`
stay exactly as they are on `main`; this branch (`discord-bear`) is the server edition and drops them.

---

## 1. How it works for the person uploading

1. **One Discord channel per car.** The channel **topic** holds the exact vehicle text, e.g.
   `FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL`. It must start with the make (BEAR uses the
   first word as the make for eBay matching).
2. **`/newfolder name: Q184`** starts a folder (a box of parts). The bot posts a marker
   message: **📁 Folder Q184**. Everything after it belongs to Q184.
3. **Upload the part-number photos** in any groups you like. Only part-number photos: **every
   photo is one part**. (Until 2026-10-27 people also posted other photos and flagged the
   part-number one with 💸; the owner dropped both, so no reaction is needed.)
4. **`/run`** ends the folder and runs every photo in it through BEAR.
5. The bot replies **"Running x parts"**. If you uploaded 20 parts and it says 4, photos are
   missing. It does not wait for a GO; it just runs.
6. The bot posts **one spreadsheet for the folder**, e.g. `Q184-ford-fiesta-mk7.xlsx`,
   with "BEAR found x listings".
7. Anything that goes wrong is posted in the **error channel**:
   "**Q184** encountered an issue — `BEAR-D05` — fix: …".

8. **Renaming (dormant since 2026-10-25).** `/run` no longer offers it; `BEAR_RENAME_OFFER=1` in
   `.env` brings the offer back. When on: next to the run card, `/run` posts **🏷️ Rename the photos?** with a
   **Rename photos** button. Tapping it opens a box to type a SKU, e.g. `MYSKU`. People have
   **1 minute** (`BEAR_RENAME_WAIT`); left blank, the photos aren't renamed and the card says so.
   With a SKU, **every photo** in the folder (from the 📁 marker to `/run`, in upload
   order) is named `MYSKU-1.jpg`, `MYSKU-2.jpg` ... and posted as `MYSKU-1.zip` (more zips,
   `MYSKU-2.zip` ..., if it doesn't fit Discord's 10 MB limit) **after the spreadsheet**, even if
   BEAR failed. **`/rename sku: MYSKU`** does only this, with no BEAR run.
9. **`/quit`** stops everything `/run` or `/rename` is doing in the channel: BEAR, the queue,
   the rename. Nothing more is posted for that folder.

Renaming is separate from BEAR: BEAR never sees the renamed files and the rename never reads 💸.
Renames have no limit on how many run at once; photos are downloaded 6 at a time across all of
them (`BEAR_RENAME_DOWNLOADS`) and zips are stored, not compressed, so CPU and memory stay low.

Rules:
- Text is never read. **Text-only messages are deleted** by the bot (a photo with a caption
  is kept). The bot never deletes its own messages.
- **Anyone** in the server can run the commands.
- `/run` waits until no new photo has arrived for **about 30 seconds** before it starts
  (the bot cannot see an upload that is still in progress).
- Running `/run` again in the same folder simply runs that folder again (it is usually done
  because something was wrong).

Mockup of the flow (owner's screenshots, 14 Oct 2026): `/newbox: Q184` → 5 general photos →
label photo on its own with 💸 → 6 general photos → `end` → `/run` → "Running x amount of
parts / Bear ran and found x amount of listings / Here is the xlsx file" + spreadsheet.
In the build, `/newbox` became `/newfolder` and `end` is part of `/run`.

---

## 2. Decisions

| Topic | Decision |
|---|---|
| Hosting | One always-on bot on a **Debian 13** VM (Proxmox): 2 cores, 4 GB RAM, 32 GB disk. Outbound connection to Discord; no port forwarding. See [SETUP.md](SETUP.md) §1. |
| Car name | From the **channel topic**. Empty topic = refuse to run. |
| Folders | `/newfolder name:<x>` starts one; `/run` ends and runs it. **One spreadsheet per folder.** |
| Part-number photo | Only part-number photos are uploaded; **every photo goes to BEAR as one part** (since 2026-10-27; before that, 💸 picked them out of all the photos). |
| Chat text | Never read; text-only messages deleted. |
| "Running x parts" | Information only, no GO button. |
| First-line name check | **Not used in Discord runs.** No automatic model fallback. If Qwen keeps failing, the owner swaps the name model by hand: set `BEAR_NAME_MODEL` in the server's `.env` (applies on the next `/run`, no restart). |
| Name model fails | Run stops, error goes to the error channel. Photo reads and eBay results are kept, so only the names need finishing later. |
| Errors | Separate error channel: folder name + error code + fix. Full error list to be refined later. |
| Who can run it | Anyone in the server. |
| Upload wait | ~30 s with no new photo before running. |
| webp | BEAR reads webp directly (no separate conversion step). HEIC = refuse with an error. |
| Spend cap | The OpenRouter key's own cap is the real limit. |
| Parallel runs | **One VM, one bot**, up to 2 BEAR runs at once (`BEAR_MAX_RUNS`, default 2). A 3rd `/run` waits in a queue and the bot says it is queued. Never the same car twice at once: one folder per car channel. |
| Status command | `/status` lists running and queued folders. |
| Same part number twice in a folder | No special handling for now. Add a "DUPLICATE? check" mark only if it becomes a problem. |
| Location (NSF/NSR/OSF/OSR) | **Being tested.** Staff write NF/OF/NR/OR in marker on the part, so it is in the part-number photo. The shadow test (below) logs what Decisions models read there; four custom emoji reactions on the photo stay the fallback. |
| Shadow test | After each `/run`, every photo goes to `openai/gpt-6-luna-decisions`, `typesafe/jev-1.13` and `cloudflare/clef` (which location?). Logged, never posted. Folders from before 2026-10-27 also logged whether Luna could find the 💸 photo; with no 💸 any more, new folders add location data only. A note in the error channel every 300 part photos (`BEAR_SHADOW_PING_PARTS`); then `shadow_report.py`. |
| Image column in the spreadsheet | Kept as it is for now. |
| Channel limit (500/server, 50/category) | Fine for now; archive or delete finished cars. |

---

## 3. How the bot uses BEAR (no changes to the Mac flow)

The bot runs BEAR the same way `bear ui` does: as a **separate program for each folder**.

```
python3 bear2/run.py <folder photos dir> "<channel topic>" <results dir>
```

What already works without changing BEAR:
- **No first-line check.** When `run.py` is started without a terminal and without the web
  page (`BEAR_WEB_ASK` unset), `assemble.asker()` returns no one to ask, so the check is
  skipped (`bear2/assemble.py:187`, `bear2/run.py:153`).
- **Name model failure stops cleanly.** With no one to ask, a failed name model raises
  `Stop` with "No names were written" and a hint to finish only the names later
  (`bear2/assemble.py:280`). The bot catches that and posts to the error channel.
  `python3 bear2/run.py <photos> "<vehicle>" <results> --names-only` finishes the names later.
- **Keys from `.env`.** `common._env()` and `jev_client.resolve_api_key()` read the shell
  environment, then `.env` at the repo root. No Keychain needed on Linux. Only the `bin/bear`
  launcher uses the macOS Keychain, and the bot does not use the launcher.
- **Spend cap per run.** Each run has its own spend ledger (`BEAR_SPEND_LEDGER`, set by the
  bot to the run folder), so parallel runs do not count each other's spending. The `$1` cap in
  `bear2/common.py:41` counts only that run. Set `BEAR_RUN_CAP_USD` higher in the bot's
  environment if a full folder can cost more.

How the bot names the photos it hands to BEAR (BEAR reads row order from the first number
in the filename, `bear2/assemble.py:image_no`):
- `001.jpg`, `002.jpg`, … in upload order. The order number must come first: BEAR sorts on
  the first number in the name.
- The bot names the photos itself (`001.jpg`…), so BEAR never reads the word `NULL` or the
  NSF/NSR/OSF/OSR location codes from a filename (those features were removed from the
  server code).
- Keep the original file extension (`.jpg`, `.png`, `.webp`).

---

## 4. What the bot does, step by step

**`/newfolder name:<x>`**
1. Check the channel has a topic. If not, error `BEAR-D01`.
2. Post the marker message **📁 Folder `<x>`** and reply to the command.

**`/run`**
1. Reply within 3 seconds ("Checking folder Q184 …"). Discord requires that.
2. Find the latest 📁 marker in the channel. None = error `BEAR-D02`.
3. If the newest photo is under ~30 s old, say "please wait, images are still uploading"
   and check again.
4. Read every message after the marker. Keep every photo, several to a message is fine; videos
   and other files are left out.
   - None = error `BEAR-D03`.
   - A photo BEAR can't read (HEIC etc.) = error `BEAR-D05`.
5. Post **"Running x parts"**.
6. Download every photo straight away (Discord links expire after 24 h), 6 at a time, into
   `<storage>/<channel>/<folder>-<time>/photos/` as `001.jpg`, `002.jpg`, … in upload order.
   A failed download = error `BEAR-D06`.
7. Run `bear2/run.py` as a separate process. It can take longer than Discord's 15-minute
   window for replying to a command, so the result is posted as a **normal bot message**,
   not as a reply to `/run`.
8. Post "BEAR found x listings" with the spreadsheet, renamed to
   `<folder>-<car>.xlsx`.
9. On any failure, post to the error channel and say in the car channel that the folder
   failed.

**Any other message**
- Text with no photo is deleted (needs the Manage Messages permission).

**Restarts**
- The bot keeps no important state in memory: on `/run` it re-reads the channel to find the
  folder marker. A restart in the middle of a run loses that run; `/run` again redoes it.

---

## 5. Error channel

Format: **`<folder>` encountered an issue — `<code>` — `<fix>`**, plus a link to the car
channel and the run's log. The fixes below are a first draft, to be refined later.

| Code | Meaning | Fix (draft) |
|---|---|---|
| `BEAR-D01` | Channel has no topic (no car name) | Put the vehicle text in the channel topic, then `/run` again. |
| `BEAR-D02` | `/run` with no folder started | Use `/newfolder` first. |
| `BEAR-D03` | No photos in the folder | Upload the part-number photos, then `/run`. |
| `BEAR-D05` | A photo BEAR can't read (e.g. HEIC) | Re-upload as JPG/PNG/WEBP, delete the original. |
| `BEAR-D06` | A photo couldn't be downloaded | `/run` again. |

`BEAR-D04` (a 💸 message with more than one photo) was retired with 💸 on 2026-10-27.
| `BEAR-D07` | Renaming failed: a photo didn't download or a zip wasn't posted | `/rename` again with the same SKU. |
| `BEAR-N01` | Name model rate limited | Wait and finish the names, or swap the name model. |
| `BEAR-N02` | Name model not responding | Same as N01. |
| `BEAR-N03` | Name model gave unusable names | Swap the name model. |
| `BEAR-K01` | OpenRouter credit / key cap reached (HTTP 402) | Top up or raise the key's cap. |
| `BEAR-K02` | BEAR's own per-folder spend cap reached (`BEAR_RUN_CAP_USD`); some parts not priced | Raise `BEAR_RUN_CAP_USD`, then `/run` again. |
| `BEAR-T01` | Run took over 2 hours, stopped | `/run` again; if it repeats, owner looks at the log. |
| `BEAR-R01` | Anything else | Owner looks at the log. |

`N01`–`N03` and `R01` are the same codes the web page uses (`bear2/ui/server.py:257`). `N04`
(every model gave a wrong first line) can't happen without the first-line check.
`K01`, `K02`, `T01` and the `D` codes are new.

---

## 6. Discord setup (one-off)

1. Create an application and bot at <https://discord.com/developers/applications>.
2. Turn on **Message Content Intent** (Bot page). It is needed to see attachments and text
   on messages that don't mention the bot. It's a simple switch until the bot reaches more
   than 10,000 users.
3. Invite it with scopes `bot` + `applications.commands` and these permissions:
   View Channels, Send Messages, Read Message History, Attach Files, Add Reactions,
   Manage Messages, Use Application Commands.
4. Register `/newfolder` and `/run` for this server only (they appear instantly).
5. Create the error channel and note its ID.
6. Store the bot token in the server's `.env` (`DISCORD_TOKEN`), with `DISCORD_GUILD_ID`,
   `ERROR_CHANNEL_ID` and `CARS_CATEGORY_ID`. The token never goes in chat, logs or code.
   Steps in [SETUP.md](SETUP.md) §2.

---

## 7. Server setup (Debian 13)

Done: see [SETUP.md](SETUP.md). `discordbot/deploy/setup.sh` does the one-command VM setup:
packages, a `bear` user, the code in `/opt/bear`, the venv, `.env` from `env.example`, the
offline tests, and the `bear-bot` systemd service (`Restart=always`). It starts in dev mode
(`BEAR_SIM=ok`).

How long to keep runs (stored under `/var/lib/bear/runs/`): **to decide**.

---

## 8. Testing (before it replaces anything)

The accuracy rule applies: Discord runs must be as accurate as the current flow.

1. **Free check of photo quality.** Upload the test-set photos from the phone through
   Discord, download them back, and compare their pixel size with the originals. BEAR shrinks
   every photo to 1600 px on the long side before the model sees it
   (`bear2/common.py:192`), so if the long side is still ≥ 1600 px the model sees almost the
   same picture.
2. **Paid A/B run.** BEAR on the originals vs. the Discord copies of the same photos;
   compare part numbers and prices. If Discord copies do worse, find another upload method
   (e.g. desktop app, or sending as a file).
3. **Free rehearsals.** Use BEAR's dev mode (`bear2/simulate.py`) so the bot can practise the
   whole Discord flow, including every error code, without spending credits.
4. **Offline tests for the bot's own logic**: finding the folder, picking 💸 messages,
   rejecting a flagged message with two photos, naming `001.jpg`…, error formatting.
5. **First real folder**: one small box, checked by hand against the current flow.

---

## 9. Build order (one PR per piece, version bump last)

1. **BEAR reads webp.** Add `.webp` to the file filters in `bear2/run.py:149` and
   `bear2/stage1_read.py:126`. Everything after that already goes through Pillow, including
   eBay image search (`bear2/image_hints.py:22`). This touches code the Mac flow shares, so it
   needs the owner's OK. — done
2. **Bot skeleton**: connects, `/newfolder`, deletes text-only messages, error channel. — done
3. **`/run`**: collect 💸 photos, checks `D01`–`D06`, download and name, "Running x parts". — done
4. **Run BEAR and post the spreadsheet**, map failures to `N01`–`N03`, `K01`, `R01`. — done
5. **Dev-mode runs and offline bot tests.** — done
6. **Debian setup notes and the `systemd` service file.** — done
7. **Photo-quality test results** written up in `tests/`. (still to do)

---

## 10. Later

- Location from the part-number photo or reactions (NF → `003_NSF.jpg`), once the shadow test shows which works.
  Only a model answer above a cut-off (or confirmed by a second model) is used; otherwise blank.
- "DUPLICATE? check" for the same part number twice in a folder, if needed.
- Which name model replaces Qwen if it keeps failing.
- What to do with finished car channels (archive, delete, or move to a forum channel).
- How long photos and results are kept on the server.
