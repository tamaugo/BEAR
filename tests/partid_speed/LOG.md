# #part-id speed test, 2026-10-30

## Result
Same photo (412 KB, from #part-id), 3 runs per gate, sent from the Mac and timed until the bot's reply arrived back on the Mac.

| Gate | Cap | Avg end to end | Photo upload | Server side (VM + OpenRouter + Discord) |
|---|---|---|---|---|
| Really slow | 256 Kbps | 33 079 ms | 30 108 ms | 2 818 ms |
| Slow | 1 Mbps | 8 117 ms | 5 521 ms | 2 462 ms |
| Medium | 10 Mbps | 4 130 ms | 1 381 ms | 2 635 ms |
| Fast | 50 Mbps | 3 872 ms | 842 ms | 2 934 ms |
| Baseline | none (108/56 Mbps) | 4 051 ms | 967 ms | 2 939 ms |

Full data: `partid_speed_2026-10-30.json`.

## What I did, and why
| Did | Why |
|---|---|
| Measured baseline with `networkQuality` | Reference speed |
| Made `/tmp` venv with discord.py 2.7.1 (deleted after) | Mac listens on the Discord gateway for the reply, like the app |
| You made a webhook in #part-id (deleted after) | Something to post the photo; the bot has no Manage Webhooks permission |
| Added `/etc/sudoers.d/bear-speedtest` (your password, deleted after) | Turn the throttle on/off without a prompt each gate |
| Throttled the Mac with `dnctl` + `pf` anchor `com.apple/bear-speedtest`, bandwidth only, IPv4 + IPv6, LAN excluded (removed after) | The gates; no added latency as asked |
| Temporary patch on the VM, bot restarted twice (~5 s down each) | Let the bot accept the test webhook and log each step in ms |
| Measured Mac/VM clock difference: 1.4 ms | So VM and Mac times line up |
| Pulled OpenRouter's own stats per call | Splits OpenRouter time into Gemini's work vs network/queue |
| Reverted VM to `discord-bear` 2a3eda8, deleted 15 test posts, 15 bot replies, their photos/cards | Leave #part-id and the server as they were |

## What this means
- At 10 Mbps upload or more, the connection is no longer the bottleneck: ~4 s every time. 50 Mbps and baseline are no faster than 10 Mbps.
- Below that, only the photo upload grows (30 s at 256 Kbps). The reply coming back is ~100–150 ms at every speed.
- The fixed ~2.8 s on the server: OpenRouter ~1.6 s (Agent 1 ~1.35 s, of which Gemini ~1.05 s; Jev ~0.26 s), our code ~0.5 s (mostly the VM downloading the photo from Discord), Discord delivery + reply ~0.8 s.
- To make slow connections faster: send a smaller photo (resize on the phone or in the app before upload). The server already resizes to 1600 px, so a smaller upload costs no accuracy as long as it stays ≥1600 px.

## Notes
- `networkQuality` upload readings under a cap are wrong (dummynet artifact). Use the curl upload speed in the JSON.
- The `split_ms` parts overlap by ~100–300 ms, because Discord's time is counted in both the reply post and the reply delivery.
- The first run of a gate is often slower (fresh connection).
- Scripts: `run_speed.py` (Mac side), `build_json.py` (joins the data). They're not in a PR; your call.
