# Discord BEAR — build plan

Status: **planning only, nothing built yet.** Everything here was agreed with the owner in
October 2026. The research behind it (Discord limits, blind spots, sources) is in
[RESEARCH.md](RESEARCH.md).

The Discord bot is a new, separate way to start BEAR. The Mac `bear` command and `bear ui`
stay exactly as they are.

---

## 1. How it works for the person uploading

1. **One Discord channel per car.** The channel **topic** holds the exact vehicle text, e.g.
   `FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL`. It must start with the make (BEAR uses the
   first word as the make for eBay matching).
2. **`/newfolder name: Q184`** starts a folder (a box of parts). The bot posts a marker
   message: **📁 Folder Q184**. Everything after it belongs to Q184.
3. **Upload the photos** in any groups you like. The **part-number photo goes on its own**
   (one photo in its own message) and gets the **💸 `:money_with_wings:`** reaction.
   That photo is the only one BEAR sees. Every other photo is ignored.
4. **`/run`** ends the folder and runs every 💸 photo in it through BEAR.
5. The bot replies **"Running x parts"**. If you uploaded 20 parts and it says 4, flags are
   missing. It does not wait for a GO; it just runs.
6. The bot posts **one spreadsheet for the folder**, e.g. `Q184-ford-fiesta-mk7.xlsx`,
   with "BEAR found x listings".
7. Anything that goes wrong is posted in the **error channel**:
   "**Q184** encountered an issue — `BEAR-D04` — fix: …".

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
| Hosting | One always-on bot on the owner's **Debian 13** server (Proxmox). Outbound connection to Discord; no port forwarding. |
| Car name | From the **channel topic**. Empty topic = refuse to run. |
| Folders | `/newfolder name:<x>` starts one; `/run` ends and runs it. **One spreadsheet per folder.** |
| Part-number photo | Posted **alone**, reacted with **💸**. Only flagged photos go to BEAR. If this proves unreliable, switch to "first/last photo of a part". |
| Chat text | Never read; text-only messages deleted. |
| "Running x parts" | Information only, no GO button. |
| First-line name check | **Not used in Discord runs.** No automatic model fallback. If Qwen keeps failing, the owner swaps the name model by hand. |
| Name model fails | Run stops, error goes to the error channel. Photo reads and eBay results are kept, so only the names need finishing later. |
| Errors | Separate error channel: folder name + error code + fix. Full error list to be refined later. |
| Who can run it | Anyone in the server. |
| Upload wait | ~30 s with no new photo before running. |
| webp | BEAR reads webp directly (no separate conversion step). HEIC = refuse with an error. |
| Spend cap | The OpenRouter key's own cap is the real limit. |
| Parallel runs | Separate BEAR processes or VMs; **only one bot**. Never the same car twice at once. |
| Same part number twice in a folder | No special handling for now. Add a "DUPLICATE? check" mark only if it becomes a problem. |
| Location (NSF/NSR/OSF/OSR) | **Later.** Plan: four custom emojis reacted on the 💸 photo; the bot puts the code in the filename. |
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
- **Spend cap per run.** Each folder is a fresh process, so the `$1` cap in
  `bear2/common.py:41` counts only that folder. Set `BEAR_RUN_CAP_USD` higher in the bot's
  environment if a full folder can cost more. Two runs on the **same machine** share
  `bear2/spend.jsonl` and can count each other's spending, so give parallel runs separate
  VMs or a higher cap.

How the bot names the photos it hands to BEAR (BEAR reads order and location from the
filename, `bear2/assemble.py:59-72`):
- `001.jpg`, `002.jpg`, … in upload order. The order number must come first: BEAR sorts on
  the first number in the name.
