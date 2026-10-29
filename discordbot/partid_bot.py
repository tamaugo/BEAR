"""#part-id, a framework for now: someone posts a part-number photo, the bot runs #part-id's own Agent 1
on it (partid/agent1.py) and replies with up to 3 part numbers, most likely first. Buttons 1, 2, 3 pick
one; ✏️ Type your own opens a box for a correction. Until someone picks or types, the answer is 1, the
most likely (owner, 2026-10-29). Answers can be changed; the last one counts. Kept apart from /run
while the new pipeline is decided: no folders, nothing in bear2/ changes.

Each photo's card is kept in <storage>/part-id/cards/<reply message id>.json: the photo, the options,
the answer (choice 1-3 or "typed", how: default / picked / typed, by whom, when) and Agent 1's raw read.
Those files are what a later step turns into a spreadsheet. The photos are in <storage>/part-id/, the
spend in <storage>/part-id/spend.jsonl, apart from the runs. Text messages are left alone.

The channel is PART_ID_CHANNEL_ID, or else the channel named part-id (setup_server.py makes it).
How a card looks is card_text() and Buttons below. The buttons keep working after a restart: the bot
registers Buttons() once (bot.py setup_hook) and each click finds its card file by the message id.
"""
import asyncio, json, logging, os, signal, sys, time
from pathlib import Path, PurePath

import discord
import folders as fo
from renames import is_image

log = logging.getLogger("bear-bot")
AGENT1 = Path(__file__).resolve().parent.parent / "partid" / "agent1.py"
CHANNEL = "part-id"
HOW_MANY = 3                   # options shown (partid/agent1.py HOW_MANY)
READS = asyncio.Semaphore(4)   # photos read at once
TIMEOUT = 180                  # seconds before a read is stopped
FOLDER = Path("part-id")       # set by setup()


def setup(storage):
    global FOLDER
    FOLDER = Path(storage) / "part-id"


def is_partid(channel, channel_id):
    """channel_id: PART_ID_CHANNEL_ID (None: find the channel by its name)."""
    return channel.id == channel_id if channel_id else getattr(channel, "name", None) == CHANNEL


# --- The card ------------------------------------------------------------------------------------

def card_text(card):
    lines = [f"**Part number** · `{card['photo_name']}`"]
    for i, text in enumerate(card["options"], 1):
        lines.append(f"**{i}** `{text}`" + ("  ← most likely" if i == 1 else ""))
    if not card["options"]:
        lines.append("Agent 1 found no part number. Type it with ✏️.")
    lines.append("")
    if card["answer"] is None:
        lines.append("Answer: none yet")
    elif card["how"] == "default":
        lines.append(f"Answer: **1** `{card['answer']}` (nobody has picked, so 1)")
    elif card["how"] == "picked":
        lines.append(f"Answer: **{card['choice']}** `{card['answer']}`, picked by {card['by']}")
    else:
        lines.append(f"Answer: ✏️ `{card['answer']}`, typed by {card['by']}")
    return "\n".join(lines)


class Buttons(discord.ui.View):
    """1, 2, 3 (as many as there are options) and ✏️ Type your own; the current answer's button is green.
    Buttons() with no card has all of them, for registering after a restart."""

    def __init__(self, card=None):
        super().__init__(timeout=None)
        count = len(card["options"]) if card else HOW_MANY
        chosen = card and card["choice"]
        for i in range(1, count + 1):
            self.add_item(Pick(i, chosen == i))
        self.add_item(TypeOwn(chosen == "typed"))


class Pick(discord.ui.Button):
    def __init__(self, i, chosen):
        super().__init__(label=str(i), custom_id=f"partid:pick:{i}",
                         style=discord.ButtonStyle.success if chosen else discord.ButtonStyle.secondary)
        self.i = i

    async def callback(self, inter):
        card = load(inter.message.id)
        if card is None or self.i > len(card["options"]):
            return await inter.response.send_message("This card isn't saved any more.", ephemeral=True)
        answer(card, self.i, card["options"][self.i - 1], "picked", inter.user)
        await inter.response.edit_message(content=card_text(card), view=Buttons(card))


class TypeOwn(discord.ui.Button):
    def __init__(self, chosen):
        super().__init__(label="Type your own", emoji="\N{PENCIL}\N{VARIATION SELECTOR-16}", custom_id="partid:type",
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
            self.number.placeholder = card["options"][0]

    async def on_submit(self, inter):
        card = load(self.card_id)
        if card is None:
            return await inter.response.send_message("This card isn't saved any more.", ephemeral=True)
        typed = self.number.value.strip()
        if typed:
            answer(card, "typed", typed, "typed", inter.user)
        else:   # blank: back to the most likely
            answer(card, 1 if card["options"] else None, card["options"][0] if card["options"] else None,
                   "default", None)
        await inter.response.edit_message(content=card_text(card), view=Buttons(card))


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
            out = await run_agent1(path, {**env, "BEAR_SPEND_LEDGER": str(FOLDER / "spend.jsonl")})
        options = out["options"][:HOW_MANY]
        card = {"card": None, "photo": str(path), "photo_name": att.filename, "message": msg.jump_url,
                "options": options, "choice": 1 if options else None, "answer": options[0] if options else None,
                "how": "default", "by": None, "by_name": None, "at": time.time(), "read": out}
        reply = await msg.reply(card_text(card), view=Buttons(card), mention_author=False)
        card["card"] = reply.id
        save(card)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("part-id read failed for %s: %s", att.filename, e)
        await safe(msg.reply(f"**Agent 1** · `{att.filename}` failed, send the photo again:\n"
                             f"```\n{str(e)[-1500:]}\n```", mention_author=False))


async def run_agent1(path, env):
    """partid/agent1.py on one photo as its own process (so it can always be stopped): its JSON."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(AGENT1), str(path), stdin=asyncio.subprocess.DEVNULL,
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
