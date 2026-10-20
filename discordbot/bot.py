"""Discord BEAR bot. One channel per car (the vehicle text is the channel topic):
/newfolder name:<x> starts a folder, 💸 flags each part-number photo, /run downloads the flagged
photos and runs BEAR on them as a separate process, then posts the spreadsheet. Up to
BEAR_MAX_RUNS folders (default 2) run at once; more wait in a queue. Errors go to the error
channel with a code and a fix (folders.ERRORS). /status lists what is running.
How every post looks and reads is in look.py (discordbot/FRONTEND.md): each /run is one card,
edited as it goes, that ends green with the spreadsheet or red with what to do.

Settings come from the environment, then .env at the repo root (discordbot/SETUP.md):
  DISCORD_TOKEN, DISCORD_GUILD_ID, ERROR_CHANNEL_ID   required
  CARS_CATEGORY_ID     car channels live in this category; text-only messages are deleted there
  BEAR_MAX_RUNS        folders running at once (2)
  BEAR_UPLOAD_WAIT     seconds with no new upload before /run starts (30)
  BEAR_RUN_TIMEOUT     seconds before a run is stopped (7200)
  BEAR_STORAGE         where photos, results and logs are kept (<repo>/runs)
  BEAR_SIM             dev mode: run bear2/simulate.py with this scenario, no credits spent
Every BEAR_* line in .env is passed to the BEAR runs (BEAR_RUN_CAP_USD, BEAR_NAME_MODEL, ...)
and read again for each run, so changing them needs no restart. The token is never passed on.

usage: python3 discordbot/bot.py       (systemd runs this: discordbot/deploy/bear-bot.service)
"""
import asyncio, logging, os, signal, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "tools"))
import jev_client  # noqa: E402  (the .env reader BEAR itself uses)
import discord  # noqa: E402
from discord import app_commands  # noqa: E402
import folders as fo  # noqa: E402
import look  # noqa: E402

log = logging.getLogger("bear-bot")
RUN_PY = REPO / "bear2" / "run.py"
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

SLOTS = asyncio.Semaphore(MAX_RUNS)
ACTIVE = {}   # channel id -> {"folder", "state", "parts", "since"}: one folder per car channel at a time
NOTICED = {}  # channel id -> when the last "text was removed" notice was posted


def dev():
    return bool(setting("BEAR_SIM"))


def version():
    try:
        return (REPO / "VERSION").read_text().strip()
    except OSError:
        return None


class Card:
    """The one live message for a /run (look.run_card), edited at each step. A normal channel
    message, not the reply to /run: replies stop being editable after 15 minutes."""

    def __init__(self, ch):
        self.ch, self.msg = ch, None

    async def show(self, post, file=None):
        try:
            if self.msg is not None:
                extra = {"attachments": [file]} if file else {}
                return await self.msg.edit(**look.kwargs(post), **extra)
        except discord.DiscordException:
            log.warning("can't edit the run card in %s, posting a new one", self.ch, exc_info=True)
        extra = {"file": file} if file else {}
        self.msg = await self.ch.send(**look.kwargs(post), **extra)


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
        guild = discord.Object(GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)   # this server only, so commands appear at once

    async def on_ready(self):
        log.info("logged in as %s", self.user)
        if self.started:   # on_ready fires again after reconnects
            return
        self.started = True
        await self.to_errors(look.bot_started(MAX_RUNS, setting("BEAR_SIM"), version()))

    async def error_channel(self):
        return self.get_channel(ERROR_CHANNEL_ID) or await self.fetch_channel(ERROR_CHANNEL_ID)

    async def to_errors(self, post, files=None):
        try:
            await (await self.error_channel()).send(**look.kwargs(post), files=files or [])
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
        links = LINK.findall(detail) if code in ("BEAR-D04", "BEAR-D05", "BEAR-D06") else []
        post = look.problem_card(folder, code, ERROR_CHANNEL_ID, links, dev(), partial)
        try:
            await (card or Card(ch)).show(post)
        except discord.DiscordException:
            log.exception("can't post in %s", ch)

    async def on_message(self, msg):
        """Text is never read: in car channels a message without a file is deleted."""
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
    """True if a folder (messages after its marker) has 💸 photos but /run never posted a card."""
    has_flags = any(not m.author.bot and m.attachments and fo.flagged(m) for m in msgs)
    has_card = any(m.author.bot and getattr(m, "embeds", None) for m in msgs)
    return has_flags and not has_card


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
    ACTIVE[ch.id] = {"folder": None, "state": "being checked", "parts": 0, "since": time.time(),
                     "channel_id": ch.id}
    folder, card = None, Card(ch)
    try:
        await inter.response.send_message(look.reply("on_it"), ephemeral=True)
        folder = await run_folder(ch, card)
    except fo.FolderError as e:
        a = ACTIVE[ch.id]
        await bot.fail(ch, a["folder"], e.code, e.detail, card=card, jump_url=a.get("marker_url"))
    except Exception:
        log.exception("run failed in %s", ch)
        a = ACTIVE[ch.id]
        await bot.fail(ch, a["folder"], "BEAR-R01", traceback.format_exc()[-1400:], card=card,
                       jump_url=a.get("marker_url"))
    finally:
        ACTIVE.pop(ch.id, None)
    log.info("run finished in %s (%s)", ch, folder)


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


