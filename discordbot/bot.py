"""Discord BEAR bot. One channel per car (the vehicle text is the channel topic):
/newfolder name:<x> starts a folder, people upload only part-number photos, /run downloads every
photo in the folder and runs BEAR on them as a separate process (each photo is one part), then
posts the spreadsheet. Up to
BEAR_MAX_RUNS folders (default 2) run at once; more wait in a queue. Errors go to the error
channel with a code and a fix (folders.ERRORS). /status lists what is running. Every 10 minutes
the bot checks in with an outside monitor that says in the error channel when BEAR is down, and after
an update it lists what changed in #update-log (heartbeat.py).
Renaming (renames.py) is separate from BEAR: /rename renames every photo in the folder to
SKU-1, SKU-2 ... and posts them as zips. /run's offer to do the same is dormant (BEAR_RENAME_OFFER).
/quit stops everything /run or /rename is doing in the channel.
Part check (partcheck.py): any photo posted in any channel (not the error or update-log channels) gets
a reply with the part number Agent 1 reads off it, with buttons to say it is right, pick another
reading or type it; the answer goes in <storage>/checks/part-numbers.txt. BEAR_PART_CHECK=0 turns it off.
After each /run, the shadow test (shadow.py) quietly asks Decisions models to read the location on
every photo in the folder and logs the answers; nothing is posted until there is enough data to look at.
How every post looks and reads is in look.py (discordbot/FRONTEND.md): each /run is one card,
edited as it goes, that ends green with the spreadsheet or red with what to do.

Settings come from the environment, then .env at the repo root (discordbot/SETUP.md):
  DISCORD_TOKEN, DISCORD_GUILD_ID, ERROR_CHANNEL_ID   required
  CARS_CATEGORY_ID     car channels live in this category; text-only messages are deleted there
  BEAR_MAX_RUNS        folders running at once (2)
  BEAR_UPLOAD_WAIT     seconds with no new upload before /run starts (30)
  BEAR_RUN_TIMEOUT     seconds before a run is stopped (7200)
  BEAR_STORAGE         where photos, results and logs are kept (<repo>/runs); renames go in its renames/
  BEAR_RENAME_OFFER    1 brings back /run's offer to rename the photos (off); read at each /run
  BEAR_RENAME_WAIT     seconds that offer gives people to type a SKU (60); read at each /run, no restart
  BEAR_RENAME_DOWNLOADS  photos downloaded at once by /run and /rename, across all channels (6)
  BEAR_ZIP_MB          biggest zip posted, in MiB (10: Discord's limit without server boosts)
  BEAR_SIM             dev mode: run bear2/simulate.py with this scenario, no credits spent (part checks
                       get a made-up read; no_number / read_fails try the other outcomes)
  BEAR_PART_CHECK      0 turns the part check off (on by default); read for each photo
  BEAR_CHECKS          photos the part check reads at once, across all channels (6)
  BEAR_CHECK_TIMEOUT   seconds before a part check gives up on a photo (60)
  BEAR_SHADOW          0 turns the shadow test off (on by default, never in dev mode); read at each /run
  BEAR_SHADOW_PING_PARTS  the error channel is told to look at the shadow data every this many part photos (300)
  BEAR_SHADOW_PING_USER   a Discord user ID to @mention in that note (blank: no mention)
  BEAR_HEARTBEAT_URL   the healthchecks.io ping URL checked in with every 10 minutes (blank: off)
  UPDATE_CHANNEL_ID    where the update log goes (blank: the channel named update-log; none: no log)
Every BEAR_* line in .env is passed to the BEAR runs (BEAR_RUN_CAP_USD, BEAR_NAME_MODEL, ...)
and read again for each run, so changing them needs no restart. The token is never passed on.

usage: python3 discordbot/bot.py       (systemd runs this: discordbot/deploy/bear-bot.service)
"""
import asyncio, json, logging, os, shutil, signal, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "tools"))
import jev_client  # noqa: E402  (the .env reader BEAR itself uses)
import discord  # noqa: E402
from discord import app_commands  # noqa: E402
import folders as fo  # noqa: E402
import heartbeat as hb  # noqa: E402
import look  # noqa: E402
import renames as rn  # noqa: E402
import partcheck as pc  # noqa: E402
import shadow as sh  # noqa: E402

log = logging.getLogger("bear-bot")
RUN_PY = REPO / "bear2" / "run.py"
CHECK_PY = HERE / "partcheck.py"
SIM_PY = REPO / "bear2" / "simulate.py"
HISTORY_LIMIT = 5000      # messages read back looking for the folder marker
MAX_UPLOAD_WAIT = 600     # /run gives up waiting for uploads to stop after this many seconds
NOTICE_GAP = 60           # seconds between "text was removed" notices in one channel
LINK = __import__("re").compile(r"https://discord\.com/channels/\S+")


def dotenv():
    return jev_client._parse_dotenv(jev_client.ENV_FILE)


def setting(name, default=None):
    """A setting, or default when it is unset, blank or still the PASTE_HERE placeholder."""
    v = (os.environ.get(name) or dotenv().get(name) or "").strip()
    return v if v and v != "PASTE_HERE" else default


def config_error(text):
    """Stop with a message for the log. Exit 78 tells systemd not to restart (bear-bot.service):
    the bot stays stopped until .env is fixed and it is restarted."""
    print(text, file=sys.stderr)
    sys.exit(78)


def number(name, default=None):
    """A whole-number setting; a typo stops the bot with a clear message instead of a crash loop."""
    v = setting(name)
    if v is None:
        if default is None:
            config_error(f"{name} is not filled in, in /opt/bear/.env (see discordbot/SETUP.md)")
        return default
    if not v.isdigit():
        config_error(f"{name} in .env must be a number only (no spaces or comments after it), not {v!r}")
    return int(v)


