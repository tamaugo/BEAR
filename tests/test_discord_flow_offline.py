#!/usr/bin/env python3
"""Offline end-to-end checks of the Discord bot (no Discord, no network, no credits). Needs
discord.py (the server's .venv has it).

Plays /run through the real bot code against a fake car channel, with BEAR's dev mode
(bear2/simulate.py) as the run: the spreadsheet posted for a good folder, every BEAR-D error a
person can cause, the name model failures (N01-N03) and a crash (R01) landing in the error
channel, and three folders at once with two slots (one waits in the queue). Then the renaming
(/run's offer is off unless BEAR_RENAME_OFFER is on): the SKU typed in that offer, the zip of
every photo posted after the spreadsheet, /rename on its own, and /quit stopping a run. A restart in the
middle of a run: the next start marks its card stopped. Last, the shadow test with its models faked: every photo logged,
reruns not counted twice, and the note in the error channel.

usage: .venv/bin/python tests/test_discord_flow_offline.py
"""
import asyncio, io, logging, os, sys, tempfile, time, zipfile
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
import renames as rn  # noqa: E402
from PIL import Image  # noqa: E402

ME, PERSON = NS(id=7, bot=True), NS(id=8, bot=False)
CAR = "MITSUBISHI SHOGUN 2007 3.2 DI-D"
B.bot._connection.user = ME
logging.disable(logging.CRITICAL)   # the bot logs every error it posts; the checks below cover them
B.car_channel_problem = lambda ch: None
B.NAME_RETRY_WAITS = (0, 0)   # retry the names at once in the test
B.rename_wait = lambda: WAIT[0]   # the rename offer's minute, shortened for the test
WAIT = [0.05]
ZIPPED = {"door.zip": ["b/10.jpg", "b/2.jpg", "__MACOSX/b/._2.jpg"], "empty.zip": ["readme.txt"],
          "bad.zip": []}


class Att:
    def __init__(self, filename):
        self.filename = filename

    async def save(self, path):
        if self.filename.endswith(".zip"):   # a zip of photos from the owner's picker app
            with zipfile.ZipFile(path, "w") as z:
                for n in ZIPPED.get(self.filename, []):
                    buf = io.BytesIO()
                    Image.new("RGB", (64, 48), "white").save(buf, "JPEG")
                    z.writestr(n, buf.getvalue())
            return
        Image.new("RGB", (64, 48), "white").save(path, "JPEG" if Path(path).suffix != ".webp" else "WEBP")

    async def read(self):
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), "white").save(buf, "JPEG")
        return buf.getvalue()


def flat(content, embeds):
    """A post as plain text (content + each embed's title and description), for the checks."""
    return "\n".join([content or ""] + [f"{e.title or ''}\n{e.description or ''}" for e in embeds or []])


class Channel:
    """A fake car channel. sent: [(text, file name)] per bot message, updated when it is edited
    (the run card); shown: every text a message ever had, so passing states can be checked."""

    def __init__(self, cid, topic=CAR):
        self.id, self.name, self.topic, self.mention = cid, f"car-{cid}", topic, f"<#{cid}>"
        self.msgs, self.sent, self.shown = [], [], []
        self.events = []   # ("file", name) each time a file goes up, in order
        self.zips = {}     # zip name -> names inside it, read as it is posted
        self.view = None   # the buttons last put on a message
        self.read = 0      # messages handed out by history(), to see how far back the bot reads

    def add(self, author=PERSON, content="", files=(), ago=300, embeds=()):
        m = NS(id=self.id * 1000 + len(self.msgs), author=author, content=content,
               attachments=[Att(f) for f in files], embeds=list(embeds), reactions=[],
               created_at=datetime.now(timezone.utc) - timedelta(seconds=ago),
               jump_url=f"https://discord.com/channels/1/{self.id}/{len(self.msgs)}")
        self.msgs.append(m)
        return m

    async def history(self, limit=100):
        for m in self.msgs[::-1][:limit]:
            self.read += 1
            yield m

    def posted(self, file):
        if file:
            self.events.append(("file", file.filename))
            if file.filename.endswith(".zip"):
                self.zips[file.filename] = zipfile.ZipFile(file.fp).namelist()

    async def send(self, content=None, embeds=None, file=None, files=None, delete_after=None, view=None,
                   allowed_mentions=None):
        text = flat(content, embeds)
        self.sent.append((text, file.filename if file else None))
        self.shown.append(text)
        self.posted(file)
        if view is not None:
            self.view = view
        m = self.add(ME, content or "", ago=0, embeds=embeds or [])
        i, ch = len(self.sent) - 1, self

        async def edit(content=None, embeds=None, attachments=None, view=False):
            text = flat(content, embeds)
            ch.sent[i] = (text, attachments[0].filename if attachments else ch.sent[i][1])
            ch.shown.append(text)
            ch.posted(attachments[0] if attachments else None)
            m.content, m.embeds = content or "", embeds or []
        m.edit = edit
        return m

    async def fetch_message(self, mid):
        m = next((m for m in self.msgs if m.id == mid), None)
        if m is None:
            raise B.discord.DiscordException(f"Unknown Message {mid}")
        return m


ERRORS = Channel(99)


async def error_channel():
    return ERRORS
B.bot.error_channel = error_channel


class Inter:
    def __init__(self, ch):
        self.channel, self.replies, self.user = ch, [], "person"
        self.response = NS(send_message=self.reply, is_done=lambda: True)
        self.followup = NS(send=self.reply)

    async def reply(self, content=None, embeds=None, ephemeral=False):
        self.replies.append(flat(content, embeds))
        if not ephemeral:
            self.channel.add(ME, content or "", ago=0, embeds=embeds or [])