async def run_folder(ch, card):
    a = ACTIVE[ch.id]
    car = (ch.topic or "").strip()
    await card.show(look.run_card("checking", None, car or "No car in the topic", dev=dev()))
    folder, msgs, marker = await read_folder(ch)
    a.update(folder=folder, marker_url=getattr(marker, "jump_url", None))
    if not car:
        raise fo.FolderError("BEAR-D01")
    await card.show(look.run_card("checking", folder, car, dev=dev()))
    # The bot can't see an upload still in progress: wait for UPLOAD_WAIT seconds of quiet.
    waited, told = 0, False
    while waited < MAX_UPLOAD_WAIT:
        age = fo.seconds_since_last_upload(msgs)
        if age is None or age >= UPLOAD_WAIT:
            break
        if not told:
            await card.show(look.run_card("waiting", folder, car, wait_seconds=UPLOAD_WAIT, dev=dev()))
            told = True
        pause = UPLOAD_WAIT - age + 1
        await asyncio.sleep(pause)
        waited += pause
        folder, msgs, marker = await read_folder(ch)
        a.update(folder=folder, marker_url=getattr(marker, "jump_url", None))
    picks = fo.flagged_photos(msgs)
    a.update(state="downloading photos", parts=len(picks))
    await card.show(look.run_card("downloading", folder, car, parts=len(picks), got=0, dev=dev()))

    # Download now: Discord's file links expire after 24 hours.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = base = STORAGE / f"{fo.slug(ch.name)}-{ch.id}" / f"{folder}-{stamp}"
    n = 1
    while run_dir.exists():   # the same folder run again within a second
        n += 1
        run_dir = base.with_name(f"{base.name}-{n}")
    photos, results = run_dir / "photos", run_dir / "results"
    photos.mkdir(parents=True)
    manifest = []
    for i, (msg, att) in enumerate(picks, 1):
        name = fo.photo_name(i, att.filename)
        for attempt in range(3):
            try:
                await att.save(photos / name)
                break
            except (discord.DiscordException, OSError) as e:
                if attempt == 2:
                    raise fo.FolderError("BEAR-D06", f"{att.filename}: {msg.jump_url}\n{type(e).__name__}: {e}")
                await asyncio.sleep(2 + attempt * 3)
        manifest.append(f"{name}\t{att.filename}\t{msg.jump_url}")
        if i % 5 == 0 and i < len(picks):   # not every photo: Discord limits how often a message is edited
            await card.show(look.run_card("downloading", folder, car, parts=len(picks), got=i, dev=dev()))
    (run_dir / "photos.tsv").write_text("\n".join(manifest) + "\n")   # 001.jpg -> the Discord message

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


async def run_bear(photos, car, results, logfile):
    """Run BEAR as its own process; returns its exit code, or None if it ran out of time.
    No stdin and no terminal, so BEAR skips the first-line check and stops if the name model fails."""
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
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)   # BEAR and the validator / xlsx steps it started
            except ProcessLookupError:   # it finished just as time ran out
                pass
            await proc.wait()
            return None


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