TOKEN = setting("DISCORD_TOKEN")
GUILD_ID = number("DISCORD_GUILD_ID")
ERROR_CHANNEL_ID = number("ERROR_CHANNEL_ID")
CARS_CATEGORY_ID = number("CARS_CATEGORY_ID", 0) or None   # unset: commands work anywhere, nothing is deleted
MAX_RUNS = max(1, number("BEAR_MAX_RUNS", 2))
UPLOAD_WAIT = number("BEAR_UPLOAD_WAIT", 30)
RUN_TIMEOUT = number("BEAR_RUN_TIMEOUT", 7200)
STORAGE = Path(setting("BEAR_STORAGE", str(REPO / "runs")))
RENAMES_DIR = STORAGE / "renames"   # on the same disk as the runs (the SSD on the VM)
SHADOW_DIR = STORAGE / "shadow"
CHECK_DIR = STORAGE / "checks"   # part-numbers.txt, the photos, pending/ (cards nobody has answered yet)
CHECK_LOG = CHECK_DIR / pc.LOG_NAME
CHECK_PENDING = CHECK_DIR / "pending"
RENAME_DOWNLOADS = max(1, number("BEAR_RENAME_DOWNLOADS", 6))
ZIP_MB = max(1, number("BEAR_ZIP_MB", 10))
CHECK_TIMEOUT = max(5, number("BEAR_CHECK_TIMEOUT", 60))
NO_CAR = "No car in the topic"

SLOTS = asyncio.Semaphore(MAX_RUNS)
# Runs and renames download photos RENAME_DOWNLOADS at a time across all of them (each is held in
# memory while it is saved). Renames have no limit on how many run at once; their zips are written
# two at a time (stored, not compressed: disk work only).
DOWNLOADS = asyncio.Semaphore(RENAME_DOWNLOADS)
ZIPPING = asyncio.Semaphore(2)
ACTIVE = {}   # channel id -> {"folder", "state", "parts", "since", "task"}: one /run per car channel at a time
RENAMES = {}  # channel id -> set of /rename tasks, so /quit can stop them
NOTICED = {}  # channel id -> when the last "text was removed" notice was posted
SHADOW = set()   # running shadow tests (kept so they aren't garbage collected mid-way)
SHADOW_CALLS = asyncio.Semaphore(4)   # photos asked about at once, across all folders
# Part checks have their own limit, so a photo never waits behind a folder's /run.
CHECKS = asyncio.Semaphore(max(1, number("BEAR_CHECKS", 6)))
CHECKING = set()   # running part checks (kept so they aren't garbage collected mid-way)
CHECK_ERROR_GAP = 600   # seconds between error-channel posts about failed part checks
CHECK_ERRORED = {}      # code -> when the error channel last heard about it


def dev():
    return bool(setting("BEAR_SIM"))


def rename_offer_on():
    """BEAR_RENAME_OFFER, read at each /run. Off by default: the renaming is kept but /run doesn't
    offer it (owner, 2026-10-25). /rename still works."""
    return setting("BEAR_RENAME_OFFER", "0").lower() in ("1", "on", "yes", "true")


def rename_wait():
    """BEAR_RENAME_WAIT, read again at each /run. A typo here logs a warning and uses 60 rather
    than stopping the bot in the middle of a run."""
    v = setting("BEAR_RENAME_WAIT", "60")
    if not v.isdigit():
        log.warning("BEAR_RENAME_WAIT in .env must be a number of seconds, not %r: using 60", v)
        return 60
    return max(5, int(v))


def version():
    return hb.version()   # VERSION plus the merges since it changed, e.g. 0.4.12


class Card:
    """The one live message for a /run (look.run_card), edited at each step. A normal channel
    message, not the reply to /run: replies stop being editable after 15 minutes."""

    def __init__(self, ch):
        self.ch, self.msg = ch, None

    async def show(self, post, file=None, view=False):
        """view: buttons to put under the card, None to take them away, False to leave them."""
        buttons = {} if view is False else {"view": view}
        try:
            if self.msg is not None:
                extra = {"attachments": [file]} if file else {}
                return await self.msg.edit(**look.kwargs(post), **extra, **buttons)
        except discord.DiscordException:
            log.warning("can't edit the card in %s, posting a new one", self.ch, exc_info=True)
        extra = {"file": file} if file else {}
        self.msg = await self.ch.send(**look.kwargs(post), **extra, **({"view": view} if view else {}))


def run_env():
    """Environment for one BEAR run: this process's, plus every BEAR_* line in .env (read now),
    minus the Discord token and the web page's ask switch (no one answers questions here)."""
    env = {**{k: v for k, v in dotenv().items() if k.startswith("BEAR_")}, **os.environ}
    for k in ("DISCORD_TOKEN", "BEAR_WEB_ASK"):
        env.pop(k, None)
    env["PYTHONUNBUFFERED"] = "1"
    return env


class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True   # needed to see files on other people's messages
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.started = False

    async def setup_hook(self):
        self.add_dynamic_items(CheckButton)   # part-check buttons keep working after a restart
        guild = discord.Object(GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)   # this server only, so commands appear at once

    async def on_ready(self):
        log.info("logged in as %s", self.user)
        if self.started:   # on_ready fires again after reconnects
            return
        self.started = True
        self.heartbeat = asyncio.create_task(heartbeat())
        await self.to_errors(look.bot_started(MAX_RUNS, setting("BEAR_SIM"), version()))
        # First start on new code: say what changed in #update-log (nothing when the code is the same)
        await asyncio.to_thread(hb.update_log, STORAGE / "update-log.last")

    async def error_channel(self):
        return self.get_channel(ERROR_CHANNEL_ID) or await self.fetch_channel(ERROR_CHANNEL_ID)

    async def to_errors(self, post, files=None, mention=False):
        extra = {"allowed_mentions": discord.AllowedMentions(users=True)} if mention else {}
        try:
            await (await self.error_channel()).send(**look.kwargs(post), files=files or [], **extra)
        except discord.DiscordException:
            log.exception("can't post to the error channel %s", ERROR_CHANNEL_ID)

    async def fail(self, ch, folder, code, detail="", logfile=None, card=None, partial=False, jump_url=None):
        """Post a problem to the error channel (the owner's fix, the log) and to the car channel
        (only what the uploader can do, with links to the photos it is about)."""
        label = folder or "(no folder)"
        log.warning("%s %s %s: %s", ch, label, code, detail[:300])
        files = [discord.File(logfile, filename=f"{label}-log.txt")] if logfile and Path(logfile).exists() else []
        meaning, fix = fo.ERRORS[code]
        await self.to_errors(look.error_report(label, code, meaning, fix, ch.id, (ch.topic or "").strip() or None,
                                               detail, jump_url, dev()), files)
        links = LINK.findall(detail) if code in ("BEAR-D05", "BEAR-D06", "BEAR-D07") else []
        post = look.problem_card(folder, code, ERROR_CHANNEL_ID, links, dev(), partial)
        try:
            await (card or Card(ch)).show(post)
        except discord.DiscordException:
            log.exception("can't post in %s", ch)

    async def on_message(self, msg):
        """Photos get a part check (any channel); text is never read: in car channels a message
        without a file is deleted."""
        if msg.attachments and not msg.author.bot and msg.guild and part_check_here(msg):
            start_check(msg)
        if (CARS_CATEGORY_ID is None or msg.author.bot or not msg.guild or msg.attachments
                or getattr(msg.channel, "category_id", None) != CARS_CATEGORY_ID
                or msg.channel.id == ERROR_CHANNEL_ID
                or msg.type not in (discord.MessageType.default, discord.MessageType.reply)):
            return
        try:
            await msg.delete()
        except discord.DiscordException as e:
            return log.warning("can't delete a text message in %s: %s", msg.channel, e)
        # Say why, at most once a minute per channel, and let the notice tidy itself away.
        if time.time() - NOTICED.get(msg.channel.id, 0) >= NOTICE_GAP:
            NOTICED[msg.channel.id] = time.time()
            try:
                await msg.channel.send(look.reply("text_removed"), delete_after=10)
            except discord.DiscordException:
                pass


