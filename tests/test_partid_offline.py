#!/usr/bin/env python3
"""Offline checks of #part-id (no Discord, no network, no credits). Needs discord.py (the server's
.venv has it). A photo posted in #part-id goes through the real bot and the real partid/agent1.py in
dev mode: the card with Jev's top 3 and their scores, the answer 1 until someone picks, the 1/2/3 buttons, ✏️ Type your
own (typed and blank), 🚫 No part number and its eBay photo search (on the card and in /sheet), the
buttons after a restart, Agent 1's ranking, and other channels, text, HEIC and failures. Then Jev doing the scoring (its order, not Agent 1's; a
Jev failure fails the read) with the Decisions call faked.

usage: .venv/bin/python tests/test_partid_offline.py
"""
import asyncio, json, logging, os, sys, tempfile
from datetime import datetime, timezone
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
sys.path.insert(0, str(ROOT / "partid"))
import bot as B  # noqa: E402
import partid_bot as P  # noqa: E402
import agent1 as A  # noqa: E402
import jev as J  # noqa: E402
import part_id as R  # noqa: E402
import photo_search as S  # noqa: E402
from PIL import Image  # noqa: E402

logging.disable(logging.CRITICAL)
P.setup(TMP)
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

    async def reply(content=None, file=None, view=None, mention_author=True):
        r = NS(id=mid * 10 + len(replies), content=content, view=view, edits=0)

        async def edit(content=None, view=None):
            r.content, r.view, r.edits = content, view, r.edits + 1
        r.edit = edit
        replies.append(r)
        return r
    return NS(id=mid, author=NS(bot=False), guild=NS(id=1), channel=channel, type=None, created_at=datetime.now(timezone.utc),
              jump_url=f"https://discord.com/channels/1/5/{mid}", attachments=[Att(f) for f in files],
              reply=reply), replies


class User:
    def __init__(self, name):
        self.name, self.mention = name, f"<@{name}>"

    def __str__(self):
        return self.name


class Inter:
    """A click on a card (message = the card's reply). Records the edit, modal or private reply."""

    def __init__(self, card_msg, user="Sam"):
        self.message, self.user = card_msg, User(user)
        self.edited, self.modal, self.private = None, None, None
        self.response = NS(edit_message=self.edit, send_modal=self.send_modal, send_message=self.send_message)

    async def edit(self, content=None, view=None):
        self.edited = content
        self.message.content, self.message.view = content, view

    async def send_modal(self, modal):
        self.modal = modal

    async def send_message(self, content=None, ephemeral=False):
        self.private = content


def button(view, custom_id):
    return next((b for b in view.children if b.custom_id == custom_id), None)


LOC = ["partid:loc:nsr", "partid:loc:nsf", "partid:loc:osr", "partid:loc:osf"]   # the 4 location buttons, row 2


def styles(view):
    """The number buttons' colours (the location buttons are checked on their own)."""
    return [b.style.name for b in view.children if not b.custom_id.startswith("partid:loc:")]


