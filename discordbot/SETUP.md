# Discord BEAR — setting up the VM

How to go from nothing to a working BEAR bot on a Debian 13 VM in Proxmox. The bot and both
BEAR runs live on the VM; the Mac is not involved. Takes about 30 minutes.

1. Make the VM (Proxmox)
2. Make the Discord bot and channels
3. Install BEAR on the VM (one script)
4. Rehearse in dev mode (no credits spent)
5. Go live
6. Everyday jobs and fixing problems

---

## 1. Make the VM

| Setting | Value |
|---|---|
| OS | Debian 13 (trixie) netinst ISO, amd64, uploaded to the Proxmox `local` storage |
| CPU | 2 cores, type `host` |
| RAM | 4 GB (2 GB minimum) |
| Disk | 32 GB, VirtIO SCSI |
| Network | VirtIO, bridge `vmbr0`, DHCP |
| Options | Start at boot: **Yes**; QEMU Guest Agent: **on** |

Why that size: BEAR mostly waits on OpenRouter and eBay, so CPU barely matters. Each run opens
up to 6 photos at once (~300 MB peak), two runs plus the bot fit easily in 4 GB. Flagged photos
are ~3 MB each, so 32 GB holds about 100 big folders before old runs need deleting (§6).

The VM only connects **out** (to Discord, OpenRouter, eBay): no port forwarding, no public IP.

Installing Debian: pick a hostname like `bear-bot`, **set a root password**, create your normal
user, and at "Software selection" untick the desktop; tick only **SSH server** and **standard
system utilities**. After the install, in Proxmox: VM > Hardware > CD/DVD > "Do not use any media".

Optional but handy: give the VM a fixed IP (a DHCP reservation on the router) so you can
`ssh <you>@<ip>` from the Mac instead of using the Proxmox console.

---

## 2. Make the Discord bot and channels

