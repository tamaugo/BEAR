# Discord BEAR: front end ↔ back end contract

Agreed between the front-end agent (Discord look, wording, server layout) and the back-end agent
(bot runtime, BEAR runs, VM, deploy). **The back-end agent edits this file**; the front end proposes
changes by message. Written from the code on `discord-bear` at `78be6cb`.

There is no HTTP API. The interfaces are:

1. **Discord surface**: what people type and see (§1)
2. **`look.py` ↔ `bot.py`**: the bot asks `look.py` for every post (§2)
3. **Bot ↔ BEAR run**: a subprocess plus a run folder on disk (§3)
4. **Settings and auth**: `.env`, the Discord token, intents and permissions (§4)
5. **Error codes**: shared by both sides (§5)

| Owner | Files |
|---|---|
| Front end | `discordbot/look.py`, `discordbot/setup_server.py`, `discordbot/FRONTEND.md`, `discordbot/mockup.*`, `tests/test_discord_look_offline.py`; the `look.*` call sites in `bot.py` (which post, when) |
| Back end | `discordbot/bot.py` (run, queue, download, settings, lifecycle), `discordbot/folders.py`, `discordbot/deploy/*`, `discordbot/SETUP.md`, `bear2/*`, `tests/test_discord_offline.py`, `tests/test_discord_flow_offline.py`, this file |

A change that crosses the line (e.g. a new `look.run_card` argument the bot must pass) is made by
the owner of each file, announced by message with branch + commit.

---

## 1. Discord surface

Slash commands are registered to **one guild** (`DISCORD_GUILD_ID`) on start, so they appear at once.
Names are fixed; descriptions come from `look.COMMANDS`.

| Command | Where | Visible reply | Effect |
|---|---|---|---|
| `/newfolder name:<str>` | a car channel | `look.folder_card` (public). Extra notes are ephemeral: `open_folder_warning`, `reply("topic_order")` | Starts a folder. The marker content line is exactly `📁 Folder **<name>**` (`folders.MARKER`): **the front end must not change this line**; `/run` finds the folder by it. |
| `/run [folder:<str>]` | a car channel | ephemeral `reply("on_it")`, then **one run card** (a normal channel message) edited through the states, ending in `done_card` + the `.xlsx` attached, or `problem_card` | Reads the folder (the newest, or the newest one called `folder`), downloads the 💸 photos, queues, runs BEAR, posts the result. A folder's messages run from its marker to the next marker. |
| `/status` | anywhere | `look.status_card` (ephemeral) | Lists running and queued folders. |

**Rules for `name`** (and `/run folder:`): `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$`; anything else → `reply("bad_name")`.

**Refusals** (ephemeral `look.reply` keys):

| Key | When |
|---|---|
| `not_car_channel` | not a text channel, or not in `CARS_CATEGORY_ID` |
| `no_topic` | `/newfolder` with no channel topic |
| `busy` | a `/run` of the **same folder** is already active; it gets `folder` and `state`. Other folders, even of the same car, are not refused |
| `no_such_folder` | `/run folder:<x>` and this channel has no folder `<x>`; it gets `folder`. Not reported to the error channel |
| `oops` | an unhandled command error (logged) |

**Car channel behaviour**:
- A message with no file, in a channel under `CARS_CATEGORY_ID`, is deleted.
- `reply("text_removed")` is posted at most once per 60 s per channel and deletes itself after 10 s.

**Error channel** (`ERROR_CHANNEL_ID`) gets:
- `look.bot_started` once per process start;
- `look.error_report` for every problem, with `<folder>-log.txt` attached when a run log exists.

### Run card states (`look.run_card(state, ...)`)

| state | Sent when | Arguments the bot passes |
|---|---|---|
| `checking` | /run starts (folder `None`), then again once the folder is known | `folder`, `car`, `dev` |
| `waiting` | the newest upload is younger than `BEAR_UPLOAD_WAIT` | `wait_seconds` |
| `downloading` | after the 💸 photos are picked; then every 5 photos | `parts`, `got` |
| `queued` | all `BEAR_MAX_RUNS` slots are busy | `parts`, `queue_ahead`, `max_runs` |
| `running` | a slot is free and BEAR starts | `parts`, `since` (unix time) |

The final edit is one of:
- `look.done_card(folder, car, parts, priced, filename, minutes, dev)`, with the file attached as
  `folders.xlsx_name(folder, car)`, e.g. `Q184-ford-fiesta-mk7.xlsx`.
- `look.problem_card(folder, code, error_channel_id, photo_links, dev, partial)`: a red card. A
  `partial` problem (K01/K02 found in `trace.json` after a successful run) is a **new amber** card
  under the green one, which keeps its spreadsheet.

If the card can't be edited, a new card is posted. Card edits are throttled by design (every 5
downloads), because Discord rate-limits edits.

## 2. `look.py` ↔ `bot.py`

**Stable API**: `bot.py` calls only these. Every card returns a post (see below).