bot = Bot()


def car_channel_problem(ch):
    if not isinstance(ch, discord.TextChannel):
        return look.reply("not_car_channel")
    if CARS_CATEGORY_ID is not None and ch.category_id != CARS_CATEGORY_ID:
        return look.reply("not_car_channel")
    return None


def never_run(msgs):
    """True if a folder (messages after its marker) has photos but /run never posted a card."""
    has_photos = any(not m.author.bot and any(fo.is_photo(att) for att in m.attachments) for m in msgs)
    has_card = any(m.author.bot and getattr(m, "embeds", None) and not fo.is_check_card(m) for m in msgs)
    return has_photos and not has_card


@bot.tree.command(name="newfolder", description=look.COMMANDS["newfolder"]["description"])
@app_commands.describe(**look.COMMANDS["newfolder"]["options"])
async def newfolder(inter: discord.Interaction, name: str):
    ch = inter.channel
    problem = car_channel_problem(ch)
    if problem:
        return await inter.response.send_message(problem, ephemeral=True)
    if not fo.FOLDER_NAME.fullmatch(name):
        return await inter.response.send_message(look.reply("bad_name"), ephemeral=True)
    car = (ch.topic or "").strip()
    if not car:
        await inter.response.send_message(look.reply("no_topic", name=name), ephemeral=True)
        return await bot.fail(ch, name, "BEAR-D01")
    # This reply is the marker /run looks for (its first line must stay fo.marker(name)).
    post = look.folder_card(name, car, dev())
    if post["content"] != fo.marker(name):
        post = {**post, "content": fo.marker(name)}
    await inter.response.send_message(**look.kwargs(post))
    # Then look at the folder before this one: skip back past the new marker to the previous one.
    previous, msgs = None, []
    try:
        history = [m async for m in ch.history(limit=500)]
        new = next((i for i, m in enumerate(history) if fo.marker_name(m, bot.user.id)), None)
        if new is not None:
            previous, _, msgs = fo.split_folder(history[new + 1:], bot.user.id)
    except discord.DiscordException:
        pass
    notes = []
    if previous and never_run(msgs):
        notes.append(look.open_folder_warning(previous))
    first = car.split()[0]
    if first.isdigit():
        notes.append(look.reply("topic_order", first=first))
    if notes:
        try:
            await inter.followup.send("\n\n".join(notes), ephemeral=True)
        except discord.DiscordException:
            pass


@bot.tree.command(name="run", description=look.COMMANDS["run"]["description"])
async def run(inter: discord.Interaction):
    ch = inter.channel
    problem = car_channel_problem(ch)
    if problem:
        return await inter.response.send_message(problem, ephemeral=True)
    if ch.id in ACTIVE:
        a = ACTIVE[ch.id]
        return await inter.response.send_message(look.reply("busy", folder=a["folder"] or "(checking)", state=a["state"]),
                                                  ephemeral=True)
    # Claimed before the first await, so a second /run straight after this one is refused.
    a = ACTIVE[ch.id] = {"folder": None, "state": "being checked", "parts": 0, "since": time.time(),
                         "channel_id": ch.id}
    card = Card(ch)
    try:
        await inter.response.send_message(look.reply("on_it"), ephemeral=True)
        if not a.get("quit"):
            a["task"] = asyncio.create_task(whole_run(ch, card, a))   # /quit cancels this
            await a["task"]
    except asyncio.CancelledError:
        if not a.get("quit"):   # the bot is stopping, not /quit
            raise
    finally:
        ACTIVE.pop(ch.id, None)
    if a.get("quit") and not a.get("bear_finished"):   # a finished spreadsheet card stays as it is
        try:
            await card.show(look.stopped_card(a["folder"], dev()))
        except discord.DiscordException:
            log.exception("can't post in %s", ch)
    log.info("run %s in %s (%s)", "stopped" if a.get("quit") else "finished", ch, a["folder"])


async def whole_run(ch, card, a):
    """Everything one /run does: BEAR on the folder's photos, and, if BEAR_RENAME_OFFER is on, beside it
    the offer to rename every photo in the folder, whose zip is posted after the spreadsheet. The
    two don't depend on each other: either can fail on its own. Cancelling this task (/quit) stops both."""
    car = (ch.topic or "").strip()
    await card.show(look.run_card("checking", None, car or NO_CAR, dev=dev()))
    ready, bear_done = asyncio.get_running_loop().create_future(), asyncio.Event()
    renaming = asyncio.create_task(offer_rename(ch, ready, bear_done)) if rename_offer_on() else None
    try:
        try:
            await run_folder(ch, card, a, ready)
        except fo.FolderError as e:
            await bot.fail(ch, a["folder"], e.code, e.detail, card=card, jump_url=a.get("marker_url"))
        except Exception:
            log.exception("run failed in %s", ch)
            await bot.fail(ch, a["folder"], "BEAR-R01", traceback.format_exc()[-1400:], card=card,
                           jump_url=a.get("marker_url"))
        finally:
            if not ready.done():   # no folder: nothing for the rename to number
                ready.set_result(None)
        a["bear_finished"] = True
        bear_done.set()
        got = ready.result() if ready.done() and not ready.cancelled() else None
        if got and shadow_on():
            start_shadow(ch, got[0], a.get("marker_id"), got[1])
        if renaming and not renaming.done():
            a.update(state="renaming photos")
            await renaming
    finally:
        if renaming and not renaming.done():
            renaming.cancel()
            await asyncio.gather(renaming, return_exceptions=True)


