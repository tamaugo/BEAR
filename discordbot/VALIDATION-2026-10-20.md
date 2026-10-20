# Discord handoff validation — 20 October 2026

The owner will merge the open PRs after the work is finished. Discord changes target
`discord-bear`; the Mac edition on `main` is unchanged.

## Code checks

- The look test uses `folders.ERRORS` and the actual folder marker helpers, so backend
  error codes and marker changes cannot silently drift from the frontend.
- Deployment now runs the look test before restarting the bot, alongside the existing
  names, folder rules and flow tests.
- The unrun-folder warning explains that `/run` uses the new folder and that earlier
  photos must be uploaded again below its marker, as approved by the owner.
- All four offline suites pass using the existing frontend Python environment and
  the VM's installed environment against PR commit `0050002` in a separate SSD
  checkout (`/mnt/bear-ssd/validation/pr29`). The running bot was not changed.
- Mutation checks confirm the look test rejects a new backend error without wording,
  a missing title, missing uploader text and marker drift.
- `bash -n discordbot/deploy/setup.sh` and `git diff --check` pass.

## VM checks

Before reboot, the VM was running `discord-bear` at `78be6cb` in simulation mode.
Only the VM bot was running; no BEAR run subprocess was active. All four offline
suites passed on the VM. Code, run storage and the journal were mounted from the
Kingston SSD. The settings file was owned by `bear`, mode 600, with required settings
present. No secrets were printed or changed.

After reboot the VM's DHCP address changed from `192.168.1.206` to `192.168.1.209`.
SSH works at the new address. The boot ID changed, all three SSD bind mounts are
correct, and the bot returned automatically after one initial DNS failure. Its new
online card is message `1562165276449972316` in `#bear-errors`, at 18:07:05 UTC.
Discord login in the shared preview is also restored.

| Check | Result this session |
|---|---|
| C4: two running, one queued | PASS: two VM processes, third card queued, private `/status` listed all three; all finished on their original cards with spreadsheets |
| C6: automatic return after VM reboot | PASS: new boot ID, bot active, SSD mounts correct and new Discord online card |
| C7: live photo on the VM | PASS: owner's live `PHONETEST` run finished green with two real part numbers/prices and a spreadsheet |
| C9: private unrun-folder warning | PASS: human `/newfolder C9OLD`, one photo with 💸, then `/newfolder C4A` produced a new public marker and a warning marked "Only you can see this" |
| Phone photo-quality comparison | PASS for this three-photo sample: same resolution, part numbers, prices and unreadable-photo outcome as the original Mac run |

No feature branch was deployed. The temporary C4 simulation delay was removed.
The bot is active in live mode after the owner's phone run. `BEAR_SIM` is commented
out; the per-folder spend cap is unchanged. No Mac bot was started.
The C9 screenshot checks the existing warning behavior; this PR's corrected wording
is verified offline and awaits deployment. C9's photo message is
`1562167872841846987` in `#test-ford-focus`.

C4 evidence: from 18:19:18 through 18:19:49 UTC, two simulation processes ran for
`C4A` and `C4B` while `C4C` was queued. After those completed, C4C ran alone. Each
folder has one downloaded photo and a 3,346-byte spreadsheet on the SSD:

- `test-ford-focus-1562152643160444958/C4A-20261020-141914`
- `test-c4-b-1562162274528002210/C4B-20261020-141915`
- `test-c4-c-1562162276222373932/C4C-20261020-141918`

Run-card message IDs are `1562168329546899530`, `1562168333208518808` and
`1562168345598361723`. The private status message was `1562168353802555395`.

## Live phone comparison

The owner uploaded the same three Q184 source photos through the phone app into
`PHONETEST` in `#test-ford-focus`. The green result card is
[`1562175337339555911`](https://discord.com/channels/1559923225746739334/1562152643160444958/1562175337339555911),
with `PHONETEST-ford-focus-mk3.xlsx` attached and no DEV footer. The run is stored at
`/var/lib/bear/runs/test-ford-focus-1562152643160444958/PHONETEST-20261020-144721`.
Its recorded model cost is **$0.00344775** and the spreadsheet is 3,386 bytes.

The actual originals are in `~/Desktop/temp/Q184 FFOCUSMK3-3 09-10`. They match the
source files beside the original Mac results by SHA-256. The comparison uses that
original Mac run's `agent2_results.md` in
`~/Documents/BEAR/Q184 FFOCUSMK3-3 09-10-20261013-220645/bear-results-20261013-220648`.

| Original photo | Original Mac result | Live phone result | Original / phone bytes |
|---|---|---|---|
| IMG_6448 | BM51-17504-BH, £19.99 | BM51-17504-BH, £19.99 | 737,597 / 244,090 |
| IMG_6457 | 3M51-6F012-BH, £19.99 | 3M51-6F012-BH, £19.99 | 857,833 / 306,921 |
| IMG_6467 | No clear part number (Agent 1) | No clear part number (Agent 1) | 1,332,032 / 463,753 |

All originals and phone copies are **1536 × 2048 pixels**. The phone copies were
recompressed, but this sample shows no loss of the Mac run's successful results.
Phone upload order differs: `001.jpg` is IMG_6457, `002.jpg` is IMG_6448 and `003.jpg`
is IMG_6467; the run's `photos.tsv` preserves this mapping.

## Next steps

1. Owner reviews and merges PRs #27, #28 and #29 into `discord-bear`.
2. Check that no folders are active, update the VM from `discord-bear`, then verify
   the offline suites, service, SSD mounts and online card.

Frontend review found no code blockers. A router DHCP reservation would prevent
the VM's address changing on a future reboot; no router changes were made.
