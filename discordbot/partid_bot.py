"""#part-id, a framework for now: someone posts a part-number photo and the bot runs partid/part_id.py on it:
Agent 1 (Gemini) reads every possible part number and reading, Jev scores them, and the reply has the
top 3 by Jev's score, most likely first, each with its score. The order is Jev's, never Gemini's
(owner, 2026-10-29). Buttons 1, 2, 3 pick
one; ✏️ Type your own opens a box for a correction. Until someone picks or types, the answer is 1, the
most likely (owner, 2026-10-29). A second row of buttons gives the location (near side rear, near side
front, off side rear, off side front); none picked = blank, clicking the picked one again clears it.
Answers can be changed; the last one counts. Kept apart from /run
while the new pipeline is decided: no folders, nothing in bear2/ changes.

🚫 No part number is for a part with no number on it (owner, 2026-11-13): the answer becomes "no part
number" and the photo itself goes to eBay's search-by-image (partid/photo_search.py, free). The top 3
look-alike listings go on the card and, as shaded rows under the part, in the /sheet spreadsheet, so a
part without a number is never a blank row. A photo Agent 1 finds no number on starts as no part number
on its own. Clicking 🚫 again goes back to option 1; picking 1-3 or typing a number replaces it.

Each photo's card is kept in <storage>/part-id/cards/<reply message id>.json: the photo, the options,
the answer (choice 1-3 or "typed", how: default / picked / typed, by whom, when), the location, when the
photo was posted, and the whole read (Agent 1's raw answer, every reading, Jev's scores).
/sheet in #part-id posts every card since the last /sheet as a spreadsheet (partid_sheet.py), first
posted at the top, and marks them with that sheet's name so the next /sheet starts after them; a copy
of each sheet stays in <storage>/part-id/sheets/. The photos are in <storage>/part-id/, the
spend in <storage>/part-id/spend.jsonl, apart from the runs. Text messages are left alone.

The channel is PART_ID_CHANNEL_ID, or else the channel named part-id (setup_server.py makes it).
How a card looks is card_text() and Buttons below. The buttons keep working after a restart: the bot
registers Buttons() once (bot.py setup_hook) and each click finds its card file by the message id.
"""
import asyncio, io, json, logging, os, signal, sys, time
from datetime import datetime
from pathlib import Path, PurePath

import discord
import folders as fo
import partid_sheet
from renames import is_image

log = logging.getLogger("bear-bot")
RUN = Path(__file__).resolve().parent.parent / "partid" / "part_id.py"
SEARCH = Path(__file__).resolve().parent.parent / "partid" / "photo_search.py"
CHANNEL = "part-id"
HOW_MANY = 3                   # options shown (partid/part_id.py HOW_MANY)
READS = asyncio.Semaphore(4)   # photos read at once
SEARCHES = asyncio.Semaphore(2)   # eBay photo searches at once
SEARCHING = set()              # cards whose photo search is running now
TIMEOUT = 180                  # seconds before a read or a photo search is stopped
LOCATIONS = {"nsr": "near side rear", "nsf": "near side front", "osr": "off side rear", "osf": "off side front"}
SHEETING = asyncio.Lock()      # one /sheet at a time
FOLDER = Path("part-id")       # set by setup()
ENV = lambda: dict(os.environ)   # noqa: E731  the photo search's environment (bot.py: run_env)


def setup(storage, env=None):
    global FOLDER, ENV
    FOLDER = Path(storage) / "part-id"
    if env:
        ENV = env


def is_partid(channel, channel_id):
    """channel_id: PART_ID_CHANNEL_ID (None: find the channel by its name)."""
    return channel.id == channel_id if channel_id else getattr(channel, "name", None) == CHANNEL


# --- The card ------------------------------------------------------------------------------------