@bot.tree.command(name="quit", description=look.COMMANDS["quit"]["description"])
async def quit_cmd(inter: discord.Interaction):
    """Stops the /run in this channel (BEAR, its queue place, the rename offer and zip) and any /rename."""
    ch = inter.channel
    a = ACTIVE.get(ch.id)
    renaming = [t for t in RENAMES.get(ch.id, ()) if not t.done()]
    if not a and not renaming:
        return await inter.response.send_message(look.reply("quit_none"), ephemeral=True)
    what = []
    if a:
        a["quit"] = True
        if a.get("task"):
            a["task"].cancel()
        what.append(f"folder **{a['folder']}**" if a["folder"] else "the run")
    for t in renaming:
        t.cancel()
    if renaming:
        what.append("the renaming")
    log.info("/quit in %s by %s", ch, inter.user)
    await inter.response.send_message(look.reply("quit_done", what=" and ".join(what)), ephemeral=True)


@bot.tree.command(name="rename", description=look.COMMANDS["rename"]["description"])
@app_commands.describe(**look.COMMANDS["rename"]["options"])
async def rename(inter: discord.Interaction, sku: str):
    """Only the renaming: every photo in the folder, as SKU-1, SKU-2 ... in zips. No BEAR run, so
    it runs next to a /run or another /rename."""
    ch = inter.channel
    problem = car_channel_problem(ch)
    if problem:
        return await inter.response.send_message(problem, ephemeral=True)
    sku = sku.strip()
    if not rn.SKU.fullmatch(sku):
        return await inter.response.send_message(look.reply("bad_sku"), ephemeral=True)
    await inter.response.send_message(look.reply("rename_on_it", sku=sku), ephemeral=True)
    rcard = Card(ch)
    task = asyncio.create_task(rename_alone(ch, rcard, sku))
    RENAMES.setdefault(ch.id, set()).add(task)
    try:
        await task
    except asyncio.CancelledError:
        if not task.cancelled():   # the bot is stopping, not /quit
            raise
    finally:
        RENAMES.get(ch.id, set()).discard(task)
        if not RENAMES.get(ch.id):
            RENAMES.pop(ch.id, None)


async def rename_alone(ch, rcard, sku):
    folder = None

    async def seen(name, marker):
        nonlocal folder
        folder = name

    async def work():
        await rcard.show(look.rename_card("waiting", sku, dev=dev()))
        _, msgs, _ = await settled_folder(ch, seen)
        await rename_folder(ch, rcard, folder, msgs, sku)
    await guard_rename(ch, rcard, lambda: folder, sku, work())


@bot.tree.command(name="status", description=look.COMMANDS["status"]["description"])
async def status(inter: discord.Interaction):
    active = [{**a, "folder": a["folder"] or "(checking)", "channel_id": cid} for cid, a in ACTIVE.items()]
    await inter.response.send_message(**look.kwargs(look.status_card(active, MAX_RUNS, time.time(), dev())),
                                      ephemeral=True)


async def read_folder(ch):
    """(name, messages after the latest marker oldest first, the marker). Raises D02 if there is no folder."""
    history = [m async for m in ch.history(limit=HISTORY_LIMIT)]
    name, marker, after = fo.split_folder(history, bot.user.id)
    if not name:
        raise fo.FolderError("BEAR-D02")
    return name, after, marker


async def settled_folder(ch, seen=None, waiting=None):
    """The folder once uploads have stopped: (name, messages oldest first, marker). The bot can't
    see an upload still in progress, so it waits for UPLOAD_WAIT seconds with no new photo.
    seen(name, marker) is awaited after each read; waiting(name) once, if it has to wait."""
    folder, msgs, marker = await read_folder(ch)
    if seen:
        await seen(folder, marker)
    waited, told = 0, False
    while waited < MAX_UPLOAD_WAIT:
        age = fo.seconds_since_last_upload(msgs)
        if age is None or age >= UPLOAD_WAIT:
            break
        if not told and waiting:
            await waiting(folder)
            told = True
        pause = UPLOAD_WAIT - age + 1
        await asyncio.sleep(pause)
        waited += pause
        folder, msgs, marker = await read_folder(ch)
        if seen:
            await seen(folder, marker)
    return folder, msgs, marker


async def run_folder(ch, card, a, ready):
    """BEAR's side of /run. ready gets (folder, messages) once uploads have stopped, for the rename."""
    car = (ch.topic or "").strip()

    async def seen(folder, marker):
        first = a["folder"] is None
        a.update(folder=folder, marker_url=getattr(marker, "jump_url", None), marker_id=getattr(marker, "id", None))
        if first:
            await card.show(look.run_card("checking", folder, car or NO_CAR, dev=dev()))

    async def waiting(folder):
        await card.show(look.run_card("waiting", folder, car or NO_CAR, wait_seconds=UPLOAD_WAIT, dev=dev()))

    folder, msgs, marker = await settled_folder(ch, seen, waiting)
    ready.set_result((folder, msgs))
    if not car:
        raise fo.FolderError("BEAR-D01")
    picks = fo.part_photos(msgs)   # every photo in the folder: each one is a part
    a.update(state="downloading photos", parts=len(picks))
    await card.show(look.run_card("downloading", folder, car, parts=len(picks), got=0, dev=dev()))

    # Download now: Discord's file links expire after 24 hours.
    run_dir = new_dir(STORAGE / f"{fo.slug(ch.name)}-{ch.id}", folder)
    photos, results = run_dir / "photos", run_dir / "results"
    photos.mkdir(parents=True)
    names = [fo.photo_name(i, att.filename) for i, (_, att) in enumerate(picks, 1)]

    async def progress(got):
        await card.show(look.run_card("downloading", folder, car, parts=len(picks), got=got, dev=dev()))
    await download_all([(m, att, photos / n) for n, (m, att) in zip(names, picks)], "BEAR-D06", progress, every=5)
    (run_dir / "photos.tsv").write_text("".join(   # 001.jpg -> the Discord message
        f"{n}\t{att.filename}\t{m.jump_url}\n" for n, (m, att) in zip(names, picks)))

    started = time.time()
    if SLOTS.locked():
        a.update(state="queued", queued_at=time.time())
        ahead = sum(1 for o in ACTIVE.values() if o is not a and o["state"] == "queued"
                    and o.get("queued_at", 0) < a["queued_at"])
        await card.show(look.run_card("queued", folder, car, parts=len(picks), queue_ahead=ahead,
                                      max_runs=MAX_RUNS, dev=dev()))
    async with SLOTS:
        a.update(state="running", since=time.time())
        await card.show(look.run_card("running", folder, car, parts=len(picks), since=a["since"], dev=dev()))
        rc = await run_bear(photos, car, results, run_dir / "bear.log")
    await report(ch, card, folder, car, rc, run_dir, results, started, a.get("marker_url"))
    return folder


