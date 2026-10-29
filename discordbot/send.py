#!/usr/bin/env python3
"""bear-send: say something in a Discord channel from the VM's terminal, as the BEAR bot.

  bear-send: my message here @example-channel

The last word, starting with @ (or #), is the channel's name; everything before it is the message.
It posts plain text (nobody gets @mentioned) with the bot token from .env, so the bot itself
doesn't need to be running. setup.sh installs it as the commands `bear-send` and `bear-send:`
(deploy/bear-send). Quote the message if it has ' " ! ( ) ; & < > in it: the shell reads those first.

usage: python3 discordbot/send.py <message words...> @channel
"""
import re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import heartbeat as hb  # noqa: E402  (the .env reader and Discord calls the update log uses)

MAX = 2000   # Discord's longest message
USAGE = "usage: bear-send: my message here @channel-name"
CHANNEL = re.compile(r"[@#]([^\s@#]+)")


def parse(words):
    """(message, channel name) from the words typed after bear-send:. Either is None if missing."""
    words = " ".join(words).split()
    m = CHANNEL.fullmatch(words[-1]) if words else None
    if not m:
        return (" ".join(words) or None), None
    return (" ".join(words[:-1]) or None), m.group(1).lower()


def text_channels():
    """{name: id} of the server's text channels, or None when Discord can't be reached."""
    guild = hb.setting("DISCORD_GUILD_ID")
    if not (hb.setting("DISCORD_TOKEN") and guild and guild.isdigit()):
        return None
    found = hb._discord(f"/guilds/{guild}/channels")
    return None if found is None else {c["name"]: c["id"] for c in found if c.get("type") == 0}


def send(words):
    """Post the message. Returns the line to print and whether it worked."""
    message, name = parse(words)
    if not (message and name):
        return USAGE, False
    if len(message) > MAX:
        return f"Too long: {len(message)} characters, Discord's limit is {MAX}.", False
    channels = text_channels()
    if channels is None:
        return "Can't reach Discord: check DISCORD_TOKEN and DISCORD_GUILD_ID in /opt/bear/.env.", False
    if name not in channels:
        return f"No channel called {name}. The channels are: " + ", ".join(sorted(channels)), False
    if not hb._discord(f"/channels/{channels[name]}/messages",
                       {"content": message, "allowed_mentions": {"parse": []}}):
        return f"Discord wouldn't take it for #{name} (can the bot post there?).", False
    return f"Sent to #{name}.", True


if __name__ == "__main__":
    line, ok = send(sys.argv[1:])
    print(line, file=sys.stdout if ok else sys.stderr)
    sys.exit(0 if ok else 1)
