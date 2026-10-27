# Discord BEAR — setting up the VM

How to go from nothing to a working BEAR bot on a Debian 13 VM in Proxmox. The bot and both
BEAR runs live on the VM; the Mac is not involved. Takes about 30 minutes.

1. Make the VM (Proxmox)
2. Make the Discord bot and channels
3. Install BEAR on the VM (one script)
4. Rehearse in dev mode (no credits spent)
5. Go live
6. Everyday jobs and fixing problems
7. Is BEAR up? (down/up messages in the error channel)
8. Update log (#update-log)

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
up to 6 photos at once (~300 MB peak), two runs plus the bot fit easily in 4 GB. Every photo in a
folder is kept (~3 MB each), so watch the disk and delete old runs (§6).

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
   https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot+applications.commands&permissions=2251802229730384
   ```
   That gives it: View Channels, Send Messages, Read Message History, Attach Files,
   **Embed Links** (the bot's cards don't show without it), Add Reactions, Manage Messages (to
   delete text-only messages), **Pin Messages** (to pin the guide; Discord split it from Manage
   Messages), Use Application Commands, plus **Manage
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

Within a few seconds `#bear-errors` shows a green **🟢 BEAR is up** card with the version, that mentions dev mode.
If not, see §6.

`.env` is only readable by root and the `bear` user and never leaves the VM.

---

## 4. Rehearse in dev mode (no credits spent)

With `BEAR_SIM=ok` every run is BEAR's simulation (`bear2/simulate.py`): the Discord side is
real (folders, downloads, queue, errors) but the photo reads, eBay results and names are fake
(a Mitsubishi Shogun), so it costs nothing.

1. In Cars, make a channel `test-car` with topic `MITSUBISHI SHOGUN 2007 3.2 DI-D`.
2. `/newfolder name: T1` → the bot posts **📁 Folder T1**.
3. Upload two photos. Type some text: it is deleted.
4. `/run` → one card that changes as it goes: "Checking the folder", "Running 2 parts", then green
   "Done" with the spreadsheet `T1-mitsubishi-shogun-2007.xlsx` attached. The footer says DEV MODE.
5. Try the mistakes: `/run` in a new folder with no photos (→ `BEAR-D03`), an iPhone HEIC photo
   (→ `BEAR-D05`), a channel with no topic (→ `BEAR-D01`). Each one turns the card red with what to
   do (D05 links to the photo), and the error channel gets the code, the fix and the details.
6. Two at once: make a second car channel, start a folder in each, `/run` both, then `/status`.
   With three channels, the third says "queued" and starts when one finishes.
7. Error scenarios: in `.env` change `BEAR_SIM=ok` to `rate-limit`, `no-response`, `unusable` or
   `crash` (no restart needed) and `/run` again → `BEAR-N01`, `N02`, `N03`, `R01`.

---

## 5. Go live

1. `nano /opt/bear/.env`, put `#` in front of `BEAR_SIM=ok`, save, `systemctl restart bear-bot`.
   The "BEAR is up" card no longer mentions dev mode, and the cards lose the DEV MODE footer.
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
| Update to the latest `discord-bear` | `/status` in Discord first (updating restarts the bot), then `bash /opt/bear/discordbot/deploy/setup.sh`. With §7 set up the error channel says 🔴 down, then 🟢 up; a failed update says which step failed. |
| Change a setting | `nano /opt/bear/.env`. `BEAR_RUN_CAP_USD`, `BEAR_NAME_MODEL`, `BEAR_SIM`, `BEAR_RENAME_OFFER`, `BEAR_RENAME_WAIT` apply to the next `/run`; anything else needs a restart. |
| Bring back `/run`'s rename offer (off since 2026-10-25) | In `.env`: `BEAR_RENAME_OFFER=1`. No restart. `/rename` works either way. |
| Give people longer to type a SKU | In `.env`: `BEAR_RENAME_WAIT=120` (seconds; default 60; only with the offer on). No restart. |
| What was renamed | `cat /var/lib/bear/runs/renames/renames.log` (one line per rename: when, channel, folder, SKU, what happened, photos, zips) |
| Shadow test results | `/opt/bear/.venv/bin/python /opt/bear/discordbot/shadow_report.py /var/lib/bear/runs/shadow/shadow.jsonl`. Add `--review /tmp/review.csv` for a sheet of 💸 photos to fill in the right location, then `--truth /tmp/review.csv` to score the models. |
| Turn the shadow test off | In `.env`: `BEAR_SHADOW=0`. No restart. `BEAR_SHADOW_PING_PARTS=300` sets how often it reminds you; `BEAR_SHADOW_PING_USER=<your user ID>` @mentions you. |
| Swap the name model (Qwen keeps failing, `BEAR-N01`–`N03`) | In `.env`: `BEAR_NAME_MODEL=google/gemini-3.1-flash-lite` (or `anthropic/claude-haiku-5.5`) |
| Disk space | `df -h /var/lib/bear/runs` and `du -sh /var/lib/bear/runs/*` |
| Delete runs older than 60 days | `find /var/lib/bear/runs -mindepth 2 -maxdepth 2 -type d -mtime +60 -exec rm -rf {} +` |

**Where things are:** each run is in
`/var/lib/bear/runs/<channel>-<id>/<folder>-<date-time>/`: `photos/` (every photo in the folder,
each one a part, `001.jpg`, … in upload order), `photos.tsv` (which Discord message each photo
came from, so a spreadsheet row can be traced back), `results/` (`results.xlsx`, `agent2_results.md`, `trace.json`, …), `bear.log` and
`spend.jsonl` (what that folder cost).

Renames are in `/var/lib/bear/runs/renames/<channel>-<id>/<SKU>-<date-time>/`, on the same disk
as the runs (the SSD). Once the zips are posted the photos and zips are deleted; `renamed.tsv`
stays (new name, Discord name, message link), and so does the line in `renames/renames.log`.
A photo too big for Discord stays in `photos/` so it can be handed over by hand.

The shadow test logs to `/var/lib/bear/runs/shadow/shadow.jsonl` (one line per photo per model,
with a link to its message) and counts its reminders in `shadow/pinged`. It runs only when live
(never in dev mode), after the spreadsheet is posted, and nothing it does can fail a `/run`.

| Problem | Fix |
|---|---|
| Status says `inactive` / `status=78` | A setting in `.env` is not filled in or wrong; the last log line says which. Fix it, then `systemctl restart bear-bot` (it won't retry by itself). |
| `/run` says "The application did not respond" | The bot is down or the VM has no internet: `systemctl status bear-bot`, then the log. |
| `/newfolder` and `/run` don't appear | Wrong `DISCORD_GUILD_ID`, or the bot was invited without `applications.commands`: re-open the invite link (§2.4). Then restart. |
| Log says `PrivilegedIntentsRequired` | Turn on Message Content Intent (§2.2), restart. |
| Log says `Improper token` / `LoginFailure` | Token wrong or reset: paste the new one in `.env`, restart. |
| Text messages aren't deleted | `CARS_CATEGORY_ID` missing/wrong, the channel isn't in Cars, or the bot lacks Manage Messages. |
| Nothing arrives in the error channel | Wrong `ERROR_CHANNEL_ID`, or the bot can't see/post there (channel permissions). |
| Setup stops at "flow test failed" | The last lines show why; the full output is in `/var/lib/bear/flow-test.log`. |

Error codes in the error channel (fixes are in each message):
`D01` no topic · `D02` no folder · `D03` no photos · `D05` photo BEAR can't
read (HEIC) · `D06` download failed · `D07` renaming failed (a photo or zip) · `N01`/`N02`/`N03` name model rate limited / not responding /
unusable names · `K01` OpenRouter out of credit · `K02` BEAR's per-folder cap · `T01` run took over
2 hours · `R01` anything else (log attached).

---

## 7. Is BEAR up? (down/up messages in the error channel)

A VM that is down can't say so itself, so a free outside monitor (healthchecks.io) watches it.
The bot checks in every 10 minutes. If a check-in is missed, healthchecks posts 🔴 **down** in
the error channel, and 🟢 **up** once check-ins start again. Updates use it too: `setup.sh` says
down just before it restarts the bot, and the bot's first check-in says up. Nothing is posted
while all is well. (`discordbot/heartbeat.py`)

One-time setup, about 5 minutes:

1. Sign up at https://healthchecks.io (free).
2. **Add Check.** Name: `BEAR`. Period: **10 minutes**. Grace: **5 minutes** (so "down" means no
   check-in for 15 minutes; a slow minute never sets it off).
3. **Integrations > Add Integration > Discord.** Discord asks for a server and channel: pick
   your server and the error channel (`#bear-errors`), then Authorize.
4. Open the `BEAR` check. Under **Notification Methods** turn Discord **on** and Email **off**,
   so every down/up message goes to the error channel and nowhere else.
5. Copy the check's ping URL (`https://hc-ping.com/...`) and on the VM:

   ```
   nano /opt/bear/.env          # add:  BEAR_HEARTBEAT_URL=https://hc-ping.com/...
   systemctl restart bear-bot
   ```

   Within a minute the check turns green on healthchecks.io.
6. Try it: `python3 /opt/bear/discordbot/heartbeat.py down` posts 🔴 down in the error channel,
   then `systemctl restart bear-bot` posts 🟢 up.

| What you see in the error channel | Meaning |
|---|---|
| 🔴 BEAR is down, right after you ran `setup.sh` | The update is restarting the bot. 🟢 up follows within a minute. |
| 🔴 BEAR is down, out of the blue | No check-in for 15 minutes: the VM, its internet or the bot stopped. `systemctl status bear-bot` on the VM, or check the VM in Proxmox. |
| 🟢 BEAR is up | Check-ins started again. |
| 🔴 Update failed at: *step* | `setup.sh` stopped part way. The bot wasn't restarted and still runs the version from before. The full output is in the terminal that ran it. |

To turn it off, delete the `BEAR_HEARTBEAT_URL` line and restart the bot (pause the check on
healthchecks.io, or it will say down).

---

## 8. Update log (#update-log)

The first time the bot starts on new code (after `setup.sh`), it posts **🐻 BEAR updated to
0.4.13** in `#update-log` with the pull requests that came in, each linked to GitHub. A restart
with no new code posts nothing there.

The version is automatic: the number in `VERSION` plus how many changes were merged since it was
last changed (0.4.13 = the 13th merge after 0.4). Bump `VERSION` to 0.5 and it starts again at 0.5.0.
The **🟢 BEAR is up** card in the error channel shows the same number.

The channel: run `/opt/bear/.venv/bin/python /opt/bear/discordbot/setup_server.py --write-env`
once (it adds `#update-log` next to `#bear-errors`, read-only, and writes `UPDATE_CHANNEL_ID`),
or make a text channel called exactly `update-log` by hand. With neither, nothing is posted and
the changes wait for the next start that has somewhere to post them.