def card_text(card):
    lines = [f"**Part number** · `{card['photo_name']}` · scored by Jev"]
    for i, o in enumerate(card["options"], 1):
        lines.append(f"**{i}** `{o['text']}` · {o['score']:.0%}" + ("  ← most likely" if i == 1 else ""))
    if not card["options"]:
        lines.append("Agent 1 found no part number. If there is one, type it with ✏️.")
    lines.append("")
    if card.get("how") == "none":
        lines.append(f"Answer: 🚫 **No part number**, marked by {card['by']}" if card.get("by")
                     else "Answer: 🚫 **No part number** (Agent 1 found none)")
        lines += matches_text(card)
    elif card["answer"] is None:
        lines.append("Answer: none yet")
    elif card["how"] == "default":
        lines.append(f"Answer: **1** `{card['answer']}` (nobody has picked, so 1)")
    elif card["how"] == "picked":
        lines.append(f"Answer: **{card['choice']}** `{card['answer']}`, picked by {card['by']}")
    else:
        lines.append(f"Answer: ✏️ `{card['answer']}`, typed by {card['by']}")
    if card.get("location"):
        lines.append(f"Location: **{card['location']}**, picked by {card['location_by']}")
    else:
        lines.append("Location: none yet")
    return "\n".join(lines)


def matches_text(card):
    """The eBay photo search's look-alikes under a no-part-number answer."""
    found = card.get("matches")
    if found is None:
        return ["eBay photo search: failed, tried again at /sheet" if card.get("matches_error")
                else "eBay photo search: looking…"]
    if not found:
        return ["eBay photo search: nothing similar found"]
    lines = ["eBay photo search, look-alikes to check by eye:"]
    for k, m in enumerate(found, 1):
        title = discord.utils.escape_markdown(" ".join(str(m.get("title") or "listing").split())[:80])
        title = title.replace("[", "(").replace("]", ")")
        lines.append(f"`{k}` [{title}](<{m['url']}>) · listed £{float(m.get('price') or 0):.2f}")
    return lines


class Buttons(discord.ui.View):
    """1, 2, 3 (as many as there are options), ✏️ Type your own and 🚫 No part number; the current answer's
    button is green.
    Under them the four locations, the picked one green.
    Buttons() with no card has all of them, for registering after a restart."""

    def __init__(self, card=None):
        super().__init__(timeout=None)
        count = len(card["options"]) if card else HOW_MANY
        chosen = card and card["choice"]
        for i in range(1, count + 1):
            self.add_item(Pick(i, chosen == i))
        self.add_item(TypeOwn(chosen == "typed"))
        self.add_item(NoNumber(chosen == "none"))
        for key, name in LOCATIONS.items():
            self.add_item(Location(key, name, bool(card) and card.get("location") == name))


class Pick(discord.ui.Button):
    def __init__(self, i, chosen):
        super().__init__(label=str(i), custom_id=f"partid:pick:{i}", row=0,
                         style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.secondary)
        self.i = i

    async def callback(self, inter):
        card = load(inter.message.id)
        if card is None or self.i > len(card["options"]):
            return await inter.response.send_message("This card isn't saved any more.", ephemeral=True)
        answer(card, self.i, card["options"][self.i - 1]["text"], "picked", inter.user)
        await inter.response.edit_message(content=card_text(card), view=Buttons(card))


class TypeOwn(discord.ui.Button):
    def __init__(self, chosen):
        super().__init__(label="Type your own", emoji="\N{PENCIL}\N{VARIATION SELECTOR-16}", custom_id="partid:type", row=0,
                         style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.primary)

    async def callback(self, inter):
        card = load(inter.message.id)
        if card is None:
            return await inter.response.send_message("This card isn't saved any more.", ephemeral=True)
        await inter.response.send_modal(TypeBox(card))


class TypeBox(discord.ui.Modal, title="Type the part number"):
    number = discord.ui.TextInput(label="Part number (leave blank for option 1)", required=False, max_length=60)

    def __init__(self, card):
        super().__init__()
        self.card_id = card["card"]
        if card["options"]:
            self.number.placeholder = card["options"][0]["text"]

    async def on_submit(self, inter):
        card = load(self.card_id)
        if card is None:
            return await inter.response.send_message("This card isn't saved any more.", ephemeral=True)
        typed = self.number.value.strip()
        if typed:
            answer(card, "typed", typed, "typed", inter.user)
        else:   # blank: back to the most likely (none found: back to no part number)
            default(card)
        await inter.response.edit_message(content=card_text(card), view=Buttons(card))
        if card["how"] == "none":
            await find_matches(card["card"], inter.message)


