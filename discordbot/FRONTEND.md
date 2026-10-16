# Discord BEAR: the front end

What people see and touch in the Discord server: the layout, the messages, the feel. The plan
is in [PLAN.md](PLAN.md). The bot's logic (`bot.py`, `folders.py`) is a separate piece of
work. This file only says what that logic should *show*. The last section lists the changes
it needs in order to show it.

- **Every message's look and wording** lives in [`look.py`](look.py).
- **Mockup:** run `python3 discordbot/mockup.py`, then open `discordbot/mockup.html`. It draws
  the real `look.py` posts in Discord's style. Click the channels on the left to switch views.
- **Checks:** `python3 tests/test_discord_look_offline.py` (offline, free).

---

## 1. The feel, in five rules

1. **One message per run.** `/run` posts a single card and edits it as it goes:
   checking → waiting for uploads → *Running 12 parts* → queued → running → done/failed.
   A box should leave three bot messages in the car channel: the 📁 marker, the run card, and
   the spreadsheet. Six status lines per box would bury the photos.
2. **Colour shows the state.** Grey = working, amber = waiting on something, green = done,
   red = problem. You can tell how a box went without reading anything.
3. **The car channel only shows what the uploader can do.** For a problem the uploader can fix
   (`BEAR-D…`), the card says what to do and links to the exact photo. For a problem the owner
   must fix (name model, credit, timeouts), the card says *"Nothing for you to do: the owner
   has been told"*. Mentions of `.env`, logs and model names stay in `#bear-errors`.
4. **Phone first.** Short lines, the action in **bold**, no walls of text. Photo links are
   tap targets.
5. **Quiet by default.** Small refusals (wrong channel, bad box name, "still running") are only
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

**Box names:** the yard's own box label, e.g. `Q184`. Letters, numbers, `-`, `_`.

**Emoji:** 💸 marks the part-number photo; nothing else is needed. Later: four custom emojis
for location (`:nsf:` `:nsr:` `:osf:` `:osr:`). Upload them as server emojis so they look the
same on every phone.

**Roles and permissions**

