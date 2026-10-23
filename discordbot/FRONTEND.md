# Discord BEAR: the front end

What people see and touch in the Discord server: the layout, the messages, the feel. The plan
is in [PLAN.md](PLAN.md), and setting up the VM and the bot is in [SETUP.md](SETUP.md).

- **Every message's look and wording** lives in [`look.py`](look.py). `bot.py` decides *when*
  to post, `look.py` decides *what it looks like*.
- **The server layout** is made by [`setup_server.py`](setup_server.py) (SETUP §3). It's safe to run again.
- **Mockup:** run `python3 discordbot/mockup.py`, then open `discordbot/mockup.html`. It draws
  the real `look.py` posts in Discord's style. Click the channels on the left to switch views.
- **Checks:** `python3 tests/test_discord_look_offline.py` checks the wording and Discord's
  limits. `tests/test_discord_flow_offline.py` drives the real bot through every card.

---

## 1. The feel, in five rules

1. **One message per run.** `/run` posts a single card and edits it as it goes:
   checking → waiting for uploads → *Running 12 parts* → queued → running → done/failed.
   A folder should leave three bot messages in the car channel: the 📁 marker, the run card, and
   the spreadsheet. Six status lines per folder would bury the photos.
2. **Colour shows the state.** Grey = working, amber = waiting on something, green = done,
   red = problem. You can tell how a folder went without reading anything.
3. **The car channel only shows what the uploader can do.** For a problem the uploader can fix
   (`BEAR-D…`), the card says what to do and links to the exact photo. For a problem the owner
   must fix (name model, credit, timeouts), the card says *"Nothing for you to do: the owner
   has been told"*. Mentions of `.env`, logs and model names stay in `#bear-errors`.
4. **Phone first.** Short lines, the action in **bold**, no walls of text. Photo links are
   tap targets.
5. **Quiet by default.** Small refusals (wrong channel, bad folder name, "still running") are only
   seen by the person who typed the command. Discord shows them as "Only you can see this".

---

## 2. Server layout

```
BEAR Parts
├── 🐻 BEAR
│   ├── #how-to-bear       read-only; the bot posts and pins the guide (look.guide)
│   └── #bear-errors       read-only for staff; bot posts problems + "BEAR is online"
├── 🚗 Cars                (CARS_CATEGORY_ID) one channel per car
│   ├── #ford-fiesta-mk7-2012     topic: FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL
│   └── #vw-golf-mk6-2010         topic: VW GOLF MK6 2010 ESTATE 1.6 TDI
└── 🗄️ Done                finished cars are moved here (keeps Cars under 50 channels)
```

**Car channels**
- Name: `make-model-mark-year`, lowercase, e.g. `ford-fiesta-mk7-2012`. The name is only for
  people. BEAR reads the car from the **topic**.
- Topic: the exact vehicle text, **make first**, e.g. `FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL`.
- Pin the guide in each car channel too (right-click the guide → Pin, or have the bot post it).
- When a car is finished, drag the channel into **🗄️ Done**. Commands there are refused.
  (Discord allows 50 channels per category and 500 per server.)

**Folder names:** the yard's own box label, e.g. `Q184`. Letters, numbers, `-`, `_`.

**Emoji:** 💸 marks the part-number photo; nothing else is needed. Later: four custom emojis
for location (`:nsf:` `:nsr:` `:osf:` `:osr:`). Upload them as server emojis so they look the
same on every phone.

**Roles and permissions**