- Later, with location: `003_NSF.jpg`.
- Never put the folder name, the word `NULL`, or `NSF`/`NSR`/`OSF`/`OSR` in a name by
  accident. BEAR skips `NULL` photos (`bear2/run.py:150`) and reads those codes as a location.
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
4. Read every message after the marker. Keep the ones with a 💸 reaction.
   - None = error `BEAR-D03`.
   - A 💸 message with more than one photo = error `BEAR-D04` (the flag can't tell which).
   - A file BEAR can't read (HEIC etc.) = error `BEAR-D05`.
5. Post **"Running x parts"**.
6. Download each flagged photo straight away (Discord links expire after 24 h) into
   `<storage>/<channel>/<folder>-<time>/photos/` as `001.jpg`, `002.jpg`, …
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
| `BEAR-D03` | No 💸 photos in the folder | Add 💸 to each part-number photo, then `/run`. |
| `BEAR-D04` | A 💸 message holds more than one photo | Post the part-number photo on its own, flag it, `/run` again. |
| `BEAR-D05` | A flagged file BEAR can't read (e.g. HEIC) | Re-upload as JPG/PNG/WEBP. |
| `BEAR-D06` | A flagged photo couldn't be downloaded | `/run` again. |
| `BEAR-N01` | Name model rate limited | Wait and finish the names, or swap the name model. |
| `BEAR-N02` | Name model not responding | Same as N01. |
| `BEAR-N03` | Name model gave unusable names | Swap the name model. |
| `BEAR-K01` | OpenRouter credit / key cap reached (HTTP 402) | Top up or raise the key's cap. |
| `BEAR-R01` | Anything else | Owner looks at the log. |

`N01`–`N03` and `R01` are the same codes the web page uses (`bear2/ui/server.py:257`). `N04`
(every model gave a wrong first line) can't happen without the first-line check.
`K01` and the `D` codes are new.

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
6. Store the bot token in the server's `.env` (`DISCORD_TOKEN`) with `ERROR_CHANNEL_ID`.
   The token never goes in chat, logs or code.

---

## 7. Server setup (Debian 13)

1. Clone the repo, e.g. `/opt/bear`, on the `discord-bear` branch.
2. `python3 -m venv .venv && .venv/bin/pip install "Pillow>=10" discord.py`.
3. Check Pillow can read webp:
   `.venv/bin/python -c "from PIL import features; print(features.check('webp'))"`
4. `.env` at the repo root: `OPENROUTER_API_KEY`, `EBAY_APP_ID`, `EBAY_CERT_ID`,
   `JEV_MODEL`, `DISCORD_TOKEN`, `ERROR_CHANNEL_ID`, optionally `BEAR_RUN_CAP_USD`.
5. Run `python3 tests/test_names_offline.py` and a dev-mode run to prove BEAR works on
   Linux. BEAR has only been used on Mac (and Windows via `.env`) so far.
6. A `systemd` service for the bot with `Restart=always`, so it starts at boot and after
   crashes.
7. Storage: `<storage>/<channel>/<folder>-<time>/` holding `photos/`, BEAR's results
   (`results.xlsx`, `agent2_results.md`, `agent3_results.txt`, `trace.json`) and the bot's
   log. How long to keep them: **to decide**.

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
   needs the owner's OK.
2. **Bot skeleton**: connects, `/newfolder`, deletes text-only messages, error channel.
3. **`/run`**: collect 💸 photos, checks `D01`–`D06`, download and name, "Running x parts".
4. **Run BEAR and post the spreadsheet**, map failures to `N01`–`N03`, `K01`, `R01`.
5. **Dev-mode runs and offline bot tests.**
6. **Debian setup notes and the `systemd` service file.**
7. **Photo-quality test results** written up in `tests/`.

---

## 10. Later

- Location reactions (NSF/NSR/OSF/OSR custom emojis → `003_NSF.jpg`).
- "DUPLICATE? check" for the same part number twice in a folder, if needed.
- Which name model replaces Qwen if it keeps failing.
- What to do with finished car channels (archive, delete, or move to a forum channel).
- How long photos and results are kept on the server.