def new_dir(parent, name):
    """parent/<name>-<date-time>, with -2, -3 ... if the same name was started within a second."""
    base = parent / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    path, n = base, 1
    while path.exists():
        n += 1
        path = base.with_name(f"{base.name}-{n}")
    return path


async def download(att, path, msg, code):
    """Save one Discord file, three tries; then FolderError(code) with a link to its message."""
    for attempt in range(3):
        try:
            return await att.save(path)
        except (discord.DiscordException, OSError) as e:
            if attempt == 2:
                raise fo.FolderError(code, f"{att.filename}: {msg.jump_url}\n{type(e).__name__}: {e}")
            await asyncio.sleep(2 + attempt * 3)


async def download_all(files, code, progress=None, every=10):
    """Download [(message, attachment, path)], DOWNLOADS at a time across the server. progress(got)
    is awaited every `every` photos (Discord limits how often a message is edited). The first
    failure raises FolderError(code) and stops the rest."""
    async def one(msg, att, path):
        async with DOWNLOADS:
            await download(att, path, msg, code)
    tasks = [asyncio.create_task(one(*f)) for f in files]
    try:
        for got, t in enumerate(asyncio.as_completed(tasks), 1):
            await t
            if progress and got % every == 0 and got < len(tasks):
                await progress(got)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_bear(photos, car, results, logfile):
    """Run BEAR as its own process; returns its exit code, or None if it ran out of time.
    No stdin and no terminal, so BEAR skips the first-line check and stops if the name model fails.
    If this is cancelled (/quit), BEAR is stopped too."""
    env = run_env()
    sim = env.get("BEAR_SIM")
    script = SIM_PY if sim else RUN_PY
    env["BEAR_SPEND_LEDGER"] = str(logfile.parent / "spend.jsonl")   # this folder's spend only
    with open(logfile, "wb") as out:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script), str(photos), car, str(results),
            stdin=asyncio.subprocess.DEVNULL, stdout=out, stderr=asyncio.subprocess.STDOUT,
            cwd=str(REPO), env=env, start_new_session=True)
        try:
            return await asyncio.wait_for(proc.wait(), RUN_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            try:
                os.killpg(proc.pid, signal.SIGKILL)   # BEAR and the validator / xlsx steps it started
            except ProcessLookupError:   # it finished just as time ran out
                pass
            await proc.wait()
            if isinstance(e, asyncio.CancelledError):
                raise
            return None


# --- Part check ---------------------------------------------------------------------------------

def part_check_here(msg):
    """BEAR_PART_CHECK (on unless 0), read for each photo; never in the error or update-log channels."""
    if setting("BEAR_PART_CHECK", "1").lower() in ("0", "off", "no", "false"):
        return False
    ch = msg.channel
    return (msg.type in (discord.MessageType.default, discord.MessageType.reply)
            and ch.id != ERROR_CHANNEL_ID and str(ch.id) != setting("UPDATE_CHANNEL_ID")
            and getattr(ch, "name", None) != hb.UPDATE_CH)


def start_check(msg):
    """A part check for every photo in the message, in the background."""
    photos = [att for att in msg.attachments if rn.is_image(att)]
    for n, att in enumerate(photos, 1):
        task = asyncio.create_task(check_photo(msg, att, n, len(photos)))
        CHECKING.add(task)
        task.add_done_callback(CHECKING.discard)


def check_car(ch):
    """The car Agent 1 is told about: the topic in a car channel, else unknown."""
    car = (getattr(ch, "topic", None) or "").strip()
    return car if car and car_channel_problem(ch) is None else "unknown (not given)"


class CheckButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"bearcheck:(?P<what>ok|alt|fix)(?::(?P<i>\d))?"):
    """A button under a part-check card. Its id says only what it does (and which other reading):
    the read itself is in CHECK_PENDING under the card's message id, so it still works after a restart."""

    def __init__(self, what, i=None, label=None):
        style = {"ok": discord.ButtonStyle.success, "fix": discord.ButtonStyle.primary}.get(what, discord.ButtonStyle.secondary)
        emoji = {"ok": look.TICK, "fix": look.PENCIL}.get(what)
        custom_id = f"bearcheck:{what}" + (f":{i}" if i is not None else "")
        super().__init__(discord.ui.Button(label=label, style=style, emoji=emoji, custom_id=custom_id))
        self.what, self.i = what, i

    @classmethod
    async def from_custom_id(cls, inter, item, match):
        return cls(match["what"], int(match["i"]) if match["i"] else None)

    async def callback(self, inter: discord.Interaction):
        await check_answer(inter, self.what, self.i)


def check_buttons(number, alts):
    view = discord.ui.View(timeout=None)
    if number:
        view.add_item(CheckButton("ok", label=look.CHECK_BUTTONS["ok"]))
        for i, alt in enumerate(alts):
            view.add_item(CheckButton("alt", i, label=alt))
    view.add_item(CheckButton("fix", label=look.CHECK_BUTTONS["fix" if number else "type"]))
    return view


class FixBox(discord.ui.Modal, title=look.CHECK_BOX["title"]):
    number = discord.ui.TextInput(label=look.CHECK_BOX["label"], min_length=1, max_length=pc.MAX_TYPED)

    def __init__(self, card_id, read):
        super().__init__(timeout=900)
        self.card_id = card_id
        self.number.default = read or None

    async def on_submit(self, inter: discord.Interaction):
        number = pc.typed(self.number.value)
        if not number:
            return await inter.response.send_message(look.reply("check_bad_number"), ephemeral=True)
        await answered(inter, self.card_id, number, "fix")


async def check_answer(inter, what, i):
    """✅, another reading, or ✏️ (which opens the box; the answer is saved when it is sent)."""
    card_id = inter.message.id
    if what == "fix":
        rec = pc.peek(CHECK_PENDING, card_id)
        if rec is None:
            return await inter.response.send_message(look.reply("check_answered"), ephemeral=True)
        return await inter.response.send_modal(FixBox(card_id, rec.get("read")))
    rec = pc.peek(CHECK_PENDING, card_id) or {}
    alts = rec.get("alts") or []
    number = rec.get("read") if what == "ok" else (alts[i] if i is not None and i < len(alts) else None)
    if not number:
        return await inter.response.send_message(look.reply("check_answered"), ephemeral=True)
    await answered(inter, card_id, number, what)