class NoNumber(discord.ui.Button):
    def __init__(self, chosen):
        super().__init__(label="No part number", emoji="\N{NO ENTRY SIGN}", custom_id="partid:none", row=0,
                         style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.secondary)

    async def callback(self, inter):
        card = load(inter.message.id)
        if card is None:
            return await inter.response.send_message("This card isn't saved any more.", ephemeral=True)
        if card.get("how") == "none" and card["options"]:   # 🚫 again: back to the most likely
            default(card)
        else:
            answer(card, "none", None, "none", inter.user)
        await inter.response.edit_message(content=card_text(card), view=Buttons(card))
        if card["how"] == "none":
            await find_matches(card["card"], inter.message)


class Location(discord.ui.Button):
    def __init__(self, key, name, chosen):
        super().__init__(label=name.capitalize(), custom_id=f"partid:loc:{key}", row=1,
                         style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.secondary)
        self.place = name

    async def callback(self, inter):
        card = load(inter.message.id)
        if card is None:
            return await inter.response.send_message("This card isn't saved any more.", ephemeral=True)
        if card.get("location") == self.place:   # the picked one again: back to none
            card.update(location=None, location_by=None)
        else:
            card.update(location=self.place, location_by=inter.user.mention)
        save(card)
        await inter.response.edit_message(content=card_text(card), view=Buttons(card))


def default(card):
    """Nobody's answer: option 1, or no part number if Agent 1 found none."""
    if card["options"]:
        answer(card, 1, card["options"][0]["text"], "default", None)
    else:
        answer(card, "none", None, "none", None)


def answer(card, choice, text, how, user):
    card.update(choice=choice, answer=text, how=how, by=getattr(user, "mention", None),
                by_name=str(user) if user else None, at=time.time())
    save(card)


def card_path(card_id):
    return FOLDER / "cards" / f"{card_id}.json"


def load(card_id):
    try:
        return json.loads(card_path(card_id).read_text())
    except (OSError, ValueError):
        return None