| Who | Car channels | `#how-to-bear` | `#bear-errors` |
|---|---|---|---|
| `@everyone` (staff) | View, Send, Attach Files, Add Reactions, Use Application Commands, Read History | View, Read History | View, Read History |
| `BEAR` (the bot's role) | + Manage Messages, Embed Links | + Send, Manage Messages (to pin) | + Send, Attach Files, Embed Links |
| Owner | everything | everything | everything |

The plan's permission list (PLAN §6) needs **Embed Links** added. Without it, the cards
don't show.

**Notifications:** set the server's default to *Only @mentions* so each upload doesn't ping
everyone. The owner can set `#bear-errors` to *All messages* so problems still ping them.

---

## 3. Every message, in order

| When | What people see | `look.py` |
|---|---|---|
| Typing `/` | `/newfolder` *Start a new box of parts in this car's channel*, `/run` *Finish the box and price every 💸 photo in it*, `/status` *See which boxes BEAR is working on* | `COMMANDS` |
| `/newfolder Q184` | `📁 Folder **Q184**` + a brand-red card: the car, then the three steps | `folder_card` |
| `/newfolder` while the last box was never run | Only you: *"Heads up: box Q183 was never run…"* | `open_folder_warning` |
| Someone types text | Their message disappears; a notice explains why, then deletes itself after 10 s | `reply("text_removed")` |
| `/run` | One card: *Checking the box* | `run_card("checking")` |
| …photos still arriving | Same card, amber: *Waiting for uploads* | `run_card("waiting")` |
| …photos found | Same card: **Running 12 parts**, saving 7/12, with *"uploaded more? a 💸 is missing"* | `run_card("downloading")` |
| …2 boxes already running | Same card, amber: *Queued: 1 box ahead* | `run_card("queued")` |
| …BEAR running | Same card: *BEAR is pricing the parts (started 4 minutes ago)* | `run_card("running")` |
| Done | Same card, green: *BEAR priced 10 of 12 parts (2 not priced)* + the `.xlsx` | `done_card` |
| Problem the uploader can fix | Same card, red: title, what to do, links to the photo(s) | `problem_card` |
| Problem the owner fixes | Same card, red: *"Nothing for you to do: the owner has been told in #bear-errors"* | `problem_card` |
| Spreadsheet posted but parts lost to money | Amber: *Some parts not priced* | `problem_card(partial=True)` |
| In `#bear-errors` | `**Q184** encountered an issue — \`BEAR-D04\` — fix: …` + red card with meaning, car, link to the box, log excerpt (+ log file) | `error_report` |
| Bot starts | Grey *BEAR is online* card in `#bear-errors` | `bot_started` |
| `/status` | *1 of 2 running*, one line per box with a channel link | `status_card` |

Wording choices:
- **"box"** in messages, because that's what the yard calls it. The command stays `/newfolder`
  (agreed), and the marker still says `📁 Folder Q184`.
- **"BEAR priced 10 of 12 parts"**, not "found 10 listings". The number is parts with a price.
  "Listings" suggests eBay ads and would be wrong (see backend flag B6).

---

## 4. Backend changes needed (for the bot agent, not done here)

These are what the front end needs from `bot.py`. None of them change BEAR itself or the Mac flow.

| # | Change | Why it matters for the feel | Size |
|---|---|---|---|
| B1 | **Send every post through `look.py`** (`channel.send(**look.kwargs(post))`). Replace the plain-text `ch.send(...)` strings in `run_folder`, `report`, `fail`, `status`, `on_ready`. Error-channel text stays from `folders.ERRORS` and is passed into `look.error_report(meaning, fix)`. | One place for all wording. | M |
| B2 | **One live run card.** In `/run`, answer the interaction with a short ephemeral "On it" (or defer), then `card = await ch.send(...)` a normal message and `card.edit(...)` at each state change. Today it posts "Checking the folder …", then "still uploading", "queued", "Running", and the result as separate messages. Use a normal message, not the interaction reply: interaction replies stop being editable after 15 minutes. | Rule 1 | M |
| B3 | **Attach the spreadsheet to the final card edit** (`card.edit(attachments=[file], ...)`). If that fails, post it right under the card. | The box ends as one message. | S |
| B4 | **Problem cards in the car channel use `problem_card`, which hides owner-side fixes.** Today `fail()` posts the `folders.ERRORS` fix in the car channel, so staff see "set BEAR_NAME_MODEL in the server's .env". | Rule 3 | S |
| B5 | **Pass the photo links for D04/D05** into `problem_card(photo_links=[msg.jump_url…])`. Also react ⚠️ on the offending messages so they stand out when scrolling. | The uploader can find the bad photo on a phone. | S |
| B6 | **Count wording.** `report()` says "BEAR found {priced} listings for {photos} parts". `priced` is the number of parts with a price, so this should be "priced X of Y parts" (`done_card`). | Accuracy of what staff are told | S |
| B7 | **Warn on `/newfolder` when the previous box was never run.** Needs "was the last marker followed by a finished run card?" Read the history back the same way `split_folder` does, and look for a green done card or problem card from the bot after it. | Stops a whole box silently going unpriced. | M |
| B8 | **Text-removed notice.** In `on_message`, after deleting, `ch.send(look.reply("text_removed"), delete_after=10)`. Rate-limit it to once a minute per channel. | Deleting without saying why feels broken. | S |
| B9 | **Refuse commands in 🗄️ Done.** Already true if `CARS_CATEGORY_ID` is set, since `car_channel_problem` checks the category. Just change the reply text to `look.reply("not_car_channel")`. | | S |
| B10 | **Command descriptions from `look.COMMANDS`** (the `@bot.tree.command(description=…)` and `@app_commands.describe` strings). | What people read when they type `/`. | S |
| B11 | **Progress while running (optional).** If BEAR prints per-photo progress to the log (the `progress-output` branch did), tail `bear.log` every ~15 s and edit the card: "Pricing 7/12". Edit no more than every 10–15 s (Discord rate limits edits). | A 10-minute run that looks frozen feels broken. | M |
| B12 | **`/status` "(no folder)" placeholder.** `ACTIVE` starts with folder `"(no folder)"` while checking; `status_card` would show that. Use the channel's latest marker name, or skip entries still being checked. | Small polish | S |
| B13 | **Dev-mode badge.** Pass `dev=bool(setting("BEAR_SIM"))` into the cards so simulated runs say "DEV MODE: simulated, no credit spent" in the footer. Then nobody mistakes a rehearsal spreadsheet for real prices. | Trust | S |
| B14 | **Invite permissions:** add **Embed Links** to PLAN §6 / SETUP.md. | Cards don't render without it. | S |
| B15 | **Topic sanity check (optional).** If the topic's first word is a year or a number, warn on `/newfolder` that the make must come first (BEAR uses the first word as the make). | Catches a silent eBay-matching miss | S |

Suggested order: B14, B1, B10, B4, B2+B3, B5, B6, B13, B8, then the rest.

---

## 5. Open questions for the owner

- Is **"box"** the right word in messages, or should they say "folder" to match the command?
- Should the guide be pinned in every car channel, or only in `#how-to-bear`?
- Should finished boxes get a 📦 reaction on the 📁 marker, so it's easy to see which boxes
  have been run when scrolling back? (Needs a small backend change.)
