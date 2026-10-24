# Discord BEAR — research notes

Background for [PLAN.md](PLAN.md): what Discord allows, the blind spots found in the first
version of the pipeline, and how each one was settled. Researched October 2026.

---

## Discord facts that shape the design

| Fact | Effect on BEAR | Source |
|---|---|---|
| A bot keeps an outbound connection (the "gateway") open to Discord; commands arrive down it. | No port forwarding, public IP or website needed. If the server or home internet is down, `/run` says "The application did not respond". | Discord developer docs |
| Up to **10 photos per message**; phones often send a selection as one message. | **Reactions belong to the whole message**, not one photo. The 💸 photo must be posted on its own. | [Discord.https API reference](https://discordhttps.js.org/interfaces/index.APIMessage.html) |
| A command must be answered within **3 seconds**; the bot can then reply to it for **15 minutes**. | Answer at once; post the spreadsheet as a normal message in case a folder takes longer. | [discord.js guide](https://discordjs.guide/slash-commands/response-methods) |
| Attachment links **expire after 24 hours** (`ex`/`is`/`hm` in the URL). Re-reading the message gives fresh links. | Download flagged photos at `/run` time; keep copies on the server; store message IDs, not links. | [BleepingComputer](https://www.bleepingcomputer.com/news/security/discord-will-switch-to-temporary-file-links-to-block-malware-delivery) |
| **Message Content** intent is needed to see text and attachments on messages that don't mention the bot. Free switch until the bot can reach 10,000+ users. | Turn it on in the developer portal. | [Discord docs: privileged intents](https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review.md) |
| Free upload limit is **20 MB** per file (raised from 10 MB in Aug 2026). | The spreadsheet is text only (~5 KB); no problem. | [Neowin](https://neowin.net/news/discord-raises-file-size-upload-limit-for-its-non-subscribers/) |
| The phone app is reported to **shrink photos** on upload; no setting for images. Desktop is said to keep originals. Not officially documented. | Must be tested on the test set (PLAN §8). | [Discord community request](https://support.discord.com/hc/it/community/posts/360050557372-implement-Image-compression-on-upload-for-mobile), [Discord help: mobile uploads](https://support.discord.com/hc/en-us/articles/9665451164951) |
| Text channel names are **lowercased, spaces become hyphens**, max 100 characters; whether `.` survives is unconfirmed. | The car name comes from the channel **topic**, not the name. | [Discord community: channel names](https://support.discord.com/hc/fr/community/posts/360048219691-Text-channels-names) |
| About **500 channels per server, 50 per category** (third-party figures). | One channel per car will hit it eventually: archive or delete finished cars. | [Mava guide](https://www.mava.app/blog/everything-you-need-to-know-about-discord-channel-category-and-thread-limits) |
| Command names can't contain spaces. | `/newfolder`, not `/new folder`. | Discord developer docs |
| Bots can't see an upload that is still in progress. | `/run` waits for ~30 s with no new photo; "Running x parts" is the backstop. | Discord developer docs |
| Two bot processes with the same token both answer every command. | Only **one** bot; it can start several BEAR runs. | Discord developer docs |

---

## Facts about BEAR that shape the design

| Fact | Where | Effect |
|---|---|---|
| Row order comes from the **filename** (the NSF/NSR/OSF/OSR location words and the `NULL` skip were removed from the server code). | `bear2/assemble.py:image_no` | Discord names like `IMG_4821.jpg` / `image0.jpg` would lose the order. The bot renames photos `001.jpg`… |
| Only `.jpg/.jpeg/.png` are read. | `bear2/run.py:149`, `bear2/stage1_read.py:126` | Add `.webp` (PLAN §9 step 1). Everything later re-encodes through Pillow. |
| Every photo is shrunk to 1600 px on the long side before the model sees it. | `bear2/common.py:192` | Makes the free pixel-size check meaningful. |
| With no terminal and no web page, the first-line check is skipped and a failed name model stops the run with "No names were written". | `bear2/assemble.py:187`, `bear2/assemble.py:280` | The bot needs no BEAR change for this. |
| The `$1` spend cap counts spending since the process started, from a shared ledger. | `bear2/common.py:41` | One process per folder; parallel runs on one machine count each other's spend. |
| Rate limits are detected (HTTP 429) and retried for ~1 minute; 400/401/402 stop at once. | `bear2/common.py:144-186` | 402 (credit / key cap) gets its own error code `BEAR-K01`. |
| Keys come from the environment, then `.env`; only the `bin/bear` launcher uses the macOS Keychain. | `bear2/common.py:19`, `tools/jev_client.py:69` | Works on Debian with a `.env` file. |
| The spreadsheet is text only: part info, price, url, image (filename). | `harness/make_xlsx.py` | Small enough for Discord; the image column is kept as is for now. |

---

## Blind spots found, and how they were settled

| # | Blind spot | Settled |
|---|---|---|
| 1 | A reaction flags a whole message, not one photo. | The part-number photo is always posted alone. Bot rejects a flagged message with 2+ photos (`BEAR-D04`). |
| 2 | Discord filenames lose location and order. | Bot renames to `001.jpg`…; location via reactions later. |
| 3 | Channel names mangle the car name. | Car name from the channel topic. |
| 4 | BEAR stops to ask for first-line approval. | Not used in Discord runs; no automatic fallback; owner swaps the name model by hand. |
| 5 | Long-running bot would trip the `$1` cap. | One BEAR process per folder; OpenRouter key cap is the real limit. |
| 6 | Discord may shrink photos and lower accuracy. | To be tested (PLAN §8). Same camera as now. |
| 7 | webp/HEIC skipped silently. | BEAR reads webp directly; HEIC refused with `BEAR-D05`. |
| 8 | Which messages count, re-runs, stray chat. | Folders via `/newfolder` + `/run`; text-only messages deleted; re-run redoes the folder. |
| 9 | 15-minute reply window. | Spreadsheet posted as a normal message. |
| 10 | Attachment links expire after 24 h. | Download at `/run` time; keep copies on the server. |
| 11 | Image column is a meaningless filename in Discord. | Kept as is for now. |
| 12 | Parallel runs share files and rate limits. | Separate processes/VMs, one bot, never the same car twice at once. |
| 13 | Keys, permissions, Mac flow. | `.env` on Debian; permissions in PLAN §6; Mac flow untouched. |
| 14 | 500-channel limit. | Fine for now. |
| — | Same part number twice in one folder (by mistake or genuinely two parts). | No special handling unless it becomes a problem. |
| — | Mid-upload `/run`. | Waits ~30 s with no new photo. |