async def answered(inter, card_id, number, how):
    """Save the answer once (a second tap is told it's taken) and turn the card green."""
    rec = pc.take(CHECK_PENDING, card_id)
    if rec is None:
        return await inter.response.send_message(look.reply("check_answered"), ephemeral=True)
    if how == "fix" and number == rec.get("read"):
        how = "ok"   # opened the box and sent BEAR's own reading back
    who = getattr(inter.user, "display_name", None) or str(inter.user)
    pc.log_answer(CHECK_LOG, rec, number, how, who)
    log.info("part check in %s: %s (%s by %s, BEAR read %s)", inter.channel, number, how, who, rec.get("read"))
    post = look.check_card("done", number, photo=rec.get("photo"), of=rec.get("of"), how=how, read=rec.get("read"),
                           who=getattr(inter.user, "mention", who), dev=dev())
    await inter.response.edit_message(**look.kwargs(post), view=None)


async def check_photo(msg, att, n, of):
    """Reply to one photo with the part number BEAR reads off it. Never raises."""
    ch = msg.channel
    try:
        card = await ch.send(**look.kwargs(look.check_card("reading", photo=n, of=of, dev=dev())),
                             reference=msg.to_reference(fail_if_not_exists=False))
    except discord.DiscordException:
        return log.warning("can't post a part check in %s", ch, exc_info=True)
    if not fo.is_photo(att):   # HEIC and other images BEAR can't open
        return await check_show(card, look.check_card("unreadable", photo=n, of=of, dev=dev()))
    try:
        async with CHECKS:
            where = CHECK_DIR / "photos" / f"{fo.slug(getattr(ch, 'name', 'dm'))}-{ch.id}"
            where.mkdir(parents=True, exist_ok=True)
            saved = where / f"{msg.id}-{n}{Path(att.filename).suffix.lower()}"
            await download(att, saved, msg, "BEAR-C01")
            got = await read_part(saved, check_car(ch))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        got = {"error": f"{type(e).__name__}: {getattr(e, 'detail', '') or e}"}
    if got.get("error"):
        await check_failed(ch, msg, got["error"])
        return await check_show(card, look.check_card("failed", photo=n, of=of, dev=dev()))
    number, alts = pc.answer(got)
    rec = {"read": number, "alts": alts, "photo": n, "of": of, "channel": f"#{getattr(ch, 'name', ch.id)}",
           "photo_url": msg.jump_url, "saved": str(saved), "read_s": got.get("read_s"),
           "wait_s": round(time.time() - msg.created_at.timestamp(), 1), "cost": got.get("cost"),
           "description": got.get("part_description")}
    try:
        pc.save_pending(CHECK_PENDING, card.id, rec)
    except OSError as e:   # the buttons would have nothing to save
        await check_failed(ch, msg, f"can't keep the read: {type(e).__name__}: {e}")
        return await check_show(card, look.check_card("failed", photo=n, of=of, dev=dev()))
    post = look.check_card("ask" if number else "none", number, alts, n, of, seconds=got.get("read_s"), dev=dev())
    await check_show(card, post, check_buttons(number, alts))


async def check_show(card, post, view=None):
    try:
        await card.edit(**look.kwargs(post), view=view)
    except discord.DiscordException:
        log.warning("can't edit the part check card in %s", card.channel, exc_info=True)


async def read_part(photo, car):
    """partcheck.py on one photo as its own process: its JSON, or {"error": ...}. Stopped after
    CHECK_TIMEOUT seconds whatever the model is doing."""
    env = run_env()
    env["BEAR_SPEND_LEDGER"] = str(CHECK_DIR / "spend.jsonl")   # part checks' spend, apart from the runs
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(CHECK_PY), str(photo), car, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(REPO), env=env,
        start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), CHECK_TIMEOUT)
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        if isinstance(e, asyncio.CancelledError):
            raise
        return {"error": f"no answer within {CHECK_TIMEOUT} s"}
    lines = out.decode(errors="replace").strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, ValueError):
        return {"error": f"partcheck.py exit {proc.returncode}: {err.decode(errors='replace')[-600:]}"}


async def check_failed(ch, msg, detail):
    """Tell the error channel, at most once per CHECK_ERROR_GAP per code: when the read model is down,
    every photo fails, and one post says so."""
    code = "BEAR-K01" if "HTTP 402" in detail else "BEAR-C01"
    log.warning("part check failed in %s (%s): %s", ch, code, detail[:300])
    if time.time() - CHECK_ERRORED.get(code, 0) < CHECK_ERROR_GAP:
        return
    CHECK_ERRORED[code] = time.time()
    meaning, fix = fo.ERRORS[code]
    car = check_car(ch)
    await bot.to_errors(look.error_report("Part check", code, meaning, fix, ch.id, None if car.startswith("unknown") else car,
                                          detail, msg.jump_url, dev()))


# --- Renaming -----------------------------------------------------------------------------------

class SkuAsk(discord.ui.View):
    """The Rename photos button under /run's offer. It keeps its own deadline: a View's timeout
    starts again on every click, so it can't be the clock."""

    def __init__(self, deadline, wait):
        super().__init__(timeout=None)
        self.deadline, self.wait = deadline, wait
        self.answer = asyncio.get_running_loop().create_future()

    def open(self):
        return not self.answer.done() and time.time() < self.deadline

    def close(self):
        if not self.answer.done():
            self.answer.cancel()
        self.stop()

    @discord.ui.button(label="Rename photos", emoji=look.TAG, style=discord.ButtonStyle.primary)
    async def rename_photos(self, inter: discord.Interaction, button):
        if not self.open():
            return await inter.response.send_message(look.reply("too_late", wait=self.wait), ephemeral=True)
        await inter.response.send_modal(SkuBox(self))