1. <https://discord.com/developers/applications> > **New Application**, name it `BEAR`.
2. **Bot** page:
   - **Reset Token** and copy it. This is `DISCORD_TOKEN`. Never paste it in chat, only in the
     VM's `.env` (§3). If it ever leaks, Reset Token again.
   - Turn on **Message Content Intent** (needed to see the photos on people's messages).
   - Turn off **Public Bot** (only you can invite it).
3. **General Information** page: copy the **Application ID**.
4. Invite the bot. Open this link with your Application ID in place of `APP_ID`:
   ```
   https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot+applications.commands&permissions=2416045136
   ```
   That gives it: View Channels, Send Messages, Read Message History, Attach Files,
   **Embed Links** (the bot's cards don't show without it), Add Reactions, Manage Messages (to
   delete text-only messages and pin the guide), Use Application Commands, plus **Manage
   Channels** and **Manage Roles**, which only the one-off layout script in §3 uses. You can take
   those two away afterwards (Server Settings > Roles > BEAR).
5. Copy the server ID: Discord settings > Advanced > turn on **Developer Mode**, then right-click
   the server icon > **Copy Server ID** → `DISCORD_GUILD_ID`.
6. The channels are made for you in §3 (`setup_server.py`):
   - **🐻 BEAR** with `#how-to-bear` (the guide, pinned) and `#bear-errors` (the error channel),
     both read-only for everyone but the bot.
   - **🚗 Cars**: every car gets a text channel here; the channel **topic** is the exact vehicle
     text, make first, e.g. `FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL`.
   - **🗄️ Done**: drag finished cars here; it's read-only and commands are refused.

   The layout and how every message looks are explained in [FRONTEND.md](FRONTEND.md).
   To make them by hand instead, copy the IDs with right-click: the error channel > **Copy
   Channel ID** → `ERROR_CHANNEL_ID`, the Cars category > **Copy Category ID** → `CARS_CATEGORY_ID`.

---

## 3. Install BEAR on the VM

Log in on the VM (Proxmox console or SSH), become root, and run the setup script:

```
su -
wget -qO setup.sh https://raw.githubusercontent.com/tamaugo/BEAR/discord-bear/discordbot/deploy/setup.sh && bash setup.sh
```

The bot always installs from the `discord-bear` branch, so that branch must stay on GitHub
(never delete it; it is the server edition and isn't merged into `main`).

It installs git and Python, makes a `bear` user, puts the code in `/opt/bear` (branch
`discord-bear`), installs the Python packages, runs the offline tests (no network, no credits)
and installs the `bear-bot` service. It ends with "Almost done. Fill in the PASTE_HERE lines".

Fill in the settings:

```
nano /opt/bear/.env
```

Paste the OpenRouter key and eBay keys (the same ones the Mac uses), the Discord token and the
server ID from §2. Leave `BEAR_SIM=ok` for now. Save with Ctrl+O, Enter, Ctrl+X. Then lay out
the server. This makes the channels, pins the guide and writes the other two IDs into `.env`.
It's safe to run again; it only adds what's missing:

```
/opt/bear/.venv/bin/python /opt/bear/discordbot/setup_server.py --write-env
systemctl restart bear-bot
systemctl status bear-bot        # should say "active (running)"
```

Within a few seconds `#bear-errors` shows a grey **🐻 BEAR is online** card that mentions dev mode.
If not, see §6.

`.env` is only readable by root and the `bear` user and never leaves the VM.

---

## 4. Rehearse in dev mode (no credits spent)

With `BEAR_SIM=ok` every run is BEAR's simulation (`bear2/simulate.py`): the Discord side is
real (folders, 💸, downloads, queue, errors) but the photo reads, eBay results and names are fake
(a Mitsubishi Shogun), so it costs nothing.

1. In Cars, make a channel `test-car` with topic `MITSUBISHI SHOGUN 2007 3.2 DI-D`.
2. `/newfolder name: T1` → the bot posts **📁 Folder T1**.
3. Upload a few photos. Post one on its own and react to it with 💸. Type some text: it is deleted.
4. `/run` → one card that changes as it goes: "Checking the folder", "Running 1 part", then green
   "Done" with the spreadsheet `T1-mitsubishi-shogun-2007.xlsx` attached. The footer says DEV MODE.
5. Try the mistakes: `/run` with no 💸 (→ `BEAR-D03`), 💸 on a message with two photos
   (→ `BEAR-D04`), a channel with no topic (→ `BEAR-D01`). Each one turns the card red with what to
   do (D04 links to the photo), and the error channel gets the code, the fix and the details.
6. Two at once: make a second car channel, start a folder in each, `/run` both, then `/status`.
   With three channels, the third says "queued" and starts when one finishes.
7. Error scenarios: in `.env` change `BEAR_SIM=ok` to `rate-limit`, `no-response`, `unusable` or
   `crash` (no restart needed) and `/run` again → `BEAR-N01`, `N02`, `N03`, `R01`.

---

## 5. Go live

1. `nano /opt/bear/.env`, put `#` in front of `BEAR_SIM=ok`, save, `systemctl restart bear-bot`.
   The "BEAR is online" card no longer mentions dev mode, and the cards lose the DEV MODE footer.
2. **Photo quality check first** (PLAN §8): Discord's phone app may shrink photos. Upload a few
   test-set photos from the phone, run a small folder, and compare the part numbers with the
   Mac run of the same photos. Only switch over once they match.
3. First real folder: a small box, checked by hand.

Cost: about 0.2p per part. `BEAR_RUN_CAP_USD` (default 3 in `.env`) stops a single folder from
spending more than that; the OpenRouter key's own cap is the real limit (`BEAR-K01` when hit).

---

## 6. Everyday jobs and fixing problems

| Job | Command (as root on the VM) |
|---|---|
| Is it running? | `systemctl status bear-bot` |
| Live log | `journalctl -u bear-bot -f` (Ctrl+C to stop watching) |
| Restart | `systemctl restart bear-bot` (a running folder is lost; `/run` it again) |
| Update to the latest `discord-bear` | `/status` in Discord first (updating restarts the bot), then `bash /opt/bear/discordbot/deploy/setup.sh` |
| Change a setting | `nano /opt/bear/.env`. `BEAR_RUN_CAP_USD`, `BEAR_NAME_MODEL`, `BEAR_SIM` apply to the next `/run`; anything else needs a restart. |
| Swap the name model (Qwen keeps failing, `BEAR-N01`–`N03`) | In `.env`: `BEAR_NAME_MODEL=google/gemini-3.1-flash-lite` (or `anthropic/claude-haiku-5.5`) |
| Disk space | `df -h /` and `du -sh /var/lib/bear/runs/*` |
| Delete runs older than 60 days | `find /var/lib/bear/runs -mindepth 2 -maxdepth 2 -type d -mtime +60 -exec rm -rf {} +` |

**Where things are:** each run is in
`/var/lib/bear/runs/<channel>-<id>/<folder>-<date-time>/`: `photos/` (`001.jpg`, … in upload
order), `photos.tsv` (which Discord message each photo came from, so a spreadsheet row can be
traced back), `results/` (`results.xlsx`, `agent2_results.md`, `trace.json`, …), `bear.log` and
`spend.jsonl` (what that folder cost).

| Problem | Fix |
|---|---|
| `/run` says "The application did not respond" | The bot is down or the VM has no internet: `systemctl status bear-bot`, then the log. |
| `/newfolder` and `/run` don't appear | Wrong `DISCORD_GUILD_ID`, or the bot was invited without `applications.commands`: re-open the invite link (§2.4). Then restart. |
| Log says `PrivilegedIntentsRequired` | Turn on Message Content Intent (§2.2), restart. |
| Log says `Improper token` / `LoginFailure` | Token wrong or reset: paste the new one in `.env`, restart. |
| Text messages aren't deleted | `CARS_CATEGORY_ID` missing/wrong, the channel isn't in Cars, or the bot lacks Manage Messages. |
| Nothing arrives in the error channel | Wrong `ERROR_CHANNEL_ID`, or the bot can't see/post there (channel permissions). |
| Setup stops at "flow test failed" | The last lines show why; the full output is in `/var/lib/bear/flow-test.log`. |

Error codes in the error channel (fixes are in each message):
`D01` no topic · `D02` no folder · `D03` no 💸 · `D04` two photos on one 💸 · `D05` file BEAR can't
read (HEIC) · `D06` download failed · `N01`/`N02`/`N03` name model rate limited / not responding /
unusable names · `K01` OpenRouter out of credit · `K02` BEAR's per-folder cap · `T01` run took over
2 hours · `R01` anything else (log attached).
