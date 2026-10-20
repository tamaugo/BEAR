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
| C7: live photo on the VM | Pending: browser lost its login while opening the source photo; no live run started |
| C9: private unrun-folder warning | PASS: human `/newfolder C9OLD`, one photo with 💸, then `/newfolder C4A` produced a new public marker and a warning marked "Only you can see this" |
| Phone photo-quality comparison | Not attempted; requires phone uploads and matching source photos |

No feature branch was deployed. The temporary C4 simulation delay was removed.
Live mode was briefly enabled to prepare C7, then simulation mode was restored when
Discord required login again. The bot is active in simulation mode; no live run started.
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

## Next steps

1. Restore Discord login and finish C7 with one real photo. The existing Q184
   `IMG_6448.JPEG` has a visibly readable `BM51-17504-BH` label and a previous Mac
   result of £19.99; its downloaded bytes have SHA-256
   `f64aecfbacfefa4f6b308006528f35fb7826142f036ebf55d633bb9218ea08ff`.
2. Complete the phone photo-quality comparison before real use. The owner has been
   asked whether the Q184 photos were phone uploads and where their originals are.
3. Owner merges the PRs when satisfied, then update the VM from `discord-bear` and
   verify the resulting deployment.