| Function | Notes |
|---|---|
| `folder_card(name, car, dev)` | `content` **must equal** `folders.marker(name)`; `bot.py` enforces it |
| `run_card(state, folder\|None, car, parts, got, queue_ahead, since, wait_seconds, max_runs, dev)` | state: `checking`, `waiting`, `downloading`, `queued` or `running` |
| `done_card(folder, car, parts, priced, filename, minutes, dev)` | |
| `problem_card(folder\|None, code, error_channel_id, photo_links, dev, partial)` | |
| `error_report(folder, code, meaning, fix, channel_id, car, detail, jump_url, dev)` | |
| `status_card(active, max_runs, now, dev)` | `active` = `[{folder, channel_id, state, parts, since}]` |
| `bot_started(max_runs, sim, version)` | |
| `guide(error_channel_id)` | |
| `open_folder_warning(previous)` | ephemeral note on `/newfolder` |
| `reply(key, **kw)` | keys: `not_car_channel`, `bad_name`, `busy`, `no_such_folder`, `no_topic`, `on_it`, `topic_order`, `text_removed`, `oops` |
| constants | `COMMANDS`, `TITLES`, `UPLOADER_FIX`, `LIMITS` |

- **A post** is a plain dict: `{"content": str | None, "embeds": [embed_dict]}`.
  - `embed_dict` is Discord's embed JSON: `color`, `title`, `description`, `fields[{name, value, inline}]`, `footer{text}`.
  - `look.py` cuts every field to Discord's limits (`look.LIMITS`).
- **The bot sends** a post with `channel.send(**look.kwargs(post))` or `message.edit(**look.kwargs(post))`.
  `look.kwargs` is the only place `look.py` imports discord.py, so the rest of `look.py` tests offline.
- **Small replies** are plain strings: `look.reply(key, **values)`.
- **Colours**: grey = working, amber = waiting or queued, green = done, red = problem. "DEV MODE" is
  in the footer when `BEAR_SIM` is set (`dev=True`).

Example post (`run_card("running", "Q184", "FORD FIESTA MK7 2012 1.4 DIESEL", parts=12, since=1792500000)`):

```json
{"content": null,
 "embeds": [{"color": 5132632, "title": "📁 Q184 · Running",
             "description": "BEAR is pricing 12 parts ...",
             "fields": [{"name": "Car", "value": "FORD FIESTA MK7 2012 1.4 DIESEL", "inline": false}],
             "footer": {"text": "..."}}]}
```

The exact wording is the front end's choice. The bot only relies on the function names, the arguments
in the table above, and the post shape.

## 3. Bot ↔ BEAR run

**Run folder**: `$BEAR_STORAGE/<channel-slug>-<channel-id>/<folder>-<YYYYmmdd-HHMMSS>[-n]/`. On the
VM, `BEAR_STORAGE=/var/lib/bear/runs`, which is on the BEAR SSD.

| Path | Written by | Contents |
|---|---|---|
| `photos/001.jpg …` | bot | the 💸 photos in upload order; the extension is kept (`.jpg .jpeg .png .webp`) |
| `photos.tsv` | bot | `001.jpg <TAB> original filename <TAB> message link`, one line per photo |
| `bear.log` | BEAR (stdout + stderr) | the whole run log |
| `spend.jsonl` | BEAR | this folder's spend only (`BEAR_SPEND_LEDGER`) |
| `results/results.xlsx` | BEAR | the spreadsheet (required for success) |
| `results/agent2_results.md` | BEAR | `photo \| part no \| … ` lines; ` \| FAILED \| ` marks an unpriced part |
| `results/trace.json` | BEAR | per-photo details; K01/K02 text here means a partial failure |

**Command**: `python bear2/run.py <photos> "<car>" <results>`, or `bear2/simulate.py` with the same
arguments when `BEAR_SIM` is set.
- Working directory: the repo.
- stdin is `/dev/null`, so BEAR skips the first-line check.
- It runs in its own process group, which is killed after `BEAR_RUN_TIMEOUT` seconds.

**Environment**: the bot's environment plus every `BEAR_*` line in `.env`, read at the start of each
run. `DISCORD_TOKEN` and `BEAR_WEB_ASK` are removed.

**Result**:
- Exit 0 with `results.xlsx` present → done card.
- Timeout → `BEAR-T01`.
- Anything else → `folders.classify(bear.log)`, which gives N01–N03, K01, K02 or R01.