| Who | Car channels | `#how-to-bear` | `#bear-errors` |
|---|---|---|---|
| `@everyone` (staff) | View, Send, Attach Files, Add Reactions, Use Application Commands, Read History | View, Read History | View, Read History |
| `BEAR` (the bot's role) | + Manage Messages, Embed Links | + Send, Manage Messages (to pin) | + Send, Attach Files, Embed Links |
| Owner | everything | everything | everything |

`setup_server.py` sets these up. The bot needs **Embed Links**, or the cards don't show. The
invite link in SETUP §2 includes it.

**Notifications:** set the server's default to *Only @mentions* so each upload doesn't ping
everyone. The owner can set `#bear-errors` to *All messages* so problems still ping them.

---

## 3. Every message, in order

| When | What people see | `look.py` |
|---|---|---|
| Typing `/` | `/newfolder` *Start a new folder (one box of parts) in this car's channel*, `/run` *Finish the folder and price every 💸 photo in it* (optional `folder:` for an earlier folder), `/status` *See which folders BEAR is working on* | `COMMANDS` |
| `/newfolder Q184` | `📁 Folder **Q184**` + a brand-red card: the car, then the three steps | `folder_card` |
| `/newfolder` while the last folder was never run | Only you: *"Heads up: folder Q183 was never run… use /run folder:Q183"* | `open_folder_warning` |
| `/run folder:` with a name that isn't in the channel | Only you: *"There's no folder NOPE in this channel…"* | `reply("no_such_folder")` |
| Someone types text | Their message disappears; a notice explains why, then deletes itself after 10 s | `reply("text_removed")` |
| `/run` | One card: *Checking the folder* | `run_card("checking")` |
| …photos still arriving | Same card, amber: *Waiting for uploads* | `run_card("waiting")` |
| …photos found | Same card: **Running 12 parts**, saving 7/12, with *"uploaded more? a 💸 is missing"* | `run_card("downloading")` |
| …2 folders already running | Same card, amber: *Queued: 1 folder ahead* | `run_card("queued")` |
| …BEAR running | Same card: *BEAR is pricing the parts (started 4 minutes ago)* | `run_card("running")` |
| Done | Same card, green: *BEAR priced 10 of 12 parts (2 not priced)* + the `.xlsx` | `done_card` |
| Problem the uploader can fix | Same card, red: title, what to do, links to the photo(s) | `problem_card` |
| Problem the owner fixes | Same card, red: *"Nothing for you to do: the owner has been told in #bear-errors"* | `problem_card` |
| Spreadsheet posted but parts lost to money | Amber: *Some parts not priced* | `problem_card(partial=True)` |
| In `#bear-errors` | `**Q184** encountered an issue — \`BEAR-D04\` — fix: …` + red card with meaning, car, link to the folder, log excerpt (+ log file) | `error_report` |
| Bot starts | Grey *BEAR is online* card in `#bear-errors` | `bot_started` |
| `/status` | *1 of 2 running*, one line per folder with a channel link | `status_card` |

Wording choices:
- **"folder"** everywhere, matching `/newfolder` and the 📁 marker.
- **"BEAR priced 10 of 12 parts"**, not "found 10 listings". The number is parts with a price.
  "Listings" suggests eBay ads, which would be wrong.

---

## 4. What's built, and what's left for the backend

**Built into `bot.py` (front-end changes only; the run, queue and download logic is unchanged):**
every post goes through `look.py`. Other changes:
- One live run card per `/run`, with the spreadsheet attached to its final edit.
- Owner-side fixes are kept out of car channels.
- D04/D05/D06 cards link to the exact photos.
- "priced X of Y parts".
- A private heads-up on `/newfolder` when the previous folder was never run, or when the topic
  doesn't start with the make.
- A self-deleting "text was removed" notice, at most once a minute per channel.
- A DEV MODE footer on simulated runs.
- `/status` is a private card.
- Command descriptions come from `look.COMMANDS`.
- The invite link now includes Embed Links.

**Still open for the backend (not done):**

| # | Change | Why it matters for the feel | Size |
|---|---|---|---|
| B1 | **Progress while running.** If BEAR printed per-photo progress to `bear.log` (the `progress-output` branch did), the bot could tail it every ~15 s and edit the card to "Pricing 7/12". | A 10-minute run that looks frozen feels broken. | M |
| B2 | **⚠️ reaction on the offending photos** for D04/D05. `flagged_photos` would need to hand back the message objects, not just their links in the detail text. | They stand out when scrolling, not only via the link. | S |
| B3 | **Restart leaves a grey "Running" card behind.** On startup the bot could find cards still in a running state (bot messages whose embed colour is grey/amber) and turn them red: "The bot restarted, /run again". | Otherwise a card says "running" forever. | M |
| B4 | **Folder marker gets a ✅ after a successful run** so it's easy to see which folders are done when scrolling back. | Scanning a busy car channel | S |
| B5 | **Cost on the done card** ("cost 3p") from the run's `spend.jsonl`. `done_card` has a footer slot for it. | Owner sees spend without the VM | S |

## 5. Open questions for the owner

- Should the guide be pinned in every car channel, or only in `#how-to-bear`?