def folder(cid, name="Q184", parts=4, topic=CAR, extra=()):
    """A folder of part-number photos: the first two in one message, the rest one per message."""
    ch = Channel(cid, topic)
    ch.add(ME, fo.marker(name))
    if parts:
        ch.add(files=["IMG_1.jpg", "IMG_2.jpg"][:parts])
    for i in range(parts - 2):
        ch.add(files=[f"IMG_{10 + i}.{'webp' if i % 2 else 'jpg'}"])
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


def card(ch):
    """The latest run card (the rename card and zips carry the 🏷️ tag)."""
    return [s for s in ch.sent if look.TAG not in s[0]][-1]


def rename_card(ch):
    return [s for s in ch.sent if look.TAG in s[0] and not s[0].lstrip().startswith(look.TAG + " **")][-1]


async def type_sku(ch, sku, late=False):
    """Wait for /run's offer, then type the SKU in its box (as the button and text box would)."""
    while ch.view is None:
        await asyncio.sleep(0.01)
    box = B.SkuBox(ch.view)
    box.sku._value = sku
    if late:
        ch.view.deadline = time.time() - 1
    i = Inter(ch)
    await box.on_submit(i)
    return i


async def run_with_sku(ch, sku, sim="ok", late=False):
    os.environ["BEAR_SIM"] = sim
    WAIT[0] = 5
    try:
        _, i = await asyncio.gather(B.run.callback(Inter(ch)), type_sku(ch, sku, late))
    finally:
        WAIT[0] = 0.05
    return i