**Concurrency**:
- At most `BEAR_MAX_RUNS` BEAR processes run at once (`asyncio.Semaphore`).
- One active `/run` per **folder** (`ACTIVE`, keyed by the folder's marker message). Two folders of
  the same car run side by side; each has its own run folder and `spend.jsonl`.
- The upload wait re-reads the same folder by its marker, so a `/newfolder` during the wait doesn't
  take the run over.
- The queue is FIFO by `queued_at`.

## 4. Settings and auth

The token, keys and IDs live **only** in `/opt/bear/.env`: mode 600, owner `bear`, on the BEAR SSD.
They never go in chat, logs or git.

| Key | Required | Notes |
|---|---|---|
| `DISCORD_TOKEN` | yes | the bot's token. Exactly **one** running bot per token (the VM). |
| `DISCORD_GUILD_ID` | yes | the server the commands are registered in |
| `ERROR_CHANNEL_ID` | yes | `#bear-errors` |
| `CARS_CATEGORY_ID` | no | if unset, commands work anywhere and nothing is deleted |
| `OPENROUTER_API_KEY`, `EBAY_APP_ID`, `EBAY_CERT_ID` | for live runs | not needed in dev mode |
| `BEAR_MAX_RUNS` (2), `BEAR_UPLOAD_WAIT` (30), `BEAR_RUN_TIMEOUT` (7200) | no | read at start |
| `BEAR_RUN_CAP_USD`, `BEAR_NAME_MODEL`, `BEAR_SIM` | no | read at each run |

Behaviour:
- `PASTE_HERE`, blank or missing counts as unset.
- A missing required setting, a non-numeric number, a refused token, or Message Content Intent
  turned off → the bot exits **78** with the reason in the journal, and systemd does not restart it
  (`RestartPreventExitStatus=78`).

**Discord application**:
- **Message Content Intent** on.
- Invited with scopes `bot applications.commands` and permissions **`2251802229730384`**
  (`discordbot/SETUP.md` §2).
- **Embed Links** is required, otherwise the cards don't show.
- Pin Messages (1<<51) is used for the guide.
- Manage Channels and Manage Roles are only needed by `setup_server.py`.

**Server layout** (`setup_server.py`):
- 🐻 BEAR: `#how-to-bear` (the pinned guide) and `#bear-errors` (`ERROR_CHANNEL_ID`)
- 🚗 Cars: `CARS_CATEGORY_ID`, one channel per car, the topic is the car
- 🗄️ Done: read-only

## 5. Error codes

Defined in `folders.ERRORS` (back end: meaning plus the owner's fix). The front-end text is in
`look.TITLES` and `look.UPLOADER_FIX`, where `None` means "nothing for you to do, the owner has been
told". **Every code must exist in all three**:
- The back end owns the code set.
- **A new code in `folders.ERRORS` needs a message to the front end first**, so `look.py` gets its
  title and uploader text in the same PR.
- `tests/test_discord_look_offline.py` imports `folders.ERRORS`, so a missing entry fails the test.

| Code | Cause | Uploader can fix |
|---|---|---|
| D01 | no channel topic | yes |
| D02 | no folder | yes |
| D03 | no 💸 | yes |
| D04 | 💸 on a message with more than one file (links to the messages) | yes |
| D05 | 💸 file not jpg/png/webp (links) | yes |
| D06 | download failed 3 times (link) | yes |
| N01 / N02 / N03 | name model rate-limited / not answering / unusable names | no |
| K01 | OpenRouter 402 | no |
| K02 | BEAR spend cap | no |
| T01 | timeout | no |
| R01 | anything else | no |

## 6. Deployment (back end)

- **VM**: Debian 13, Proxmox VM 108. The code is in `/opt/bear` on `discord-bear`; update it with
  `sudo bash /opt/bear/discordbot/deploy/setup.sh`.
- **Service**: `bear-bot.service` runs as user `bear`, with the drop-in `bear-bot.service.d/ssd.conf`
  (`RequiresMountsFor` the SSD).
- **Storage**: `/opt/bear`, `/var/lib/bear` and `/var/log/journal` are bind mounts from the Kingston
  SSD (`/mnt/bear-ssd`, label `BEAR-SSD`).
- **Logs**: `journalctl -u bear-bot`, plus `bear.log` in each run folder.

## 7. Integration checks

Run against the **VM bot** in the real server, one bot online.

| # | Check | Pass when |
|---|---|---|
| C1 | Start | the `bot_started` card is in #bear-errors; `/newfolder`, `/run`, `/status` show in the command list |
| C2 | Dev run | `/newfolder T1`, 2 photos, 1 💸, `/run` → one card goes checking → running → green, with `T1-<car>.xlsx` attached |
| C3 | Person error | `/run` with no 💸 → red D03 card in the channel, and an `error_report` in #bear-errors |
| C4 | Parallel | 3 car channels `/run` together → two run, one shows queued; `/status` lists them; all three finish |
| C5 | Text | typed text in a car channel is deleted, and the notice appears and goes after 10 s |
| C6 | Restart | after a VM reboot, the bot is back (C1) with no manual step |
| C7 | Live | with `BEAR_SIM` off, one real part-number photo → green card with a real part number and price |
| C8 | D04 links | 💸 on a 2-photo message → red D04 card whose photo link jumps to that message |
| C9 | Unrun folder | `/newfolder` while the previous folder was never `/run` → a private warning |
| C10 | Same car twice | in one car channel: `/newfolder A`, 💸, `/run`; straight away `/newfolder B`, 💸, `/run` → both cards running at once, each spreadsheet has only its own parts; `/run folder:A` again while A runs → `busy` |

**Who checks what**:
- **Front end** checks the Discord side through the bot's REST API (messages and embeds) and screenshots.
- **Back end** checks the VM side: `journalctl -u bear-bot` and the run folders on the SSD.
- Slash commands and uploads must come from a human account (bots can't trigger them).
