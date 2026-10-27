#!/usr/bin/env python3
"""Is BEAR up? An outside monitor (healthchecks.io) answers that, because a VM that is down can't
say so itself. The bot checks in with it every 10 minutes (BEAR_HEARTBEAT_URL in .env); when a
check-in is missed the monitor posts "down" in the error channel, and "up" once they start again.
setup.sh uses the same monitor for updates: "down" just before it restarts the bot, and the bot's
first check-in afterwards turns it back to "up". Nothing is posted while all is well.

An update that stops part way posts to the error channel straight from here (with the bot token),
because the bot keeps running the version from before and the monitor has nothing to report.
When the bot first starts on new code it lists what changed (the pull requests merged since the
last one posted) in #update-log: the channel UPDATE_CHANNEL_ID, or else the channel named update-log.

usage (setup.sh runs the first two, the bot does the update log; nothing happens when a setting is missing):
  python3 discordbot/heartbeat.py down                   the monitor says BEAR is down for an update
  python3 discordbot/heartbeat.py failed "<step>"        the error channel hears the update failed
  python3 discordbot/heartbeat.py update-log <file>      #update-log hears what changed; <file>
                                                         remembers the last commit posted
"""
import json, os, re, subprocess, sys, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import jev_client  # noqa: E402  (the .env reader BEAR itself uses; stdlib only, so no venv needed)
import look  # noqa: E402  (no discord.py needed for the post itself)

UPDATE_CH = "update-log"
MAX_CHANGES = 15   # newest first; older ones become "... and N older changes"
API = "https://discord.com/api/v10"
EVERY = 600     # seconds between check-ins; set the monitor's period to 10 minutes to match
AGENT = "DiscordBot (https://github.com/tamaugo/BEAR, 1) BEAR-heartbeat"


def setting(name):
    """From the environment, then .env (the same reader as the bot); blank or PASTE_HERE is None."""
    v = (os.environ.get(name) or jev_client._parse_dotenv(jev_client.ENV_FILE).get(name) or "").strip()
    return v if v and v != "PASTE_HERE" else None


def ping_url(base, kind=""):
    """healthchecks.io: the plain URL means "up", <url>/fail means "down"."""
    return base.rstrip("/") + (f"/{kind}" if kind else "")


def _send(req, timeout=10, answer=False):
    """True when it worked (or the JSON answer, with answer=True); False/None on any problem."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r) if answer else 200 <= r.status < 300
    except Exception as e:   # never let a monitor problem break the bot or an update
        print(f"heartbeat: {e}", file=sys.stderr)
        return None if answer else False


def _discord(path, body=None, token=None):
    token = token or setting("DISCORD_TOKEN")
    headers = {"Authorization": f"Bot {token}", "User-Agent": AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
        return _send(urllib.request.Request(API + path, data=json.dumps(body).encode(), headers=headers))
    return _send(urllib.request.Request(API + path, headers=headers), answer=True)


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
    return _discord(f"/channels/{channel}/messages", {"content": text, "allowed_mentions": {"parse": []}}, token)


def update_channel():
    """UPDATE_CHANNEL_ID, or the server's text channel named update-log; None if there's neither."""
    channel = setting("UPDATE_CHANNEL_ID")
    if channel and channel.isdigit():
        return channel
    guild = setting("DISCORD_GUILD_ID")
    if not (setting("DISCORD_TOKEN") and guild and guild.isdigit()):
        return None
    found = [c["id"] for c in _discord(f"/guilds/{guild}/channels") or [] if c.get("type") == 0 and c.get("name") == UPDATE_CH]
    return found[0] if found else None


def git(*args):
    # setup.sh runs this as root on the bear user's checkout: safe.directory lets git read it
    return subprocess.run(["git", "-c", f"safe.directory={REPO}", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=True).stdout


MERGE = re.compile(r"Merge pull request #(\d+) ")


def changes(last, head):
    """[(pull request number or None, title)] newest first, from the commits after last up to head
    on the branch itself (a pull request counts once, under its own title). With no last commit
    (the first update log), just head's own change."""
    span = [f"{last}..{head}"] if last else [head, "-1"]
    out = []
    for entry in git("log", "--first-parent", "--format=%s%x1f%b%x1e", *span).split("\x1e"):
        subject, _, body = entry.strip("\n").partition("\x1f")
        if not subject:
            continue
        m = MERGE.match(subject)
        title = (body.strip().splitlines() or [subject])[0] if m else subject
        out.append((int(m.group(1)) if m else None, title))
    return out


def version():
    """VERSION's major.minor, then how many changes were merged since VERSION last changed: 0.4.12
    is the 12th merge after 0.4. Automatic; bumping VERSION to 0.5 starts again at 0.5.0."""
    try:
        base = (REPO / "VERSION").read_text().strip()
    except OSError:
        return None
    try:
        since = git("log", "--first-parent", "-1", "--format=%H", "--", "VERSION").strip()
        n = int(git("rev-list", "--count", "--first-parent", f"{since}..HEAD")) if since else 0
    except (OSError, ValueError, subprocess.CalledProcessError):
        return base   # no git: the number in the file
    return ".".join(base.split(".")[:2] + [str(n)])


def update_log(state):
    """Post what changed since the commit in the state file, then remember head. Nothing new, or
    nowhere to post: nothing is posted (and what wasn't posted is kept for next time)."""
    state = Path(state)
    try:
        head = git("rev-parse", "HEAD").strip()
        last = state.read_text().strip() if state.exists() else None
        if last == head:
            return False
        if last and subprocess.run(["git", "-c", f"safe.directory={REPO}", "-C", str(REPO), "merge-base",
                                    "--is-ancestor", last, head], capture_output=True).returncode:
            last = None   # history was rewritten: just say what is running now
        found = changes(last, head)
    except (OSError, subprocess.CalledProcessError) as e:   # never stop the bot over the update log
        print(f"update log: {e}", file=sys.stderr)
        return False
    channel = update_channel()
    if not channel:
        return False
    post = look.update_log(found[:MAX_CHANGES], version(), max(0, len(found) - MAX_CHANGES))
    ok = _discord(f"/channels/{channel}/messages", {**post, "allowed_mentions": {"parse": []}})
    if ok:
        try:
            state.write_text(head + "\n")
        except OSError as e:
            print(f"update log: {e}", file=sys.stderr)
    return ok


def main(argv):
    if argv[:1] == ["down"]:
        ping("fail")
    elif argv[:1] == ["failed"]:
        post_error(update_failed_text(" ".join(argv[1:]) or "an unknown step"))
    elif argv[:1] == ["update-log"] and len(argv) == 2:
        update_log(argv[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
