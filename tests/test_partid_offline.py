#!/usr/bin/env python3
"""Offline checks of #part-id (no Discord, no network, no credits). Needs discord.py (the server's
.venv has it). A photo posted in #part-id goes through the real bot and the real partid/agent1.py in
dev mode, and the raw read comes back as a reply; other channels, text, HEIC and failures too.

usage: .venv/bin/python tests/test_partid_offline.py
"""
import asyncio, json, logging, os, sys, tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="bear-partid-test-"))
os.environ.update({"DISCORD_GUILD_ID": "1", "ERROR_CHANNEL_ID": "99", "BEAR_STORAGE": str(TMP), "BEAR_SIM": "ok"})
for k in ("CARS_CATEGORY_ID", "PART_ID_CHANNEL_ID"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT / "tools"))
import jev_client  # noqa: E402
jev_client.ENV_FILE = TMP / "no.env"
sys.path.insert(0, str(ROOT / "discordbot"))
import bot as B  # noqa: E402
import partid_bot as P  # noqa: E402
from PIL import Image  # noqa: E402

logging.disable(logging.CRITICAL)
fails = []


def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")


class Att:
    def __init__(self, filename):
        self.filename, self.content_type = filename, None

    async def save(self, path):
        Image.new("RGB", (64, 48), "white").save(path, "JPEG")


def message(channel, files=(), mid=500):
    replies = []

    async def reply(content=None, file=None, mention_author=True):
        replies.append((content, file.filename if file else None))
    return NS(id=mid, author=NS(bot=False), guild=NS(id=1), channel=channel, type=None,
              attachments=[Att(f) for f in files], reply=reply), replies


async def main():
    part_id, car = NS(id=5, name="part-id", category_id=None), NS(id=6, name="car-x", category_id=None)

    # A photo in #part-id: one reply with the model's raw text, the read kept on disk.
    m, replies = message(part_id, ["IMG_1.jpg"])
    await B.bot.on_message(m)
    check("one reply", len(replies), 1)
    text = replies[0][0] if replies else ""
    check("header", text.split("\n")[0].startswith("**Agent 1** · `IMG_1.jpg` · google/gemini-3.1-flash-lite"), True)
    check("raw read in a code block", "```json\n" + P.AGENT1.read_text().split("SIM_RAW = '")[1].split("'\n")[0] + "\n```" in text, True)
    kept = json.loads((TMP / "part-id" / "500-1.json").read_text())
    check("kept on disk", sorted(kept), ["cost", "model", "raw", "seconds"])

    # Two photos and a HEIC in one message: a reply each, and HEIC is refused.
    m, replies = message(part_id, ["a.jpg", "b.png", "c.heic", "notes.pdf"], 501)
    await B.bot.on_message(m)
    check("two reads + HEIC note", len(replies), 3)
    check("HEIC refused", any("Can't read c.heic" in (r[0] or "") for r in replies), True)

    # Other channels and text-only messages are not read.
    m, replies = message(car, ["x.jpg"], 502)
    await B.bot.on_message(m)
    check("other channel ignored", replies, [])
    m, replies = message(part_id, [], 503)
    await B.bot.on_message(m)
    check("text ignored", replies, [])

    # PART_ID_CHANNEL_ID wins over the name.
    check("by id", P.is_partid(car, 6), True)
    check("by id, name not enough", P.is_partid(part_id, 6), False)

    # A failed read says so in a reply.
    real, P.AGENT1 = P.AGENT1, TMP / "missing.py"
    m, replies = message(part_id, ["y.jpg"], 504)
    await B.bot.on_message(m)
    check("failure replied", "failed" in (replies[0][0] if replies else ""), True)
    P.AGENT1 = real

    # Too long for one message: posted as a file.
    check("too long", P.reply_text("z.jpg", {"model": "m", "seconds": 1, "cost": 0, "raw": "x" * 2100}), None)
    check("``` can't end the block early", "'''" in P.reply_text("z.jpg", {"model": "m", "seconds": 1, "cost": 0,
                                                                           "raw": "a```b"}), True)

asyncio.run(main())
if fails:
    print("FAIL\n  " + "\n  ".join(fails))
    sys.exit(1)
print("part-id offline checks: all passed")
