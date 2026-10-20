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
- All four offline suites pass using the existing frontend Python environment.
- Mutation checks confirm the look test rejects a new backend error without wording,
  a missing title, missing uploader text and marker drift.
- `bash -n discordbot/deploy/setup.sh` and `git diff --check` pass.

## VM checks

Before reboot, the VM was running `discord-bear` at `78be6cb` in simulation mode.
Only the VM bot was running; no BEAR run subprocess was active. All four offline
suites passed on the VM. Code, run storage and the journal were mounted from the
Kingston SSD. The settings file was owned by `bear`, mode 600, with required settings
present. No secrets were printed or changed.

| Check | Result this session |
|---|---|
| C4: two running, one queued | Pending Discord login and VM availability |
| C6: automatic return after VM reboot | Unresolved: reboot was issued, but SSH and ping did not return; owner asked to inspect VM 108's Proxmox console |
| C7: live photo on the VM | Not attempted |
| C9: private unrun-folder warning | Pending Discord login and VM availability |
| Phone photo-quality comparison | Not attempted; requires phone uploads and matching source photos |

No feature branch was deployed. The live-mode switch and temporary C4 simulation
delay have not been applied. Do not treat the reboot or live checks as passed.

## Next steps

1. Diagnose the VM console state and restore access; verify the SSD mounts and bot.
2. Log back into Discord in the shared preview.
3. Run C4 in the existing test channels, temporarily using `BEAR_SIM_PAUSE=4.5`, and
   remove that setting afterwards.
4. Run C9 with a human-uploaded, flagged photo between the two folder markers.
5. Complete the live run and phone photo-quality comparison before real use.
6. Owner merges the PRs when satisfied, then update the VM from `discord-bear` and
   verify the resulting deployment.
