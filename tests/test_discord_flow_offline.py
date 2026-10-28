#!/usr/bin/env python3
"""Offline end-to-end checks of the Discord bot (no Discord, no network, no credits). Needs
discord.py (the server's .venv has it).

Plays /run through the real bot code against a fake car channel, with BEAR's dev mode
(bear2/simulate.py) as the run: the spreadsheet posted for a good folder, every BEAR-D error a
person can cause, the name model failures (N01-N03) and a crash (R01) landing in the error
channel, and three folders at once with two slots (one waits in the queue). Then the renaming
(/run's offer is off unless BEAR_RENAME_OFFER is on): the SKU typed in that offer, the zip of
every photo posted after the spreadsheet, /rename on its own, and /quit stopping a run. Last, the shadow test with its models faked: every photo logged,
reruns not counted twice, and the note in the error channel. And the part check: a photo posted
gets a reply with the number partcheck.py read (dev mode: a made-up read, through the real process),
✅ / another reading / ✏️ save it in part-numbers.txt once, and the cases with nothing to show.

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
B.rename_wait = lambda: WAIT[0]   # the rename offer's minute, shortened for the test
WAIT = [0.05]


class Att:
    def __init__(self, filename):
        self.filename = filename

    async def save(self, path):
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

    def add(self, author=PERSON, content="", files=(), ago=300, embeds=()):
        m = NS(id=self.id * 1000 + len(self.msgs), author=author, content=content,
               attachments=[Att(f) for f in files], embeds=list(embeds), reactions=[],
               created_at=datetime.now(timezone.utc) - timedelta(seconds=ago),
               jump_url=f"https://discord.com/channels/1/{self.id}/{len(self.msgs)}")
        self.msgs.append(m)
        return m

    async def history(self, limit=100):
        for m in self.msgs[::-1][:limit]:
            yield m

    def posted(self, file):
        if file:
            self.events.append(("file", file.filename))
            if file.filename.endswith(".zip"):
                self.zips[file.filename] = zipfile.ZipFile(file.fp).namelist()

    async def send(self, content=None, embeds=None, file=None, files=None, delete_after=None, view=None,
                   allowed_mentions=None, reference=None):
        text = flat(content, embeds)
        self.sent.append((text, file.filename if file else None))
        self.shown.append(text)
        self.posted(file)
        if view is not None:
            self.view = view
        m = self.add(ME, content or "", ago=0, embeds=embeds or [])
        i, ch = len(self.sent) - 1, self
        m.view, m.channel, m.reply_to = view, self, reference

        async def edit(content=None, embeds=None, attachments=None, view=False):
            text = flat(content, embeds)
            ch.sent[i] = (text, attachments[0].filename if attachments else ch.sent[i][1])
            ch.shown.append(text)
            ch.posted(attachments[0] if attachments else None)
            m.content, m.embeds = content or "", embeds or []
            if view is not False:
                m.view = view
        m.edit = edit
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

    # Shadow test: never in dev mode; switched on here with the Decisions models faked (no network).
    shadow_log = TMP / "shadow" / "shadow.jsonl"
    check("no shadow test in dev mode", shadow_log.exists(), False)
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

    await part_check()



class Click:
    """A tap on a part-check card's button, or the ✏️ box sent: what the bot answered."""

    def __init__(self, card, user="Sam"):
        self.message, self.channel = card, card.channel
        self.user = NS(display_name=user, mention=f"<@{user}>")
        self.said, self.modal = [], None
        self.response = NS(send_message=self.say, send_modal=self.open, edit_message=card.edit)

    async def say(self, content=None, ephemeral=False):
        self.said.append(content)

    async def open(self, modal):
        self.modal = modal


def photo_msg(ch, *files, mid=None):
    m = ch.add(files=files, ago=2)
    m.id = mid or m.id
    m.guild, m.channel, m.type = True, ch, B.discord.MessageType.default
    m.to_reference = lambda **kw: "ref"
    return m


async def post(ch, *files):
    """A person posts photos; returns the bot's part-check cards for them, once they are done."""
    before = len(ch.msgs)
    await B.bot.on_message(photo_msg(ch, *files))
    await asyncio.gather(*B.CHECKING)
    return [m for m in ch.msgs[before:] if m.author is ME]


