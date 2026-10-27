#!/usr/bin/env python3
"""Is BEAR up? An outside monitor (healthchecks.io) answers that, because a VM that is down can't
say so itself. The bot checks in with it every 10 minutes (BEAR_HEARTBEAT_URL in .env); when a
check-in is missed the monitor posts "down" in the error channel, and "up" once they start again.
setup.sh uses the same monitor for updates: "down" just before it restarts the bot, and the bot's
first check-in afterwards turns it back to "up". Nothing is posted while all is well.

An update that stops part way posts to the error channel straight from here (with the bot token),
because the bot keeps running the version from before and the monitor has nothing to report.

usage (setup.sh runs these; both do nothing when the setting they need is missing):
  python3 discordbot/heartbeat.py down                   the monitor says BEAR is down for an update
  python3 discordbot/heartbeat.py failed "<step>"        the error channel hears the update failed
"""
import json, os, sys, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import jev_client  # noqa: E402  (the .env reader BEAR itself uses; stdlib only, so no venv needed)

EVERY = 600     # seconds between check-ins; set the monitor's period to 10 minutes to match
AGENT = "DiscordBot (https://github.com/tamaugo/BEAR, 1) BEAR-heartbeat"


def setting(name):
    """From the environment, then .env (the same reader as the bot); blank or PASTE_HERE is None."""
    v = (os.environ.get(name) or jev_client._parse_dotenv(jev_client.ENV_FILE).get(name) or "").strip()
    return v if v and v != "PASTE_HERE" else None


def ping_url(base, kind=""):
    """healthchecks.io: the plain URL means "up", <url>/fail means "down"."""
    return base.rstrip("/") + (f"/{kind}" if kind else "")


def _send(req, timeout=10):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception as e:   # never let a monitor problem break the bot or an update
        print(f"heartbeat: {e}", file=sys.stderr)
        return False


def ping(kind=""):
    """Check in with the monitor (kind "" = up, "fail" = down). False when off or it didn't answer."""
    base = setting("BEAR_HEARTBEAT_URL")
    if not base:
        return False
    return _send(urllib.request.Request(ping_url(base, kind), headers={"User-Agent": AGENT}))


def update_failed_text(step):
    return (f"\N{LARGE RED CIRCLE} **Update failed** at: {step}\n"
            "BEAR was not restarted: it is still running the version from before. "
            "The full output is on the VM, in the terminal that ran setup.sh.")


def post_error(text):
    """Post plain text to the error channel with the bot token (the bot itself may not be running)."""
    token, channel = setting("DISCORD_TOKEN"), setting("ERROR_CHANNEL_ID")
    if not (token and channel and channel.isdigit()):
        return False
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel}/messages",
        data=json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode(),
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json", "User-Agent": AGENT})
    return _send(req)


def main(argv):
    if argv[:1] == ["down"]:
        ping("fail")
    elif argv[:1] == ["failed"]:
        post_error(update_failed_text(" ".join(argv[1:]) or "an unknown step"))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