class SkuBox(discord.ui.Modal, title="Rename the photos"):
    sku = discord.ui.TextInput(label="SKU (letters, numbers, - and _)", placeholder="e.g. MYSKU",
                               min_length=1, max_length=40)

    def __init__(self, ask):
        super().__init__(timeout=max(1, ask.deadline - time.time()) + 300)
        self.ask = ask

    async def on_submit(self, inter: discord.Interaction):
        sku = self.sku.value.strip()
        if not self.ask.open():
            return await inter.response.send_message(look.reply("too_late", wait=self.ask.wait), ephemeral=True)
        if not rn.SKU.fullmatch(sku):   # the button is still there to try again
            return await inter.response.send_message(look.reply("bad_sku"), ephemeral=True)
        self.ask.answer.set_result(sku)
        log.info("SKU %s given by %s in %s", sku, inter.user, inter.channel)
        await inter.response.send_message(look.reply("sku_ok", sku=sku), ephemeral=True)


async def ask_sku(rcard, wait, ready):
    """Post the offer with its button; the SKU typed within `wait` seconds, or None. It closes
    early if ready says there is no folder."""
    deadline = time.time() + wait
    ask = SkuAsk(deadline, wait)

    def no_folder(f):
        if f.result() is None and not ask.answer.done():
            ask.answer.set_result(None)
    ready.add_done_callback(no_folder)
    await rcard.show(look.rename_card("offer", deadline=deadline, dev=dev()), view=ask)
    try:
        return await asyncio.wait_for(asyncio.shield(ask.answer), wait)
    except asyncio.TimeoutError:
        return None
    finally:
        ask.close()


async def offer_rename(ch, ready, bear_done):
    """/run's rename: offer it, and if a SKU is given, rename the photos BEAR's side settled on
    (ready) and post the zips once the spreadsheet is out (bear_done)."""
    rcard, sku, folder = Card(ch), None, None

    async def work():
        nonlocal sku, folder
        sku = await ask_sku(rcard, rename_wait(), ready)
        if not sku and ready.done() and ready.result() is None:   # no folder: the run card says so
            rename_log(ch, None, None, "no folder")
            return await rcard.show(look.rename_card("nothing", dev=dev()), view=None)
        if not sku:
            rename_log(ch, None, None, "no SKU given")
            return await rcard.show(look.rename_card("skipped", dev=dev()), view=None)
        await rcard.show(look.rename_card("waiting", sku, dev=dev()), view=None)
        got = await ready
        if not got:   # no folder: the run card already says so
            rename_log(ch, None, sku, "no folder")
            return await rcard.show(look.rename_card("nothing", sku, dev=dev()))
        folder = got[0]
        await rename_folder(ch, rcard, folder, got[1], sku, bear_done.wait)
    await guard_rename(ch, rcard, lambda: folder, lambda: sku, work())


async def guard_rename(ch, rcard, folder, sku, work):
    """Run a rename, and say on its card how it ended if it didn't finish: stopped by /quit, or
    BEAR-D07. folder and sku are the name and SKU, or functions giving them as they are now."""
    get = lambda v: v() if callable(v) else v   # noqa: E731
    try:
        await work
    except asyncio.CancelledError:
        rename_log(ch, get(folder), get(sku), "stopped with /quit")
        try:
            await rcard.show(look.rename_card("stopped", get(sku), dev=dev()), view=None)
        except discord.DiscordException:
            pass
        raise
    except fo.FolderError as e:
        await bot.fail(ch, get(folder) or get(sku), e.code, e.detail, card=rcard)
        rename_log(ch, get(folder), get(sku), f"failed {e.code}")
    except Exception:
        log.exception("rename failed in %s", ch)
        await bot.fail(ch, get(folder) or get(sku), "BEAR-D07", traceback.format_exc()[-1400:], card=rcard)
        rename_log(ch, get(folder), get(sku), "failed BEAR-D07")


async def rename_folder(ch, rcard, folder, msgs, sku, before_post=None):
    """Every photo in msgs, numbered from the start of the folder, saved as SKU-1.jpg ... in
    <storage>/renames/<channel>/<SKU>-<time>/, zipped to fit Discord and posted. before_post is
    awaited before the zips go up (/run: the spreadsheet first). Afterwards only renamed.tsv
    (new name, Discord name, message) stays on disk, and a line in renames/renames.log."""
    picks, others = rn.all_photos(msgs)
    if not picks:
        rename_log(ch, folder, sku, "no photos")
        return await rcard.show(look.rename_card("nothing", sku, folder, dev=dev()))
    job = new_dir(RENAMES_DIR / f"{fo.slug(ch.name)}-{ch.id}", sku)
    photos, zips = job / "photos", job / "zips"
    photos.mkdir(parents=True)
    zips.mkdir()
    names = [rn.new_name(sku, i, att.filename) for i, (_, att) in enumerate(picks, 1)]
    too_big = []
    (job / "renamed.tsv").write_text("".join(f"{n}\t{att.filename}\t{m.jump_url}\n"
                                             for n, (m, att) in zip(names, picks)))
    try:
        await rcard.show(look.rename_card("saving", sku, folder, photos=len(picks), got=0, dev=dev()))

        async def progress(got):
            await rcard.show(look.rename_card("saving", sku, folder, photos=len(picks), got=got, dev=dev()))
        await download_all([(m, att, photos / n) for n, (m, att) in zip(names, picks)], "BEAR-D07", progress)

        plan, too_big = rn.plan_zips([(n, (photos / n).stat().st_size) for n in names], ZIP_MB * 1024 * 1024)
        made = []
        for k, part in enumerate(plan, 1):
            path = zips / rn.zip_name(sku, k)
            async with ZIPPING:
                await asyncio.to_thread(rn.write_zip, path, [(photos / names[i], names[i]) for i in part])
            made.append((path, names[part[0]], names[part[-1]]))
        await rcard.show(look.rename_card("posting", sku, folder, photos=len(picks), alone=before_post is None,
                                          dev=dev()))
        if before_post:
            await before_post()
        for k, (path, first, last) in enumerate(made, 1):
            try:
                await ch.send(**look.kwargs(look.zip_post(sku, k, len(made), first, last)),
                              file=discord.File(path, filename=path.name))
            except discord.DiscordException as e:
                raise fo.FolderError("BEAR-D07", f"{path.name} ({path.stat().st_size} bytes) wasn't posted: "
                                                 f"{type(e).__name__}: {e}")
        await rcard.show(look.rename_card("done", sku, folder, photos=len(picks), zips=len(made), first=names[0],
                                          last=names[-1], others=others, too_big=[names[i] for i in too_big],
                                          dev=dev()))
        rename_log(ch, folder, sku, "posted", len(picks), len(made), job)
    finally:
        # Tidy up whatever happened; photos too big for Discord stay so the owner can hand them over.
        keep = {names[i] for i in too_big}
        shutil.rmtree(zips, ignore_errors=True)
        for p in photos.iterdir():
            if p.name not in keep:
                p.unlink(missing_ok=True)
        if not keep:
            shutil.rmtree(photos, ignore_errors=True)


