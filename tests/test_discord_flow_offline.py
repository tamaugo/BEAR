#!/usr/bin/env python3
"""Offline end-to-end checks of the Discord bot (no Discord, no network, no credits). Needs
discord.py (the server's .venv has it).

Plays /run through the real bot code against a fake car channel, with BEAR's dev mode
(bear2/simulate.py) as the run: the spreadsheet posted for a good folder, every BEAR-D error a
person can cause, the name model failures (N01-N03) and a crash (R01) landing in the error
channel, and three folders at once with two slots (one waits in the queue).

usage: .venv/bin/python tests/test_discord_flow_offline.py
"""
import asyncio, logging, os, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="bear-discord-test-"))
os.environ.update({"DISCORD_GUILD_ID": "1", "ERROR_CHANNEL_ID": "99", "BEAR_STORAGE": str(TMP),
                   "BEAR_UPLOAD_WAIT": "1", "BEAR_MAX_RUNS": "2", "BEAR_SIM_PAUSE": "0.02"})
os.environ.pop("CARS_CATEGORY_ID", None)
sys.path.insert(0, str(ROOT / "discordbot"))
import bot as B  # noqa: E402
import folders as fo  # noqa: E402
from PIL import Image  # noqa: E402

ME, PERSON = NS(id=7, bot=True), NS(id=8, bot=False)
CAR = "MITSUBISHI SHOGUN 2007 3.2 DI-D"
B.bot._connection.user = ME
logging.disable(logging.CRITICAL)   # the bot logs every error it posts; the checks below cover them
B.car_channel_problem = lambda ch: None


class Att:
    def __init__(self, filename):
        self.filename = filename

    async def save(self, path):
        Image.new("RGB", (64, 48), "white").save(path, "JPEG" if Path(path).suffix != ".webp" else "WEBP")


class Channel:
    def __init__(self, cid, topic=CAR):
        self.id, self.name, self.topic, self.mention = cid, f"car-{cid}", topic, f"<#{cid}>"
        self.msgs, self.sent = [], []

    def add(self, author=PERSON, content="", files=(), money=False, ago=300):
        self.msgs.append(NS(author=author, content=content, attachments=[Att(f) for f in files],
                            reactions=[NS(emoji=fo.MONEY)] if money else [],
                            created_at=datetime.now(timezone.utc) - timedelta(seconds=ago),
                            jump_url=f"https://discord.com/channels/1/{self.id}/{len(self.msgs)}"))

    async def history(self, limit=100):
        for m in self.msgs[::-1][:limit]:
            yield m

    async def send(self, text, file=None, files=None):
        self.sent.append((text, file.filename if file else None))
        self.add(ME, text, ago=0)


ERRORS = Channel(99)


async def error_channel():
    return ERRORS
B.bot.error_channel = error_channel


class Inter:
    def __init__(self, ch):
        self.channel, self.replies = ch, []
        self.response = NS(send_message=self.reply, is_done=lambda: True)

    async def reply(self, text, ephemeral=False):
        self.replies.append(text)
        if not ephemeral:
            self.channel.add(ME, text, ago=0)


def folder(cid, name="Q184", flags=2, topic=CAR, extra=()):
    ch = Channel(cid, topic)
    ch.add(ME, fo.marker(name))
    ch.add(files=["IMG_1.jpg", "IMG_2.jpg"])
    for i in range(flags):
        ch.add(files=[f"IMG_{10 + i}.{'webp' if i % 2 else 'jpg'}"], money=True)
    for kw in extra:
        ch.add(**kw)
    return ch


async def run(ch, sim="ok"):
    os.environ["BEAR_SIM"] = sim
    await B.run.callback(Inter(ch))
    return ch


fails = []


def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")


def last_error():
    return ERRORS.sent[-1][0] if ERRORS.sent else ""


async def main():
    # A good folder: photos downloaded as 001.jpg, 002.webp; the simulated spreadsheet posted.
    ch = await run(folder(10))
    text, fname = ch.sent[-1]
    check("spreadsheet posted", fname, "Q184-mitsubishi-shogun-2007.xlsx")
    check("listings counted", "found 6 listings for 7 parts" in text, True)
    check("running message", any("Running 2 parts" in t for t, _ in ch.sent), True)
    run_dir = next((TMP / "car-10-10").iterdir())
    check("photo names", sorted(p.name for p in (run_dir / "photos").iterdir()), ["001.jpg", "002.webp"])
    check("own spend ledger used", (run_dir / "results" / "results.xlsx").exists(), True)
    check("no error posted", ERRORS.sent, [])

    # Problems a person can cause.
    cases = [
        ("no folder", Channel(11), "BEAR-D02"),
        ("no topic", folder(12, topic=""), "BEAR-D01"),
        ("no flags", folder(13, flags=0), "BEAR-D03"),
        ("two photos flagged", folder(14, extra=[dict(files=["a.jpg", "b.jpg"], money=True)]), "BEAR-D04"),
        ("HEIC flagged", folder(15, extra=[dict(files=["IMG_5.HEIC"], money=True)]), "BEAR-D05"),
    ]
    for what, ch, code in cases:
        await run(ch)
        check(what, f"`{code}`" in last_error() and f"`{code}`" in ch.sent[-1][0], True)

    # Name model failures and a crash, from the simulated run's log.
    for i, (sim, code) in enumerate([("rate-limit", "BEAR-N01"), ("no-response", "BEAR-N02"),
                                     ("unusable", "BEAR-N03"), ("crash", "BEAR-R01")]):
        ch = await run(folder(20 + i))
        await run(ch, sim)
        check(f"sim {sim}", f"`{code}`" in last_error(), True)

    # Upload still arriving: /run waits for a quiet spell, then runs.
    ch = folder(30)
    ch.add(files=["IMG_99.jpg"], money=True, ago=0)
    await run(ch)
    check("waited for uploads", any("still uploading" in t for t, _ in ch.sent), True)
    check("ran after waiting", ch.sent[-1][1], "Q184-mitsubishi-shogun-2007.xlsx")

    # Three folders at once with two slots: one is queued, all three finish.
    chans = [folder(40 + i, name=f"BOX{i}") for i in range(3)]
    os.environ["BEAR_SIM"] = "ok"
    await asyncio.gather(*(B.run.callback(Inter(c)) for c in chans))
    check("one queued", sum(any("queued" in t for t, _ in c.sent) for c in chans), 1)
    check("all three posted", [c.sent[-1][1] for c in chans],
          [f"BOX{i}-mitsubishi-shogun-2007.xlsx" for i in range(3)])
    check("nothing left running", B.ACTIVE, {})

    # /run twice at once in one channel (double click, two people): the second is refused.
    ch, second = folder(50), None
    second = Inter(ch)
    await asyncio.gather(B.run.callback(Inter(ch)), B.run.callback(second))
    check("second /run refused", any("in this channel is still" in r for r in second.replies), True)
    check("only one spreadsheet", sum(1 for _, f in ch.sent if f), 1)

asyncio.run(main())
if fails:
    print("\n".join(fails))
    sys.exit(f"{len(fails)} failed (run folders in {TMP})")
print(f"all Discord flow checks passed (run folders in {TMP})")