async def part_check():
    os.environ.update({"BEAR_SIM": "ok", "BEAR_SIM_PAUSE": "0.02"})
    txt = TMP / "checks" / "part-numbers.txt"
    ch = Channel(120)
    started = time.time()
    a, b = await post(ch, "IMG_7.jpg", "IMG_8.png")
    check("check: one reply per photo", [m.reply_to for m in (a, b)], ["ref", "ref"])
    check("check: reading shown first", any("Reading the part number" in t for t in ch.shown), True)
    check("check: answer shown", "# `82481-3Z000`" in flat(a.content, a.embeds) and "photo 1 of 2" in flat(a.content, a.embeds), True)
    check("check: buttons", [i.item.label for i in a.view.children], ["Correct", "82481-3Z0O0", "82481-3Z010", "Fix"])
    check("check: fast in dev mode", time.time() - started < 15, True)
    pid = ch.msgs[0].id
    check("check: photos kept", sorted(p.name for p in (TMP / "checks" / "photos" / "car-120-120").iterdir()),
          [f"{pid}-1.jpg", f"{pid}-2.png"])

    ok = Click(a)
    await a.view.children[0].callback(ok)
    check("check ✅: card green", "Checked by <@Sam>" in flat(a.content, a.embeds) and a.view is None, True)
    again = Click(a, "Alfie")
    await B.check_answer(again, "ok", None)
    check("check ✅ twice: told, not saved twice", (again.said, len(B.pc.read_lines(txt))),
          ([look.reply("check_answered")], 1))

    fix = Click(b)
    await b.view.children[-1].callback(fix)
    check("check ✏️: box filled with BEAR's read", fix.modal.number.default, "82481-3Z000")
    fix.modal.number._value = "nonsense; drop"
    await fix.modal.on_submit(fix)
    check("check ✏️: bad number refused", fix.said, [look.reply("check_bad_number")])
    fix.modal.number._value = " 82481 3z000x "
    await fix.modal.on_submit(fix)
    check("check ✏️: typed number saved", "# `82481 3Z000X`" in flat(b.content, b.embeds) and "Typed by" in flat(b.content, b.embeds), True)

    (c,) = await post(ch, "IMG_9.jpg")
    check("check: a single photo isn't numbered", "photo 1" in flat(c.content, c.embeds), False)
    await c.view.children[2].callback(Click(c))
    rows = B.pc.read_lines(txt)
    check("check: text file", [(r["part_number"], r["bear_read"], r["how"], r["who"]) for r in rows],
          [("82481-3Z000", "82481-3Z000", "correct", "Sam"), ("82481 3Z000X", "82481-3Z000", "typed", "Sam"),
           ("82481-3Z010", "82481-3Z000", "picked another reading", "Sam")])
    check("check: timings logged", all(float(r["wait_s"]) >= 0 and float(r["read_s"]) >= 0 for r in rows), True)
    check("check: links logged", rows[0]["photo"].startswith("https://discord.com/channels/"), True)
    check("check: nothing left waiting", list((TMP / "checks" / "pending").iterdir()), [])

    os.environ["BEAR_SIM"] = "no_number"
    (d,) = await post(ch, "IMG_10.jpg")
    check("check: no number", "No part number found" in flat(d.content, d.embeds)
          and [i.item.label for i in d.view.children] == ["Type it"], True)
    await d.view.children[0].callback(box := Click(d))
    check("check: nothing read, box empty", box.modal.number.default, None)

    os.environ["BEAR_SIM"] = "read_fails"
    errors = len(ERRORS.sent)
    (e,) = await post(ch, "IMG_11.jpg")
    await post(ch, "IMG_12.jpg")
    check("check: failure on the card", "Couldn't read this photo" in flat(e.content, e.embeds) and e.view is None, True)
    check("check: error channel told once", (len(ERRORS.sent) - errors, "`BEAR-C01`" in last_error()), (1, True))

    os.environ["BEAR_SIM"] = "ok"
    (h,) = await post(ch, "IMG_13.heic")
    check("check: HEIC", look.TITLES["BEAR-D05"] in flat(h.content, h.embeds), True)
    check("check: nothing in the error channel", await post(ERRORS, "IMG_14.jpg"), [])
    log_ch = Channel(121)
    log_ch.name = "update-log"
    check("check: nothing in update-log", await post(log_ch, "IMG_14.jpg"), [])
    os.environ["BEAR_PART_CHECK"] = "0"
    check("check: switched off", await post(ch, "IMG_15.jpg"), [])
    os.environ.pop("BEAR_PART_CHECK")

    # A folder whose photos got part checks but was never /run: still warned about on /newfolder.
    f = folder(124, parts=0)
    await post(f, "IMG_16.jpg")
    check("check cards aren't run cards", B.never_run(f.msgs[1:]), True)


asyncio.run(main())
if fails:
    print("\n".join(fails))
    sys.exit(f"{len(fails)} failed (run folders in {TMP})")
print(f"all Discord flow checks passed (run folders in {TMP})")