def rename_log(ch, folder, sku, outcome, photos=0, zips=0, where=""):
    """One line per rename (or offer left blank) in <storage>/renames/renames.log, kept for good."""
    log.info("rename in %s: %s %s %s (%s photos, %s zips)", ch, folder, sku, outcome, photos, zips)
    try:
        RENAMES_DIR.mkdir(parents=True, exist_ok=True)
        with open(RENAMES_DIR / "renames.log", "a") as f:
            f.write(rn.log_line(f"{ch.name}-{ch.id}", folder, sku, outcome, photos, zips, where))
    except OSError:
        log.exception("can't write the rename log")


async def report(ch, card, folder, car, rc, run_dir, results, started, jump_url=None):
    logfile = run_dir / "bear.log"
    text = logfile.read_text(errors="replace") if logfile.exists() else ""
    xlsx = results / "results.xlsx"
    if rc is None:
        return await bot.fail(ch, folder, "BEAR-T01", text[-1200:], logfile, card, jump_url=jump_url)
    if rc != 0 or not xlsx.exists():
        return await bot.fail(ch, folder, fo.classify(text), text[-1200:], logfile, card, jump_url=jump_url)
    a2 = results / "agent2_results.md"
    photos, priced = fo.count_results(a2.read_text() if a2.exists() else "")
    name = fo.xlsx_name(folder, car)
    await card.show(look.done_card(folder, car, photos, priced, name, round((time.time() - started) / 60), dev()),
                    file=discord.File(xlsx, filename=name))
    trace = results / "trace.json"
    code = fo.partial_problem(trace.read_text(errors="replace")) if trace.exists() else None
    if code:   # a new message under the green card, which keeps its spreadsheet
        await bot.fail(ch, folder, code, "The spreadsheet was posted, but some parts failed because of this.",
                       logfile, partial=True, jump_url=jump_url)


# --- Shadow test (shadow.py) ------------------------------------------------------------------

def shadow_on():
    """Read at each /run. Off in dev mode: it would spend credit."""
    return not dev() and setting("BEAR_SHADOW", "1").lower() not in ("0", "off", "no", "false")


def start_shadow(ch, folder, marker_id, msgs):
    """Start the shadow test for a folder in the background: /run doesn't wait for it, and /quit
    doesn't stop it. Skipped when the folder had no usable photos (D03, D05)."""
    try:
        photos = fo.part_photos(msgs)
    except fo.FolderError:
        return
    task = asyncio.create_task(shadow_folder(ch, folder, marker_id, photos))
    SHADOW.add(task)
    task.add_done_callback(SHADOW.discard)


async def shadow_folder(ch, folder, marker_id, photos):
    """Ask the Decisions models about every photo in the folder and log the answers. Every photo is
    a part-number photo now, so each is logged as flagged (the log's old name for that) and asked
    the location by every model. Never raises."""
    try:
        base = {"channel": f"{ch.name}-{ch.id}", "folder": folder, "marker": marker_id,
                "run": datetime.now().strftime("%Y%m%d-%H%M%S-%f"), "of": len(photos)}

        async def one(n, msg, att):
            models = [sh.LABEL_MODEL, *sh.LOC_MODELS]
            async with SHADOW_CALLS:
                try:
                    uri = await asyncio.to_thread(sh.data_uri, await att.read())
                except Exception as e:
                    results = {m: {"error": f"photo: {type(e).__name__}: {e}"[:300]} for m in models}
                else:
                    results = {m: await asyncio.to_thread(sh.check, m, uri, m == sh.LABEL_MODEL) for m in models}
            return [sh.record(base, n, att.filename, msg.jump_url, True, m, r) for m, r in results.items()]
        done = await asyncio.gather(*(one(n, m, att) for n, (m, att) in enumerate(photos, 1)))
        path = SHADOW_DIR / "shadow.jsonl"
        sh.append(path, [r for rows in done for r in rows])
        log.info("shadow test logged %s photos of %s in %s", len(photos), folder, ch)
        await shadow_ping(path)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("shadow test failed for %s in %s", folder, ch)


async def shadow_ping(path):
    """Tell the error channel to look at the data each time another BEAR_SHADOW_PING_PARTS part photos
    have been logged. The number of notes so far is kept in shadow/pinged."""
    v = setting("BEAR_SHADOW_PING_PARTS", str(sh.PING_EVERY))
    every = int(v) if v.isdigit() and int(v) > 0 else sh.PING_EVERY
    folders, parts = sh.counts(sh.read_log(path))
    marker = SHADOW_DIR / "pinged"
    try:
        done = int(marker.read_text().strip())
    except (OSError, ValueError):
        done = 0
    due = sh.pings_due(parts, done, every)
    if due is None:
        return
    marker.write_text(f"{due}\n")
    user = setting("BEAR_SHADOW_PING_USER")
    user = user if user and user.isdigit() else None
    await bot.to_errors(look.shadow_ping(folders, parts, path, user), mention=bool(user))


async def heartbeat():
    """Check in with the outside monitor every 10 minutes (heartbeat.py); it posts in the error
    channel only when check-ins stop or start again. BEAR_HEARTBEAT_URL is read each time."""
    while True:
        await asyncio.to_thread(hb.ping)
        await asyncio.sleep(hb.EVERY)


@bot.tree.error
async def on_command_error(inter: discord.Interaction, error):
    log.error("command error: %s", error, exc_info=error)
    msg = look.reply("oops")
    try:
        if inter.response.is_done():
            await inter.followup.send(msg, ephemeral=True)
        else:
            await inter.response.send_message(msg, ephemeral=True)
    except discord.DiscordException:
        pass


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not TOKEN:
        config_error("DISCORD_TOKEN is not filled in, in /opt/bear/.env (see discordbot/SETUP.md)")
    STORAGE.mkdir(parents=True, exist_ok=True)
    try:
        bot.run(TOKEN, log_handler=None)
    except discord.LoginFailure:
        config_error("Discord refused DISCORD_TOKEN: paste the current token from the Bot page into .env (SETUP.md part 2)")
    except discord.PrivilegedIntentsRequired:
        config_error("Turn on Message Content Intent on the Discord Bot page (SETUP.md part 2), then restart")


if __name__ == "__main__":
    main()