async def main():
    # A good folder: every photo saved in photos/ as 001.jpg ... for BEAR, each one a part; the
    # simulated spreadsheet posted, and no rename offer.
    ch = await run(folder(10))
    text, fname = card(ch)
    check("spreadsheet posted", fname, "Q184-mitsubishi-shogun-2007.xlsx")
    check("parts counted", "priced **6 of 7** parts" in text, True)
    check("running shown", any("Running 4 parts" in t for t in ch.shown), True)
    check("one card per run, no rename offer", len(ch.sent), 1)
    check("card ends done", "Done" in text, True)
    run_dir = next((TMP / "car-10-10").iterdir())
    check("every photo goes to BEAR", sorted(p.name for p in (run_dir / "photos").iterdir()),
          ["001.jpg", "002.jpg", "003.jpg", "004.webp"])
    check("photos.tsv", [l.split("\t")[:2] for l in (run_dir / "photos.tsv").read_text().splitlines()],
          [["001.jpg", "IMG_1.jpg"], ["002.jpg", "IMG_2.jpg"], ["003.jpg", "IMG_10.jpg"], ["004.webp", "IMG_11.webp"]])
    check("own spend ledger used", (run_dir / "results" / "results.xlsx").exists(), True)
    check("no error posted", ERRORS.sent, [])
    check("finished run leaves no restart note", list(B.RUNNING_DIR.glob("*.json")), [])

    # A zip of photos counts as its photos, at its place in the folder, in name order inside it.
    # The zip stays in Discord and a copy stays on the server (zips/); nothing is deleted.
    ch = Channel(15)
    ch.add(ME, fo.marker("Q190"))
    ch.add(files=["IMG_1.jpg"])
    zmsg = ch.add(files=["door.zip", "empty.zip"])
    ch.add(files=["IMG_9.webp"])
    await run(ch)
    check("zip: run counts the photos inside", any("Running 4 parts" in t for t in ch.shown), True)
    check("zip: card ends done", "Done" in card(ch)[0], True)
    run_dir = next((TMP / "car-15-15").iterdir())
    check("zip: photos unpacked in order", sorted(p.name for p in (run_dir / "photos").iterdir()),
          ["001.jpg", "002.jpg", "003.jpg", "004.webp"])
    check("zip: photos.tsv says which zip and photo",
          [l.split("\t")[:2] for l in (run_dir / "photos.tsv").read_text().splitlines()],
          [["001.jpg", "IMG_1.jpg"], ["002.jpg", "door.zip/b/2.jpg"], ["003.jpg", "door.zip/b/10.jpg"],
           ["004.webp", "IMG_9.webp"]])
    check("zip: zips kept on the server", sorted(p.name for p in (run_dir / "zips").iterdir()),
          ["01-door.zip", "02-empty.zip"])
    check("zip: zip message kept in Discord", zmsg in ch.msgs, True)
    check("zip: no error posted", ERRORS.sent, [])

    ch = Channel(16)
    ch.add(ME, fo.marker("Q191"))
    ch.add(files=["empty.zip"])
    await run(ch)
    check("zip with no photos -> D03", "BEAR-D03" in last_error(), True)
    ch = Channel(17)
    ch.add(ME, fo.marker("Q192"))
    ch.add(files=["IMG_1.jpg"])
    ch.add(files=["bad.zip"])
    os.environ["BEAR_SIM"] = "ok"
    _save = Att.save

    async def broken(self, path):
        if self.filename == "bad.zip":
            return Path(path).write_bytes(b"not a zip")
        return await _save(self, path)
    Att.save = broken
    await run(ch)
    Att.save = _save
    check("broken zip -> D08", "BEAR-D08" in last_error(), True)
    check("broken zip kept on the server", (next((TMP / "car-17-17").iterdir()) / "zips" / "01-bad.zip").exists(), True)
    ERRORS.sent.clear()

    # People can type notes between the photos: text is never deleted, never answered, and never
    # changes what is sent to BEAR (same photos, same names as the folder above).
    B.CARS_CATEGORY_ID = 555
    ch = Channel(14)
    ch.category_id = 555
    ch.add(ME, fo.marker("Q184"))
    ch.add(PERSON, "bumper bracket LH, cracked")
    ch.add(files=["IMG_1.jpg", "IMG_2.jpg"])
    ch.add(PERSON, "part 2 is the 2012 type, check fit")
    ch.add(files=["IMG_10.jpg"], content="caption on a photo")
    ch.add(files=["IMG_11.webp"])
    ch.add(PERSON, "that's the box done")
    notes = [m for m in ch.msgs if m.author is PERSON and not m.attachments]
    for m in notes:
        m.delete_calls = 0
        m.guild, m.channel, m.type = True, ch, B.discord.MessageType.default

        async def delete(m=m):
            m.delete_calls += 1
        m.delete = delete
        await B.bot.on_message(m)
    check("typed notes are kept", [m.delete_calls for m in notes], [0, 0, 0])
    check("typed notes get no notice", ch.sent, [])
    # Outside the car channels a person's message gets the brick wall picture, which deletes itself
    # after 4 seconds. Car channels (this one is in category 555), bots, other kinds of message and
    # the picture itself (a bot's) get nothing; with no car category set, nothing is a non-car channel.
    walls = []

    def talk(channel, who=PERSON, kind=B.discord.MessageType.default, guild=True):
        m = NS(author=who, guild=guild, channel=channel, type=kind, attachments=[])

        async def reply(**kw):
            walls.append(kw)
        m.reply = reply
        return m
    lounge = NS(id=30, category_id=556)
    thread = NS(id=31, category_id=556)      # a thread reports its parent's category
    car_thread = NS(id=32, category_id=555)
    no_category = NS(id=33)                  # a channel outside any category
    await B.bot.on_message(talk(ch))
    await B.bot.on_message(talk(car_thread))
    await B.bot.on_message(talk(lounge, who=ME))
    await B.bot.on_message(talk(lounge, kind=B.discord.MessageType.new_member))
    await B.bot.on_message(talk(lounge, guild=None))
    check("car channels, bots, joins and DMs get no brick wall", walls, [])
    await B.bot.on_message(talk(lounge))
    await B.bot.on_message(talk(thread, kind=B.discord.MessageType.reply))
    await B.bot.on_message(talk(no_category))
    check("other channels each get one brick wall", len(walls), 3)
    check("brick wall deletes itself after 4 seconds", {w["delete_after"] for w in walls}, {4})
    check("brick wall is the picture, without pinging", {(w["file"].filename, w["mention_author"]) for w in walls},
          {("brick-wall.jpg", False)})
    check("brick wall picture is in the repo", B.BRICK_WALL.is_file(), True)

    async def refused(**kw):
        raise B.discord.Forbidden(NS(status=403, reason="no"), "no permission")
    m = talk(lounge)
    m.reply = refused
    await B.bot.on_message(m)      # no permission to post there: nothing raised
    B.CARS_CATEGORY_ID = None
    walls.clear()
    await B.bot.on_message(talk(lounge))
    check("no car category set: no brick wall", walls, [])
    await run(ch)
    run_dir = next((TMP / "car-14-14").iterdir())
    check("notes don't change the photos", sorted(p.name for p in (run_dir / "photos").iterdir()),
          ["001.jpg", "002.jpg", "003.jpg", "004.webp"])
    check("notes don't change the parts", "priced **6 of 7** parts" in card(ch)[0], True)
    check("notes cause no error", ERRORS.sent, [])

    # read_folder stops at the newest marker, with exactly the answer reading all HISTORY_LIMIT
    # messages and splitting them gave (the old way); D02 the same when no marker is in reach.
    async def old_read_folder(ch):
        history = [m async for m in ch.history(limit=B.HISTORY_LIMIT)]
        name, marker, after = fo.split_folder(history, B.bot.user.id)
        if not name:
            raise fo.FolderError("BEAR-D02")
        return name, after, marker

    async def outcome(read, ch):
        try:
            name, after, marker = await read(ch)
            return name, [m.id for m in after], marker.id
        except fo.FolderError as e:
            return e.code

    limit, B.HISTORY_LIMIT = B.HISTORY_LIMIT, 10

    def chan(cid, plan):
        """plan, oldest first: a folder name is its marker, "p" a photo, "t" a bot text message."""
        ch = Channel(cid)
        for x in plan:
            ch.add(ME, fo.marker(x)) if len(x) > 1 else ch.add(ME, "card") if x == "t" else ch.add(files=["a.jpg"])
        return ch
    shapes = {
        "one folder": ["Q1", "p", "p", "t"],
        "two folders, newest wins": ["Q1", "p", "Q2", "p", "p"],
        "marker newest, no photos yet": ["p", "Q1"],
        "no marker at all (D02)": ["p", "p", "t"],
        "empty channel (D02)": [],
        "marker exactly at the limit": ["Q1"] + ["p"] * 9,
        "marker one past the limit (D02)": ["Q1"] + ["p"] * 10,
        "older marker past the limit": ["Q0", "p", "p", "Q1"] + ["p"] * 6,
    }
    for i, (what, plan) in enumerate(shapes.items()):
        ch = chan(200 + i, plan)
        old = await outcome(old_read_folder, ch)
        ch.read = 0
        new = await outcome(B.read_folder, ch)
        check(f"read_folder same as before: {what}", new, old)
        stop = next((k + 1 for k, m in enumerate(ch.msgs[::-1][:10]) if fo.marker_name(m, ME.id)), min(len(plan), 10))
        check(f"read_folder stops at the marker: {what}", ch.read, stop)
    check("marker at the limit found", await outcome(B.read_folder, chan(299, shapes["marker exactly at the limit"])),
          ("Q1", [299001 + k for k in range(9)], 299000))
    B.HISTORY_LIMIT = limit

    # Problems a person can cause.
    cases = [
        ("no folder", Channel(11), "BEAR-D02"),
        ("no topic", folder(12, topic=""), "BEAR-D01"),
        ("no photos", folder(13, parts=0), "BEAR-D03"),
        ("a HEIC photo", folder(15, extra=[dict(files=["IMG_5.HEIC"])]), "BEAR-D05"),
    ]
    for what, ch, code in cases:
        await run(ch)
        check(what, f"`{code}`" in last_error() and look.TITLES[code] in card(ch)[0], True)

    # Name model failures and a crash, from the simulated run's log.
    for i, (sim, code) in enumerate([("rate-limit", "BEAR-N01"), ("no-response", "BEAR-N02"),
                                     ("unusable", "BEAR-N03"), ("crash", "BEAR-R01")]):
        ch = await run(folder(20 + i))
        await run(ch, sim)
        check(f"sim {sim}", f"`{code}`" in last_error(), True)
        if code != "BEAR-R01":   # names failed: only the names were tried again, twice
            log_text = sorted((TMP / f"car-{20 + i}-{20 + i}").iterdir())[-1].joinpath("bear.log").read_text()
            check(f"sim {sim}: names retried twice", log_text.count("retrying only the part names"), 2)
            check(f"sim {sim}: photos read once", log_text.count("Reading part numbers 1/"), 1)

    # The name model fails once, then the names-only retry works: the spreadsheet is posted.
    errors_before = len(ERRORS.sent)
    ch = await run(folder(28), "names-once")
    check("names-once: spreadsheet posted after retrying the names", card(ch)[1], "Q184-mitsubishi-shogun-2007.xlsx")
    check("names-once: no error posted", len(ERRORS.sent), errors_before)

    # The final check flags a row: the owner hears (BEAR-V01, the row), the uploader's card stays green.
    ERRORS.sent.clear()
    ch = await run(folder(27), "flagged")
    check("flagged: spreadsheet posted", card(ch)[1], "Q184-mitsubishi-shogun-2007.xlsx")
    check("flagged: card stays green", "Done" in card(ch)[0], True)
    check("flagged: V01 to the owner", "`BEAR-V01`" in last_error() and "price unparseable" in last_error(), True)
    check("flagged: one error post", len(ERRORS.sent), 1)

    # eBay down for most of the run: the spreadsheet is still posted, plus BEAR-E01 in amber.
    ch = await run(folder(26), "outage")
    check("outage: spreadsheet still posted", any(f == "Q184-mitsubishi-shogun-2007.xlsx" for _, f in ch.sent), True)
    check("outage: E01 in the error channel", "`BEAR-E01`" in last_error(), True)
    check("outage: amber note under the card", "Some parts not priced" in card(ch)[0], True)

    # Upload still arriving: /run waits for a quiet spell, then runs.
    ch = folder(30)
    ch.add(files=["IMG_99.jpg"], ago=0)
    await run(ch)
    check("waited for uploads", any("Waiting for uploads" in t for t in ch.shown), True)
    check("ran after waiting", card(ch)[1], "Q184-mitsubishi-shogun-2007.xlsx")

    # Three folders at once with two slots: one is queued, all three finish.
    chans = [folder(40 + i, name=f"BOX{i}") for i in range(3)]
    os.environ["BEAR_SIM"] = "ok"
    await asyncio.gather(*(B.run.callback(Inter(c)) for c in chans))
    check("one queued", sum(any("Queued" in t for t in c.shown) for c in chans), 1)
    check("all three posted", [card(c)[1] for c in chans],
          [f"BOX{i}-mitsubishi-shogun-2007.xlsx" for i in range(3)])
    check("nothing left running", B.ACTIVE, {})

    # /run twice at once in one channel (double click, two people): the second is refused.
    ch, second = folder(50), None
    second = Inter(ch)
    await asyncio.gather(B.run.callback(Inter(ch)), B.run.callback(second))
    check("second /run refused", any("here is still" in r for r in second.replies), True)
    check("only one spreadsheet", sum(1 for _, f in ch.sent if f), 1)

    # Owner-side problems don't tell the uploader to edit .env; D05 links to the photo.
    ch = await run(folder(60), "rate-limit")
    check("N01 card hides the fix", ".env" not in card(ch)[0] and "Nothing for you to do" in card(ch)[0], True)
    ch = await run(folder(61, extra=[dict(files=["IMG_5.HEIC"])]))
    check("D05 links the photo", "[Photo 1](https://discord.com/channels/1/61/" in card(ch)[0], True)

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

    # Renaming in /run, with the dormant offer switched back on: no SKU, no rename.
    os.environ["BEAR_RENAME_OFFER"] = "1"
    ch = await run(folder(79))
    check("offer on: one run card and one rename card", len(ch.sent), 2)
    check("no SKU: not renamed", "No SKU given" in rename_card(ch)[0], True)

    # With a SKU: every photo from the marker on, in upload order, posted as a
    # zip after the spreadsheet. Other files are left out; BEAR's own photos are untouched.
    ch = folder(80, extra=[dict(files=["two_a.png", "two_b.jpg"]), dict(files=["clip.mp4"])])
    i = await run_with_sku(ch, "MYSKU")
    check("SKU accepted", any("**MYSKU-1**" in r for r in i.replies), True)
    check("spreadsheet still posted", card(ch)[1], "Q184-mitsubishi-shogun-2007.xlsx")
    check("zip posted", ch.zips.get("MYSKU-1.zip"),
          ["MYSKU-1.jpg", "MYSKU-2.jpg", "MYSKU-3.jpg", "MYSKU-4.webp", "MYSKU-5.png", "MYSKU-6.jpg"])
    files = [f for _, f in ch.events]
    check("zip after the spreadsheet", files, ["Q184-mitsubishi-shogun-2007.xlsx", "MYSKU-1.zip"])
    check("rename card done", "6 photos renamed" in rename_card(ch)[0] and "1 file that isn't a photo" in rename_card(ch)[0], True)
    job = next((TMP / "renames" / "car-80-80").iterdir())
    check("only the list stays on disk", sorted(p.name for p in job.iterdir()), ["renamed.tsv"])
    check("list maps names back", (job / "renamed.tsv").read_text().splitlines()[0].split("\t")[:2], ["MYSKU-1.jpg", "IMG_1.jpg"])
    check("BEAR's photos untouched", sorted(p.name for p in (next((TMP / "car-80-80").iterdir()) / "photos").iterdir()),
          ["001.jpg", "002.jpg", "003.jpg", "004.webp", "005.png", "006.jpg"])
    logged = (TMP / "renames" / "renames.log").read_text()
    check("rename logged", "\tQ184\tMYSKU\tposted\t6\t1\t" in logged, True)

    # The rename doesn't need BEAR: a HEIC BEAR can't read still gets the zip (after the error card).
    ch = folder(81, parts=2, extra=[dict(files=["IMG_5.HEIC"])])
    await run_with_sku(ch, "NOBEAR")
    check("BEAR fails D05", look.TITLES["BEAR-D05"] in card(ch)[0], True)
    check("zip without BEAR", ch.zips.get("NOBEAR-1.zip"), ["NOBEAR-1.jpg", "NOBEAR-2.jpg", "NOBEAR-3.heic"])

    # A bad SKU is refused (the button stays); a SKU after the minute is too late.
    ch = folder(82)
    WAIT[0] = 5
    run_task = asyncio.create_task(B.run.callback(Inter(ch)))
    bad = await type_sku(ch, "MY SKU!")
    check("bad SKU refused", any("letters, numbers" in r for r in bad.replies), True)
    late = await type_sku(ch, "LATE", late=True)
    check("late SKU refused", any("Too late" in r for r in late.replies), True)
    WAIT[0] = 0.05
    ch.view.answer.set_result(None) if not ch.view.answer.done() else None
    await run_task
    check("no zip when refused", ch.zips, {})

    # No folder: the offer closes straight away instead of waiting the minute.
    ch, WAIT[0] = Channel(83), 30
    t0 = time.time()
    await run(ch)
    WAIT[0] = 0.05
    check("no folder closes the offer", time.time() - t0 < 5 and "Nothing to rename" in rename_card(ch)[0], True)

    # /rename on its own: just the zip, no BEAR; refused SKU; no folder.
    ch = folder(84)
    i = Inter(ch)
    await B.rename.callback(i, "ALONE")
    check("/rename zip", ch.zips.get("ALONE-1.zip"), ["ALONE-1.jpg", "ALONE-2.jpg", "ALONE-3.jpg", "ALONE-4.webp"])
    check("/rename runs no BEAR", any(f.endswith(".xlsx") for _, f in ch.events), False)
    i = Inter(ch)
    await B.rename.callback(i, "../x")
    check("/rename bad SKU", any("letters, numbers" in r for r in i.replies), True)
    ch = Channel(85)
    await B.rename.callback(Inter(ch), "NOPE")
    check("/rename no folder", look.TITLES["BEAR-D02"] in ch.sent[-1][0], True)

    # /quit: stops BEAR while it runs, and the rename waiting for it; nothing more is posted.
    os.environ["BEAR_SIM_PAUSE"] = "1"
    ch = folder(86)

    async def quit_when_running():
        await type_sku(ch, "STOPME")
        while B.ACTIVE.get(ch.id, {}).get("state") != "running":
            await asyncio.sleep(0.02)
        q = Inter(ch)
        await B.quit_cmd.callback(q)
        return q
    WAIT[0] = 5
    t0 = time.time()
    _, q = await asyncio.gather(B.run.callback(Inter(ch)), quit_when_running())
    WAIT[0] = 0.05
    os.environ["BEAR_SIM_PAUSE"] = "0.02"
    check("/quit replies", any("Stopping folder **Q184**" in r for r in q.replies), True)
    check("/quit stops quickly", time.time() - t0 < 5, True)
    check("run card stopped", "Stopped" in card(ch)[0], True)
    check("rename card stopped", "Stopped" in rename_card(ch)[0], True)
    check("nothing posted after /quit", ch.events, [])
    check("channel free after /quit", ch.id in B.ACTIVE, False)
    check("rename files tidied", [p.name for p in next((TMP / "renames" / "car-86-86").iterdir()).iterdir()], ["renamed.tsv"])
    q = Inter(ch)
    await B.quit_cmd.callback(q)
    check("/quit with nothing running", any("Nothing is running" in r for r in q.replies), True)
    os.environ.pop("BEAR_RENAME_OFFER")
    check("/quit leaves no restart note", list(B.RUNNING_DIR.glob("*.json")), [])

    # /update: anyone can; it leaves a note for systemd (bear-update.path) rather than running anything itself.
    B.UPDATE_REQUEST, B.UPDATE_UNIT = TMP / "update-request", TMP / "bear-update.path"
    B.UPDATE_REQUEST.unlink(missing_ok=True)
    B.UPDATE_UNIT.unlink(missing_ok=True)
    i = Inter(Channel(95))
    await B.update.callback(i)
    check("/update not set up", any("can't update itself" in r for r in i.replies) and not B.UPDATE_REQUEST.exists(), True)
    B.UPDATE_UNIT.write_text("")
    B.ACTIVE[95] = {"folder": "Q1", "state": "running", "parts": 1, "since": time.time()}
    i = Inter(Channel(95))
    await B.update.callback(i)
    check("/update waits for a run", any("still working on 1 folder" in r for r in i.replies) and not B.UPDATE_REQUEST.exists(), True)
    del B.ACTIVE[95]
    ERRORS.sent.clear()
    i = Inter(Channel(95))
    await B.update.callback(i)
    check("/update leaves the note", B.UPDATE_REQUEST.exists() and any("Updating BEAR" in r for r in i.replies), True)
    check("/update tells the error channel", "/update" in str(ERRORS.sent), True)
    i = Inter(Channel(95))
    await B.update.callback(i)
    check("/update twice is one update", any("already on its way" in r for r in i.replies), True)
    B.UPDATE_REQUEST.unlink()
    B.ACTIVE[95] = {"folder": "Q1", "state": "running", "parts": 1, "since": time.time()}
    i = Inter(Channel(95))
    await B.update.callback(i, force=True)
    del B.ACTIVE[95]
    check("/update force goes ahead", B.UPDATE_REQUEST.exists(), True)
    B.UPDATE_REQUEST.unlink()

    # An /update note nobody picked up (the watcher wasn't running) stops blocking /update after 45 minutes.
    B.UPDATE_REQUEST.write_text("old\n")
    os.utime(B.UPDATE_REQUEST, (time.time() - B.UPDATE_STALE - 60,) * 2)
    i = Inter(Channel(95))
    await B.update.callback(i)
    check("/update: a stale note is replaced", any("Updating BEAR" in r for r in i.replies)
          and "person" in B.UPDATE_REQUEST.read_text(), True)
    B.UPDATE_REQUEST.unlink()

    # The run card was deleted (or Discord wouldn't edit it) when the spreadsheet was ready: discord.py
    # closes a file once it has tried to send it, so the new message needs a fresh one. The
    # spreadsheet used to be lost here, with BEAR-R01 for a run that had worked.
    ch = folder(96)
    real_send = ch.send

    async def send_closing(**kw):
        if kw.get("file") is not None and kw["file"].fp.closed:
            raise ValueError("I/O operation on closed file")   # what discord.py does with a used File
        m = await real_send(**kw)

        async def edit(content=None, embeds=None, attachments=None, view=False):
            if attachments:
                for f in attachments:
                    f.close()   # as discord.py does, whether the edit worked or not
                raise B.discord.DiscordException("Unknown Message")
            ch.sent[0] = (flat(content, embeds), ch.sent[0][1])
        m.edit = edit
        return m
    ch.send = send_closing
    ERRORS.sent.clear()
    await run(ch)
    text, fname = card(ch)
    check("card gone: spreadsheet still posted", (fname, "Done" in text), ("Q184-mitsubishi-shogun-2007.xlsx", True))
    check("card gone: no error", ERRORS.sent, [])

    # A topic typed over two lines, or with a | in it, is one line with spaces: BEAR's result lines
    # are one line each with | between the fields, so it used to break every row of the spreadsheet.
    ch = await run(folder(97, topic="MITSUBISHI SHOGUN\n2007 | 3.2 DI-D "))
    check("two-line topic: car on one line", B.car_of(ch), "MITSUBISHI SHOGUN 2007 3.2 DI-D")
    check("two-line topic: done", "Done" in card(ch)[0], True)
    lines = (next((TMP / "car-97-97").iterdir()) / "results" / "agent3_results.txt").read_text().splitlines()
    check("two-line topic: every row has its 5 fields", {len(l.split("|")) for l in lines}, {5})
    check("two-line topic: no error", ERRORS.sent, [])

    # /newfolder typed while /run is still waiting for uploads doesn't take the run over: the run
    # keeps the folder it started with (its photos only), instead of switching to the new, empty one.
    ch = folder(98, name="Q200", parts=2)
    first = ch.msgs[0]
    check("pinned: the folder /run started with", (await B.read_folder(ch, first.id))[0], "Q200")
    ch.add(ME, fo.marker("Q201"))
    ch.add(files=["IMG_50.jpg"])
    name, msgs, marker = await B.read_folder(ch, first.id)
    check("pinned: still the first folder", (name, marker is first), ("Q200", True))
    check("pinned: only its own photos", [att.filename for m in msgs for att in m.attachments], ["IMG_1.jpg", "IMG_2.jpg"])
    check("not pinned: the newest folder", (await B.read_folder(ch))[0], "Q201")
    ch = folder(98, name="Q200", parts=2)
    ch.msgs[-1].created_at = datetime.now(timezone.utc)   # an upload just now: /run waits a second
    task = asyncio.create_task(run(ch))
    while not any("Waiting for uploads" in t for t in ch.shown):
        await asyncio.sleep(0.01)
    ch.add(ME, fo.marker("Q201"))
    await task
    check("newfolder during the wait: the first folder is run", ("Q200" in card(ch)[0], "Done" in card(ch)[0]), (True, True))
    check("newfolder during the wait: its 2 photos", any("Running 2 parts" in t for t in ch.shown), True)

    # Photos uploaded after /run has read the folder aren't in the run: the done card says so.
    os.environ["BEAR_SIM_PAUSE"] = "0.3"
    ch = folder(93, parts=2)
    task = asyncio.create_task(run(ch))
    while not any("pricing the parts" in t for t in ch.shown):
        await asyncio.sleep(0.01)
    ch.add(files=["LATE_1.jpg", "LATE_2.jpg", "notes.pdf"], ago=0)
    await task
    os.environ["BEAR_SIM_PAUSE"] = "0.02"
    check("late uploads: the card says 2", "2 uploads arrived after /run started" in card(ch)[0], True)
    check("late uploads: still done, with its spreadsheet", ("Done" in card(ch)[0], card(ch)[1] is not None), (True, True))
    check("no late uploads: no warning", "arrived after" in card(await run(folder(92)))[0], False)

    # Every /run is added to the usage log: a spreadsheet, a failure and a /quit; never a folder with no photos.
    usage = [r for r in B.up.read_lines(B.up.usage_dir(TMP) / "usage.jsonl") if r["kind"] == "run"]
    check("usage log: the run just done", [(usage[-1][k]) for k in ("channel", "folder", "parts", "priced", "outcome", "dev")],
          ["car-92-92", "Q184", 7, 6, "sheet", True])
    check("usage log: failures and stops are there too", {"failed", "stopped"} <= {r["outcome"] for r in usage}, True)
    before = len(usage)
    await run(folder(91, parts=0))
    check("usage log: no photos is not a run", len(B.up.read_lines(B.up.usage_dir(TMP) / "usage.jsonl")), before + sum(
        1 for r in B.up.read_lines(B.up.usage_dir(TMP) / "usage.jsonl") if r["kind"] != "run"))

    # /health and /summary (dev mode: no keys checked, no network), posted in the channel for everyone to see.
    class Deferred(Inter):
        def __init__(self, ch):
            super().__init__(ch)
            self.response = NS(defer=self.defer, send_message=self.reply, is_done=lambda: True)

        async def defer(self, ephemeral=False, thinking=False):
            self.deferred = ephemeral
    i = Deferred(Channel(90))
    await B.health.callback(i)
    check("/health", (not i.deferred, "BEAR health" in i.replies[0], "not checked in dev mode" in i.replies[0],
                      "Disk" in i.replies[0]), (True, True, True, True))
    i = Deferred(Channel(90))
    await B.summary.callback(i)
    check("/summary", (not i.deferred, "This week so far" in i.replies[0], "BEAR has cost" in i.replies[0]), (True, True, True))
    check("/health and /summary are posted in the channel for everyone", len(i.channel.msgs), 1)

    # The daily and weekly jobs. First look: nothing to sum up yet, the day's jobs are done once.
    ERRORS.sent.clear()
    (B.up.usage_dir(TMP) / "state.json").unlink(missing_ok=True)
    old_run = TMP / "car-10-10"
    old_photos = next(old_run.iterdir()) / "photos"
    os.utime(old_photos.parent / "photos.tsv", (time.time() - 5 * 86400,) * 2)
    monday = datetime(2026, 11, 16, 8, 0, tzinfo=B.up.UK)
    await B.chores_once(monday)
    check("chores: photos older than 4 days deleted, results kept",
          (old_photos.exists(), (old_photos.parent / "results" / "results.xlsx").exists()), (False, True))
    check("chores: nothing posted when all is well", ERRORS.sent, [])
    await B.chores_once(monday + timedelta(days=6, hours=12))
    check("chores: no summary on the Sunday, the week isn't over", ERRORS.sent, [])
    await B.chores_once(monday + timedelta(days=7, minutes=10))
    check("chores: the weekly summary on Monday", len(ERRORS.sent) == 1 and "Weekly summary" in last_error()
          and "Mon 16 Nov to Sun 22 Nov" in last_error(), True)
    await B.chores_once(monday + timedelta(days=7, minutes=20))
    check("chores: once a week only", len(ERRORS.sent), 1)
    # eBay's daily allowance: one warning a day at 80%; a full disk and a dead key are reported once a day.
    ERRORS.sent.clear()
    cache_was, B.EBAY_CACHE = B.EBAY_CACHE, TMP
    os.environ["BEAR_EBAY_DAILY_LIMIT"] = "10"
    (TMP / f"calls-ebay-{time.strftime('%Y-%m-%d', time.gmtime())}.count").write_bytes(b"." * 8)
    disk_was, health_was = B.up.disk, B.health_rows
    B.up.disk = lambda storage: (0.5, 2.0)
    B.health_rows = lambda: [("OpenRouter", False, "OpenRouter refused the key (wrong or revoked)"), ("Disk", False, "0.5 GB free (2%)")]
    for _ in range(2):
        await B.chores_once(monday + timedelta(days=8))
    B.up.disk, B.health_rows, B.EBAY_CACHE = disk_was, health_was, cache_was
    os.environ.pop("BEAR_EBAY_DAILY_LIMIT")
    text = "\n".join(s[0] for s in ERRORS.sent)
    check("chores: eBay, disk and key warnings, once each", (len(ERRORS.sent), "8 of 10" in text, "disk is nearly full" in text,
                                                             "daily check found a problem" in text and "refused the key" in text),
          (3, True, True, True))

    # The error report still arrives when its log can't be attached (too big for Discord).
    ERRORS.sent.clear()
    real_error_send = ERRORS.send

    async def no_files(files=None, **kw):
        if files:
            raise B.discord.DiscordException("413 Payload Too Large")
        return await real_error_send(**kw)
    ERRORS.send = no_files
    logfile = TMP / "big-log.txt"
    logfile.write_text("log")
    await B.bot.fail(Channel(94), "Q1", "BEAR-R01", "boom", logfile)
    ERRORS.send = real_error_send
    check("error report sent without its log", "BEAR-R01" in last_error(), True)

    # A restart while a folder runs: the run dies without a word (here: its task is cancelled the
    # way the bot's shutdown cancels it), its note stays, and the next start marks the card stopped.
    os.environ["BEAR_SIM_PAUSE"] = "1"
    ch = folder(90, name="Q190")
    task = asyncio.create_task(run(ch))
    while B.ACTIVE.get(ch.id, {}).get("state") != "running":
        await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    os.environ["BEAR_SIM_PAUSE"] = "0.02"
    note = B.RUNNING_DIR / "90.json"
    check("restart: note kept", note.exists(), True)
    check("restart: card left on running", "Running 4 parts" in card(ch)[0], True)
    check("restart: note names the card", B.json.loads(note.read_text())["message_id"] in [m.id for m in ch.msgs], True)
    gone_msg = folder(91)
    (B.RUNNING_DIR / "91.json").write_text(B.json.dumps({"channel_id": 91, "message_id": 123, "folder": "X"}))
    (B.RUNNING_DIR / "92.json").write_text(B.json.dumps({"channel_id": 92, "message_id": 1, "folder": "Y"}))
    (B.RUNNING_DIR / "93.json").write_text("not json")
    chans = {90: ch, 91: gone_msg}

    async def no_channel(cid):
        raise B.discord.DiscordException(f"Unknown Channel {cid}")
    B.bot.get_channel, B.bot.fetch_channel = chans.get, no_channel
    errors_before = len(ERRORS.sent)

    async def no_heartbeat():
        pass
    B.heartbeat, B.chores, B.hb.update_log = no_heartbeat, no_heartbeat, lambda path: None   # chores: checked above
    B.bot.started = False
    await B.bot.on_ready()
    await asyncio.sleep(0)
    check("restart: card marked stopped", "Q190 · Stopped by a restart" in card(ch)[0] and "/run" in card(ch)[0], True)
    check("restart: still one card", len(ch.sent), 1)
    check("restart: missing channel, card and bad notes skipped, all tidied", list(B.RUNNING_DIR.glob("*.json")), [])
    check("restart: started message still posted", len(ERRORS.sent), errors_before + 1)
    check("restart: other channels untouched", gone_msg.sent, [])

    # Shadow test: off unless BEAR_SHADOW=1, never in dev mode; switched on here with the Decisions
    # models faked (no network).
    shadow_log = TMP / "shadow" / "shadow.jsonl"
    check("no shadow test in dev mode", shadow_log.exists(), False)
    dev_was = B.dev
    B.dev = lambda: False
    os.environ.pop("BEAR_SHADOW", None)
    check("shadow: off when not set", B.shadow_on(), False)
    os.environ["BEAR_SHADOW"] = "0"
    check("shadow: off with 0", B.shadow_on(), False)
    os.environ["BEAR_SHADOW"] = "1"
    check("shadow: on with 1", B.shadow_on(), True)
    B.dev = lambda: True
    check("shadow: never in dev mode", B.shadow_on(), False)
    B.dev = dev_was
    os.environ.pop("BEAR_SHADOW")
    asked = []

    def fake_check(model, uri, with_label):
        asked.append(uri.startswith("data:image/jpeg;base64,"))
        return {"label": 0.9 if with_label else None, "loc": "NF", "loc_p": {"NF": 0.9}, "cost": 0.0001}
    B.sh.check, B.shadow_on = fake_check, lambda: True
    os.environ.update({"BEAR_SHADOW_PING_PARTS": "3", "BEAR_SHADOW_PING_USER": "123"})
    errors_before = len(ERRORS.sent)
    ch = folder(87, parts=2)
    for _ in range(2):   # the second /run of the same folder replaces the first one's answers
        await run(ch)
        await asyncio.gather(*B.SHADOW)
    rows = B.sh.latest_runs(B.sh.read_log(shadow_log))
    check("shadow: every photo asked by every model", len(rows), 2 * (1 + len(B.sh.LOC_MODELS)))
    check("shadow: every photo is a part", all(r["flagged"] for r in rows), True)
    check("shadow: photos sent as JPEG", set(asked), {True})
    check("shadow: rerun not counted twice", B.sh.counts(B.sh.read_log(shadow_log)), (1, 2))
    check("shadow: no note before 3 part photos", len(ERRORS.sent), errors_before)
    await run(folder(88, name="Q185", parts=2))
    await asyncio.gather(*B.SHADOW)
    check("shadow: one note at 3+ part photos", len(ERRORS.sent), errors_before + 1)
    check("shadow: note mentions the owner", ERRORS.sent[-1][0].startswith("<@123>"), True)
    check("shadow: note says how much", "4 part photos" in ERRORS.sent[-1][0], True)
    await run(folder(89, name="Q186", parts=1))
    await asyncio.gather(*B.SHADOW)
    check("shadow: no second note until 6", len(ERRORS.sent), errors_before + 1)

asyncio.run(main())
if fails:
    print("\n".join(fails))
    sys.exit(f"{len(fails)} failed (run folders in {TMP})")
print(f"all Discord flow checks passed (run folders in {TMP})")