async def main():
    part_id, car = NS(id=5, name="part-id", category_id=None), NS(id=6, name="car-x", category_id=None)

    # A photo in #part-id: one card, 3 options most likely first, answer 1 until someone picks.
    m, replies = message(part_id, ["IMG_1.jpg"])
    await B.bot.on_message(m)
    check("one card", len(replies), 1)
    card_msg = replies[0]
    # dev mode's made-up Jev scores reverse Agent 1's order, so this order can only be Jev's
    for i, (text, pc) in enumerate([("39R293-1200", 46), ("97420-3Z0O0", 31), ("97420-3Z000", 23)], 1):
        check(f"option {i}", f"**{i}** `{text}` · {pc}%" in card_msg.content, True)
    check("says Jev", "scored by Jev" in card_msg.content, True)
    check("default answer", "Answer: **1** `39R293-1200` (nobody has picked, so 1)" in card_msg.content, True)
    check("buttons", [b.custom_id for b in card_msg.view.children],
          ["partid:pick:1", "partid:pick:2", "partid:pick:3", "partid:type", "partid:none", *LOC])
    check("1 is green", styles(card_msg.view), ["success", "secondary", "secondary", "primary", "secondary"])
    saved = json.loads((TMP / "part-id" / "cards" / f"{card_msg.id}.json").read_text())
    check("saved default", (saved["choice"], saved["answer"], saved["how"]), (1, "39R293-1200", "default"))
    check("raw read kept", saved["read"]["agent1"]["raw"], A.SIM_RAW)
    check("Jev's scores kept", saved["read"]["jev"]["method"], "jev (dev mode)")

    # Pick 2, then 3: the last pick counts.
    i = Inter(card_msg)
    await button(card_msg.view, "partid:pick:2").callback(i)
    check("picked 2", "Answer: **2** `97420-3Z0O0`, picked by <@Sam>" in (i.edited or ""), True)
    check("2 is green", styles(card_msg.view), ["secondary", "success", "secondary", "primary", "secondary"])
    i = Inter(card_msg, "Ali")
    await button(card_msg.view, "partid:pick:3").callback(i)
    saved = P.load(card_msg.id)
    check("picked 3", (saved["choice"], saved["answer"], saved["how"], saved["by_name"]),
          (3, "97420-3Z000", "picked", "Ali"))

    # ✏️ Type your own: the box, a typed number, then a blank box goes back to 1.
    i = Inter(card_msg)
    await button(card_msg.view, "partid:type").callback(i)
    check("box opened", isinstance(i.modal, P.TypeBox), True)
    check("box hint is option 1", i.modal.number.placeholder, "39R293-1200")
    i.modal.number._value = "  97420-3Z010  "
    await i.modal.on_submit(i)
    saved = P.load(card_msg.id)
    check("typed", (saved["choice"], saved["answer"], saved["how"]), ("typed", "97420-3Z010", "typed"))
    check("typed shown", "Answer: ✏️ `97420-3Z010`, typed by <@Sam>" in (i.edited or ""), True)
    check("type is green", styles(card_msg.view), ["secondary", "secondary", "secondary", "success", "secondary"])
    i = Inter(card_msg)
    await button(card_msg.view, "partid:type").callback(i)
    i.modal.number._value = "   "
    await i.modal.on_submit(i)
    saved = P.load(card_msg.id)
    check("blank = 1", (saved["choice"], saved["answer"], saved["how"]), (1, "39R293-1200", "default"))

    # After a restart: the registered Buttons() find the card by its message id.
    i = Inter(NS(id=card_msg.id, content=None, view=None))
    await button(P.Buttons(), "partid:pick:2").callback(i)
    check("after restart", P.load(card_msg.id)["choice"], 2)
    i = Inter(NS(id=12345, content=None, view=None))
    await button(P.Buttons(), "partid:pick:1").callback(i)
    check("unknown card", i.private, "This card isn't saved any more.")

    # 🚫 No part number: the answer, then eBay's photo search on the same photo, shown on the card.
    i = Inter(card_msg, "Jo")
    await button(card_msg.view, "partid:none").callback(i)
    saved = P.load(card_msg.id)
    check("no number saved", (saved["choice"], saved["answer"], saved["how"], saved["by_name"]), ("none", None, "none", "Jo"))
    check("no number shown", "Answer: 🚫 **No part number**, marked by <@Jo>" in (i.edited or ""), True)
    check("search shown as looking first", "eBay photo search: looking…" in (i.edited or ""), True)
    check("photo searched", [m["title"] for m in saved["matches"]], [m["title"] for m in S.SIM])
    check("card redrawn with the look-alikes", ("`1` [(dev mode) made-up look-alike listing 1](<https://www.ebay.co.uk/itm/100000000001>)"
                                               " · listed £14.99") in card_msg.content, True)
    check("no number is green", styles(card_msg.view), ["secondary", "secondary", "secondary", "primary", "success"])
    # 🚫 again: back to option 1, and the look-alikes are kept (not searched twice)
    i = Inter(card_msg)
    await button(card_msg.view, "partid:none").callback(i)
    saved = P.load(card_msg.id)
    check("🚫 again = 1", (saved["choice"], saved["answer"], saved["how"]), (1, "39R293-1200", "default"))
    check("look-alikes not on a numbered card", "eBay photo search" in (i.edited or ""), False)
    searched, P.SEARCH = P.SEARCH, TMP / "must-not-run.py"
    await button(card_msg.view, "partid:none").callback(Inter(card_msg))
    check("searched once per card", P.load(card_msg.id)["matches_error"], None)
    P.SEARCH = searched
    await button(card_msg.view, "partid:pick:2").callback(Inter(card_msg))
    check("a pick replaces no number", P.load(card_msg.id)["how"], "picked")

    # Agent 1 finds no number: the card starts as no part number and is searched by its photo at once.
    fake = TMP / "no_number_read.py"
    fake.write_text('import json; print(json.dumps({"options": [], "readings": [], "cost": 0}))')
    real, P.RUN = P.RUN, fake
    m, replies = message(part_id, ["blank.jpg"], 505)
    await B.bot.on_message(m)
    P.RUN = real
    blank = P.load(replies[0].id)
    check("none found = no part number", (blank["choice"], blank["answer"], blank["how"], blank["by"]), ("none", None, "none", None))
    check("none found shown", "Answer: 🚫 **No part number** (Agent 1 found none)" in replies[0].content, True)
    check("none found searched at once", (len(blank["matches"]), replies[0].edits), (3, 1))
    check("none found buttons", [b.custom_id for b in replies[0].view.children][:2], ["partid:type", "partid:none"])
    i = Inter(replies[0])
    await button(replies[0].view, "partid:type").callback(i)
    i.modal.number._value = ""
    await i.modal.on_submit(i)
    check("blank box with no options = no part number", P.load(replies[0].id)["how"], "none")

    # The photo search failing says so on the card; /sheet tries it again before the spreadsheet.
    searched, P.SEARCH, P.RUN = P.SEARCH, TMP / "missing-search.py", fake
    m, replies = message(part_id, ["shiny.jpg"], 506)
    await B.bot.on_message(m)
    P.RUN = real
    shiny = replies[0]
    failed = P.load(shiny.id)
    check("search failed kept", (failed["matches"], bool(failed["matches_error"])), (None, True))
    check("search failed shown", "eBay photo search: failed, tried again at /sheet" in shiny.content, True)
    P.SEARCH = searched

    # No number found: only ✏️, no answer yet.
    empty = {"card": 1, "photo_name": "x.jpg", "options": [], "choice": None, "answer": None, "how": "default"}
    check("no number text", "Agent 1 found no part number" in P.card_text(empty) and "Answer: none yet" in P.card_text(empty), True)
    check("no number buttons", [b.custom_id for b in P.Buttons(empty).children], ["partid:type", "partid:none", *LOC])

    # Two photos and a HEIC in one message: a card each, and HEIC is refused.
    m, replies = message(part_id, ["a.jpg", "b.png", "c.heic", "notes.pdf"], 501)
    await B.bot.on_message(m)
    check("two cards + HEIC note", len(replies), 3)
    check("HEIC refused", any("Can't read c.heic" in (r.content or "") for r in replies), True)

    # Other channels and text-only messages are not read; PART_ID_CHANNEL_ID wins over the name.
    m, replies = message(car, ["x.jpg"], 502)
    await B.bot.on_message(m)
    check("other channel ignored", replies, [])
    m, replies = message(part_id, [], 503)
    await B.bot.on_message(m)
    check("text ignored", replies, [])
    check("by id", P.is_partid(car, 6), True)
    check("by id, name not enough", P.is_partid(part_id, 6), False)

    # A failed read says so.
    real, P.RUN = P.RUN, TMP / "missing.py"
    m, replies = message(part_id, ["y.jpg"], 504)
    await B.bot.on_message(m)
    check("failure replied", "failed, send the photo again" in (replies[0].content if replies else ""), True)
    P.RUN = real

    # Agent 1 only lists: every reading in its own order, each other reading tied to its number.
    raw = json.dumps({"part_description": "door mirror", "candidates": [
        {"text": "SEC 1", "role": "secondary", "legibility": "clear"},
        {"text": "PRI-2", "role": "primary", "legibility": "poor", "alt_readings": ["PRI 2", "PRL-2"]},
        "junk", {"text": "  "}]})
    found = A.readings(raw)
    check("readings", [(r["text"], r["alt_of"]) for r in found],
          [("SEC 1", None), ("PRI-2", None), ("PRL-2", "PRI-2")])
    check("broken JSON", A.readings('{"candidates": [{"text": "A'), [])

    # Jev does the scoring: one choice call over every reading, and its probabilities set the order.
    os.environ.pop("BEAR_SIM")
    calls = []

    def fake_jev(state, questions, tag=""):
        calls.append((state, questions))
        return {"answers": {"number": {"type": "choice", "choice": "R3", "confidence": 0.7,
                                       "probabilities": {"R1": 0.05, "R2": 0.25, "R3": 0.7}}},
                "usage": {"cost": 0.00003}}
    J.c.jev = fake_jev
    R.agent1.read = lambda path, vehicle: {"model": "m", "seconds": 1, "cost": 0.0005, "raw": raw}
    out = R.run("x.jpg")
    check("one Jev call", len(calls), 1)
    check("Jev sees every reading", [r["reading"] for r in calls[0][0]["readings"].values()], ["SEC 1", "PRI-2", "PRL-2"])
    check("Jev sees the part", calls[0][0]["part_in_photo"], "door mirror")
    check("a choice question", (calls[0][1]["number"]["type"], list(calls[0][1]["number"]["criteria"])),
          ("choice", ["R1", "R2", "R3"]))
    check("Jev's order", [(o["text"], o["score"]) for o in out["options"]], [("PRL-2", 0.7), ("PRI-2", 0.25), ("SEC 1", 0.05)])
    check("cost adds up", round(out["cost"], 5), 0.00053)

    # Jev failing fails the read: never Agent 1's order instead.
    def broken_jev(state, questions, tag=""):
        raise RuntimeError("Decisions API returned 503")
    J.c.jev = broken_jev
    try:
        R.run("x.jpg")
        fails.append("Jev failing: no error")
    except RuntimeError as e:
        check("Jev failing", str(e), "Decisions API returned 503")
    J.c.jev = lambda state, questions, tag="": {"answers": {"number": {"type": "choice", "choice": "R1"}},
                                                "usage": {"cost": 0}}
    try:
        R.run("x.jpg")
        fails.append("Jev without scores: no error")
    except RuntimeError as e:
        check("Jev without scores", str(e).startswith("Jev gave no scores"), True)

    # One reading: nothing to score, no Jev call. None: no options.
    calls.clear()
    J.c.jev = fake_jev
    R.agent1.read = lambda path, vehicle: {"model": "m", "seconds": 1, "cost": 0, "raw": '{"candidates": [{"text": "ONLY-1"}]}'}
    check("one reading", [o["text"] for o in R.run("x.jpg")["options"]], ["ONLY-1"])
    check("one reading, no call", calls, [])
    R.agent1.read = lambda path, vehicle: {"model": "m", "seconds": 1, "cost": 0, "raw": '{"candidates": []}'}
    check("no readings", R.run("x.jpg")["options"], [])

    # More than 3 readings: Jev scores them all, the top 3 are shown.
    R.agent1.read = lambda path, vehicle: {"model": "m", "seconds": 1, "cost": 0, "raw": json.dumps(
        {"candidates": [{"text": f"NUM-{k}"} for k in range(1, 6)]})}
    J.c.jev = lambda state, questions, tag="": {"answers": {"number": {"type": "choice", "probabilities": {
        "R1": 0.1, "R2": 0.05, "R3": 0.4, "R4": 0.15, "R5": 0.3}}}, "usage": {"cost": 0}}
    check("top 3 of 5", [o["text"] for o in R.run("x.jpg")["options"]], ["NUM-3", "NUM-5", "NUM-4"])

    os.environ["BEAR_SIM"] = "ok"   # dev mode again: the retried photo search is made up
    # /sheet: deferred (photo searches take time), the failed search is retried, and the spreadsheet has
    # each no-number part with its look-alikes under it.
    sent = {}

    async def defer(thinking=False):
        sent["deferred"] = thinking

    async def followup(content=None, file=None):
        sent["content"], sent["file"] = content, file
    i = NS(user=User("Sam"), response=NS(defer=defer), followup=NS(send=followup))
    await P.sheet(i)
    check("sheet deferred", sent.get("deferred"), True)
    check("sheet says parts", (sent.get("content") or "").startswith("**Sheet** · "), True)
    check("failed search retried", len(P.load(shiny.id)["matches"]), 3)
    import zipfile, io
    with zipfile.ZipFile(io.BytesIO(sent["file"].fp.read())) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    check("sheet has no-number rows", sheet.count("NO PART NUMBER"), 2)
    check("sheet has look-alike rows", sheet.count("POSSIBLE MATCH"), 6)
    check("sheet links the photos", 'HYPERLINK("https://discord.com/channels/1/5/505","blank.jpg")' in sheet, True)
    check("all marked", all(P.load(c)["sheet"] for c in (shiny.id, blank["card"], card_msg.id)), True)

asyncio.run(main())
if fails:
    print("FAIL\n  " + "\n  ".join(fails))
    sys.exit(1)
print("part-id offline checks: all passed")