def save(card):
    path = card_path(card["card"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(card, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


# --- Reading a photo -----------------------------------------------------------------------------

async def handle(msg, env):
    """Read every photo on msg, each replied to with its own card as soon as it is done."""
    photos = [a for a in msg.attachments if fo.is_photo(a)]
    unreadable = [a.filename for a in msg.attachments if is_image(a) and not fo.is_photo(a)]
    if unreadable:
        await safe(msg.reply(f"Can't read {', '.join(unreadable)}: send it as JPG, PNG or WEBP.",
                             mention_author=False))
    await asyncio.gather(*(one(msg, att, n, env) for n, att in enumerate(photos, 1)))


async def one(msg, att, n, env):
    FOLDER.mkdir(parents=True, exist_ok=True)
    path = FOLDER / f"{msg.id}-{n}{PurePath(att.filename).suffix.lower()}"
    try:
        await att.save(path)
        async with READS:
            out = await script(RUN, path, {**env, "BEAR_SPEND_LEDGER": str(FOLDER / "spend.jsonl")})
        options = out["options"][:HOW_MANY]
        card = {"card": None, "photo": str(path), "photo_name": att.filename, "message": msg.jump_url,
                "posted": msg.created_at.timestamp(), "location": None, "location_by": None,
                "options": options, "choice": 1 if options else "none", "answer": options[0]["text"] if options else None,
                "how": "default" if options else "none", "by": None, "by_name": None, "at": time.time(),
                "matches": None, "matches_error": None, "read": out}
        reply = await msg.reply(card_text(card), view=Buttons(card), mention_author=False)
        card["card"] = reply.id
        save(card)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("part-id read failed for %s: %s", att.filename, e)
        await safe(msg.reply(f"**Part number** · `{att.filename}` failed, send the photo again:\n"
                             f"```\n{str(e)[-1500:]}\n```", mention_author=False))
        return
    if card["how"] == "none":   # no number found: look for the part by its photo straight away
        await find_matches(card["card"], reply, env)


async def find_matches(card_id, message, env=None):
    """eBay photo search for a card marked no part number: once per card (a failed search is tried again
    later). The look-alikes are saved on the card and the card's message (if given) is redrawn."""
    card = load(card_id)
    if card is None or card.get("matches") is not None or card_id in SEARCHING:
        return
    SEARCHING.add(card_id)
    try:
        try:
            async with SEARCHES:
                found, error = (await script(SEARCH, card["photo"], env or ENV()))["matches"], None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("part-id photo search failed for %s: %s", card.get("photo_name"), e)
            found, error = None, str(e)[-300:]
        card = load(card_id) or card   # the answer may have changed while eBay was searched
        card.update(matches=found, matches_error=error, matches_at=time.time())
        save(card)
    finally:
        SEARCHING.discard(card_id)
    if message is not None and card.get("how") == "none":
        await safe(message.edit(content=card_text(card), view=Buttons(card)))


async def script(run, path, env):
    """partid/part_id.py (or photo_search.py) on one photo as its own process (so it can always be
    stopped): its JSON."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(run), str(path), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env, start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        if isinstance(e, asyncio.CancelledError):
            raise
        raise RuntimeError(f"no answer after {TIMEOUT} s, stopped") from None
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="replace").strip() or f"exit code {proc.returncode}")
    return json.loads(out)


async def safe(post):
    try:
        return await post
    except Exception:
        log.exception("can't reply in #part-id")


# --- /sheet --------------------------------------------------------------------------------------

def posted(card):
    """When the card's photo was posted, and its place on the message: the sheet's order. Cards from
    before "posted" was kept get it from the message id."""
    msg_id, _, n = PurePath(card["photo"]).stem.partition("-")
    when = card.get("posted") or discord.utils.snowflake_time(int(msg_id)).timestamp()
    return when, int(n or 1)


def new_cards():
    """Every saved card no /sheet has had yet, first posted first."""
    cards = []
    for path in (FOLDER / "cards").glob("*.json"):
        try:
            card = json.loads(path.read_text())
        except (OSError, ValueError):
            log.warning("part-id card %s can't be read, left out of the sheet", path.name)
            continue
        if card.get("card") and not card.get("sheet"):
            cards.append(card)
    cards.sort(key=posted)
    for card in cards:
        card["posted"] = posted(card)[0]
    return cards


async def sheet(inter):
    """/sheet: every card since the last /sheet, as a spreadsheet posted in the channel."""
    async with SHEETING:
        cards = await asyncio.to_thread(new_cards)
        if not cards:
            return await inter.response.send_message("No new part numbers since the last sheet.", ephemeral=True)
        await inter.response.defer(thinking=True)   # photo searches can take longer than Discord's 3 s
        unsearched = [c for c in cards if c.get("how") == "none" and c.get("matches") is None]
        await asyncio.gather(*(find_matches(c["card"], None) for c in unsearched))
        for c in unsearched:
            c.update({k: (load(c["card"]) or c).get(k) for k in ("matches", "matches_error")})
        name = f"part-id-{datetime.now(partid_sheet.UK).strftime('%Y-%m-%d-%H%M%S')}.xlsx"
        data = await asyncio.to_thread(partid_sheet.xlsx, cards)
        sheets = FOLDER / "sheets"
        sheets.mkdir(parents=True, exist_ok=True)
        (sheets / name).write_bytes(data)
        await inter.followup.send(
            f"**Sheet** · {len(cards)} part{'s' if len(cards) != 1 else ''}, by {inter.user.mention}",
            file=discord.File(io.BytesIO(data), filename=name))
        for card in cards:   # only once it is posted, so a failed post leaves them for the next /sheet
            fresh = load(card["card"]) or card
            fresh.update(sheet=name, posted=card["posted"])
            save(fresh)
        log.info("/sheet %s: %d cards, by %s", name, len(cards), inter.user)
