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
sys.path.insert(0, str(ROOT / "tools"))
import jev_client  # noqa: E402
jev_client.ENV_FILE = TMP / "no.env"   # the server's .env (PASTE_HERE lines, real IDs) must not change the test
sys.path.insert(0, str(ROOT / "discordbot"))
import bot as B  # noqa: E402
import folders as fo  # noqa: E402
import look  # noqa: E402
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


def flat(content, embeds):
    """A post as plain text (content + each embed's title and description), for the checks."""
    return "\n".join([content or ""] + [f"{e.title or ''}\n{e.description or ''}" for e in embeds or []])


class Channel:
    """A fake car channel. sent: [(text, file name)] per bot message, updated when it is edited
    (the run card); shown: every text a message ever had, so passing states can be checked."""

    def __init__(self, cid, topic=CAR):
        self.id, self.name, self.topic, self.mention = cid, f"car-{cid}", topic, f"<#{cid}>"
        self.msgs, self.sent, self.shown = [], [], []

    def add(self, author=PERSON, content="", files=(), money=False, ago=300, embeds=()):
        m = NS(author=author, content=content, attachments=[Att(f) for f in files], embeds=list(embeds),
               reactions=[NS(emoji=fo.MONEY)] if money else [],
               created_at=datetime.now(timezone.utc) - timedelta(seconds=ago),
               jump_url=f"https://discord.com/channels/1/{self.id}/{len(self.msgs)}")
        self.msgs.append(m)
        return m

    async def history(self, limit=100):
        for m in self.msgs[::-1][:limit]:
            yield m

    async def send(self, content=None, embeds=None, file=None, files=None, delete_after=None):
        text = flat(content, embeds)
        self.sent.append((text, file.filename if file else None))
        self.shown.append(text)
        m = self.add(ME, content or "", ago=0, embeds=embeds or [])
        i, ch = len(self.sent) - 1, self

        async def edit(content=None, embeds=None, attachments=None):
            text = flat(content, embeds)
            ch.sent[i] = (text, attachments[0].filename if attachments else ch.sent[i][1])
            ch.shown.append(text)
            m.content, m.embeds = content or "", embeds or []
        m.edit = edit
        return m


ERRORS = Channel(99)


async def error_channel():
    return ERRORS
B.bot.error_channel = error_channel


class Inter:
    def __init__(self, ch):
        self.channel, self.replies = ch, []
        self.response = NS(send_message=self.reply, is_done=lambda: True)
        self.followup = NS(send=self.reply)

    async def reply(self, content=None, embeds=None, ephemeral=False):
        self.replies.append(flat(content, embeds))
        if not ephemeral:
            self.channel.add(ME, content or "", ago=0, embeds=embeds or [])


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
    check("parts counted", "priced **6 of 7** parts" in text, True)
    check("running shown", any("Running 2 parts" in t for t in ch.shown), True)
    check("one card per run", len(ch.sent), 1)
    check("card ends done", "Done" in text, True)
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
        check(what, f"`{code}`" in last_error() and look.TITLES[code] in ch.sent[-1][0], True)

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
    check("waited for uploads", any("Waiting for uploads" in t for t in ch.shown), True)
    check("ran after waiting", ch.sent[-1][1], "Q184-mitsubishi-shogun-2007.xlsx")

    # Three folders at once with two slots: one is queued, all three finish.
    chans = [folder(40 + i, name=f"BOX{i}") for i in range(3)]
    os.environ["BEAR_SIM"] = "ok"
    await asyncio.gather(*(B.run.callback(Inter(c)) for c in chans))
    check("one queued", sum(any("Queued" in t for t in c.shown) for c in chans), 1)
    check("all three posted", [c.sent[-1][1] for c in chans],
          [f"BOX{i}-mitsubishi-shogun-2007.xlsx" for i in range(3)])
    check("nothing left running", B.ACTIVE, {})

    # /run twice at once in one channel (double click, two people): the second is refused.
    ch, second = folder(50), None
    second = Inter(ch)
    await asyncio.gather(B.run.callback(Inter(ch)), B.run.callback(second))
    check("second /run refused", any("here is still" in r for r in second.replies), True)
    check("only one spreadsheet", sum(1 for _, f in ch.sent if f), 1)

    # Owner-side problems don't tell the uploader to edit .env; D04 links to the photo.
    ch = await run(folder(60), "rate-limit")
    check("N01 card hides the fix", ".env" not in ch.sent[-1][0] and "Nothing for you to do" in ch.sent[-1][0], True)
    ch = await run(folder(61, extra=[dict(files=["a.jpg", "b.jpg"], money=True)]))
    check("D04 links the photo", "[Photo 1](https://discord.com/channels/1/61/" in ch.sent[-1][0], True)

    # /newfolder: the marker card, and a heads-up when the folder before was never run.
    ch = folder(70, name="OLD")
    i = Inter(ch)
    await B.newfolder.callback(i, "NEW")
    check("marker posted", fo.split_folder(ch.msgs[::-1], ME.id)[0], "NEW")
    check("never-run warning", any("**OLD** was never run" in r for r in i.replies), True)
    ch = await run(folder(71, name="DONE1"))
    i = Inter(ch)
    await B.newfolder.callback(i, "NEXT")
    check("no warning after a run", any("never run" in r for r in i.replies), False)
    ch = Channel(72, topic="2012 FORD FIESTA")
    i = Inter(ch)
    await B.newfolder.callback(i, "Q1")
    check("topic order warning", any("start with the make" in r for r in i.replies), True)

    # /status is a card only the person who asked sees.
    i = Inter(Channel(73))
    await B.status.callback(i)
    check("status card", "Nothing running" in i.replies[-1], True)

asyncio.run(main())
if fails:
    print("\n".join(fails))
    sys.exit(f"{len(fails)} failed (run folders in {TMP})")
print(f"all Discord flow checks passed (run folders in {TMP})")
