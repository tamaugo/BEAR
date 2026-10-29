#!/usr/bin/env python3
"""Offline checks of #part-id (no Discord, no network, no credits). Needs discord.py (the server's
.venv has it). A photo posted in #part-id goes through the real bot and the real partid/agent1.py in
dev mode: the card with 3 options, the answer 1 until someone picks, the 1/2/3 buttons, ✏️ Type your
own (typed and blank), the buttons after a restart, Agent 1's ranking, and other channels, text,
HEIC and failures.

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
sys.path.insert(0, str(ROOT / "partid"))
import bot as B  # noqa: E402
import partid_bot as P  # noqa: E402
import agent1 as A  # noqa: E402
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
        r = NS(id=mid * 10 + len(replies), content=content, view=view)
        replies.append(r)
        return r
    return NS(id=mid, author=NS(bot=False), guild=NS(id=1), channel=channel, type=None,
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


def styles(view):
    return [b.style.name for b in view.children]


async def main():
    part_id, car = NS(id=5, name="part-id", category_id=None), NS(id=6, name="car-x", category_id=None)

    # A photo in #part-id: one card, 3 options most likely first, answer 1 until someone picks.
    m, replies = message(part_id, ["IMG_1.jpg"])
    await B.bot.on_message(m)
    check("one card", len(replies), 1)
    card_msg = replies[0]
    for i, text in enumerate(["97420-3Z000", "97420-3Z0O0", "39R293-1200"], 1):
        check(f"option {i}", f"**{i}** `{text}`" in card_msg.content, True)
    check("default answer", "Answer: **1** `97420-3Z000` (nobody has picked, so 1)" in card_msg.content, True)
    check("buttons", [b.custom_id for b in card_msg.view.children],
          ["partid:pick:1", "partid:pick:2", "partid:pick:3", "partid:type"])
    check("1 is green", styles(card_msg.view), ["success", "secondary", "secondary", "primary"])
    saved = json.loads((TMP / "part-id" / "cards" / f"{card_msg.id}.json").read_text())
    check("saved default", (saved["choice"], saved["answer"], saved["how"]), (1, "97420-3Z000", "default"))
    check("raw read kept", saved["read"]["raw"], A.SIM_RAW)

    # Pick 2, then 3: the last pick counts.
    i = Inter(card_msg)
    await button(card_msg.view, "partid:pick:2").callback(i)
    check("picked 2", "Answer: **2** `97420-3Z0O0`, picked by <@Sam>" in (i.edited or ""), True)
    check("2 is green", styles(card_msg.view), ["secondary", "success", "secondary", "primary"])
    i = Inter(card_msg, "Ali")
    await button(card_msg.view, "partid:pick:3").callback(i)
    saved = P.load(card_msg.id)
    check("picked 3", (saved["choice"], saved["answer"], saved["how"], saved["by_name"]),
          (3, "39R293-1200", "picked", "Ali"))

    # ✏️ Type your own: the box, a typed number, then a blank box goes back to 1.
    i = Inter(card_msg)
    await button(card_msg.view, "partid:type").callback(i)
    check("box opened", isinstance(i.modal, P.TypeBox), True)
    check("box hint is option 1", i.modal.number.placeholder, "97420-3Z000")
    i.modal.number._value = "  97420-3Z010  "
    await i.modal.on_submit(i)
    saved = P.load(card_msg.id)
    check("typed", (saved["choice"], saved["answer"], saved["how"]), ("typed", "97420-3Z010", "typed"))
    check("typed shown", "Answer: ✏️ `97420-3Z010`, typed by <@Sam>" in (i.edited or ""), True)
    check("type is green", styles(card_msg.view), ["secondary", "secondary", "secondary", "success"])
    i = Inter(card_msg)
    await button(card_msg.view, "partid:type").callback(i)
    i.modal.number._value = "   "
    await i.modal.on_submit(i)
    saved = P.load(card_msg.id)
    check("blank = 1", (saved["choice"], saved["answer"], saved["how"]), (1, "97420-3Z000", "default"))

    # After a restart: the registered Buttons() find the card by its message id.
    i = Inter(NS(id=card_msg.id, content=None, view=None))
    await button(P.Buttons(), "partid:pick:2").callback(i)
    check("after restart", P.load(card_msg.id)["choice"], 2)
    i = Inter(NS(id=12345, content=None, view=None))
    await button(P.Buttons(), "partid:pick:1").callback(i)
    check("unknown card", i.private, "This card isn't saved any more.")

    # No number found: only ✏️, no answer yet.
    empty = {"card": 1, "photo_name": "x.jpg", "options": [], "choice": None, "answer": None, "how": "default"}
    check("no number text", "Agent 1 found no part number" in P.card_text(empty) and "Answer: none yet" in P.card_text(empty), True)
    check("no number buttons", [b.custom_id for b in P.Buttons(empty).children], ["partid:type"])

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
    real, P.AGENT1 = P.AGENT1, TMP / "missing.py"
    m, replies = message(part_id, ["y.jpg"], 504)
    await B.bot.on_message(m)
    check("failure replied", "failed, send the photo again" in (replies[0].content if replies else ""), True)
    P.AGENT1 = real

    # Agent 1's ranking: primary before unclear before secondary, clear first, each with its other
    # readings, the same number once, at most 3; broken JSON gives none.
    raw = json.dumps({"candidates": [
        {"text": "SEC 1", "role": "secondary", "legibility": "clear"},
        {"text": "PRI-2", "role": "primary", "legibility": "poor", "alt_readings": ["PRI 2", "PRL-2"]},
        {"text": "PRI-1", "role": "primary", "legibility": "clear", "alt_readings": ["PRI-I"]}]})
    check("ranking", A.options(raw), ["PRI-1", "PRI-I", "PRI-2"])
    check("broken JSON", A.options('{"candidates": [{"text": "A'), [])
    check("no candidates", A.options('{"candidates": []}'), [])

asyncio.run(main())
if fails:
    print("FAIL\n  " + "\n  ".join(fails))
    sys.exit(1)
print("part-id offline checks: all passed")
