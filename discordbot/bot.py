"""Discord BEAR bot. One channel per car (the vehicle text is the channel topic):
/newfolder name:<x> starts a folder, 💸 flags each part-number photo, /run downloads the flagged
photos and runs BEAR on them as a separate process, then posts the spreadsheet. Up to
BEAR_MAX_RUNS folders (default 2) run at once; more wait in a queue. Errors go to the error
channel with a code and a fix (folders.ERRORS). /status lists what is running.

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

log = logging.getLogger("bear-bot")
RUN_PY = REPO / "bear2" / "run.py"
SIM_PY = REPO / "bear2" / "simulate.py"
HISTORY_LIMIT = 5000      # messages read back looking for the folder marker
MAX_UPLOAD_WAIT = 600     # /run gives up waiting for uploads to stop after this many seconds


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
        sim = setting("BEAR_SIM")
        await self.to_errors(f"\N{BEAR FACE} BEAR bot started: {MAX_RUNS} folders at once"
                             + (f", **dev mode** (simulated runs, `{sim}`)" if sim else "")
                             + ". A folder that was running when the bot stopped needs /run again.")

    async def error_channel(self):
        return self.get_channel(ERROR_CHANNEL_ID) or await self.fetch_channel(ERROR_CHANNEL_ID)

    async def to_errors(self, text, files=None):
        try:
            await (await self.error_channel()).send(text[:2000], files=files or [])
        except discord.DiscordException:
            log.exception("can't post to the error channel %s", ERROR_CHANNEL_ID)

    async def fail(self, ch, folder, code, detail="", logfile=None):
        """Post a problem to the error channel and say so in the car channel."""
        log.warning("%s %s %s: %s", ch, folder, code, detail[:300])
        files = [discord.File(logfile, filename=f"{folder}-log.txt")] if logfile and Path(logfile).exists() else []
        await self.to_errors(fo.error_report(folder, code, ch.mention, detail), files)
        try:
            await ch.send(f"\N{CROSS MARK} Folder **{folder}** encountered an issue — `{code}`: "
                          f"{fo.ERRORS[code][0]} Fix: {fo.ERRORS[code][1]} (also in <#{ERROR_CHANNEL_ID}>)")
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
            log.warning("can't delete a text message in %s: %s", msg.channel, e)


bot = Bot()


def car_channel_problem(ch):
    if not isinstance(ch, discord.TextChannel):
        return "Use this in a car's text channel."
    if CARS_CATEGORY_ID is not None and ch.category_id != CARS_CATEGORY_ID:
        return "Use this in a car channel (the channels in the cars category)."
    return None


@bot.tree.command(name="newfolder", description="Start a new folder (a box of parts) in this car channel")
@app_commands.describe(name="Folder name, e.g. Q184 (letters, numbers, - and _)")
async def newfolder(inter: discord.Interaction, name: str):
    ch = inter.channel
    problem = car_channel_problem(ch)
    if problem:
        return await inter.response.send_message(problem, ephemeral=True)
    if not fo.FOLDER_NAME.fullmatch(name):
        return await inter.response.send_message(
            "Folder names are letters, numbers, - and _ only (up to 40), e.g. Q184.", ephemeral=True)
    if not (ch.topic or "").strip():
        await inter.response.send_message(f"Folder **{name}** not started.", ephemeral=True)
        return await bot.fail(ch, name, "BEAR-D01")
    await inter.response.send_message(fo.marker(name))   # this reply is the marker /run looks for


@bot.tree.command(name="run", description="Run every 💸 photo in the current folder through BEAR")
async def run(inter: discord.Interaction):
    ch = inter.channel
    problem = car_channel_problem(ch)
    if problem:
        return await inter.response.send_message(problem, ephemeral=True)
    if ch.id in ACTIVE:
        a = ACTIVE[ch.id]
        return await inter.response.send_message(
            f"Folder **{a['folder']}** in this channel is still {a['state']}. /run again when it has finished.",
            ephemeral=True)
    # Claimed before the first await, so a second /run straight after this one is refused.
    ACTIVE[ch.id] = {"folder": "(no folder)", "state": "being checked", "parts": 0, "since": time.time()}
    folder = None
    try:
        await inter.response.send_message("Checking the folder ...")
        folder = await run_folder(ch)
    except fo.FolderError as e:
        await bot.fail(ch, ACTIVE[ch.id]["folder"], e.code, e.detail)
    except Exception:
        log.exception("run failed in %s", ch)
        await bot.fail(ch, ACTIVE[ch.id]["folder"], "BEAR-R01", traceback.format_exc()[-1400:])
    finally:
        ACTIVE.pop(ch.id, None)
    log.info("run finished in %s (%s)", ch, folder)


@bot.tree.command(name="status", description="Which folders BEAR is running or has queued")
async def status(inter: discord.Interaction):
    if not ACTIVE:
        return await inter.response.send_message(f"Nothing running. {MAX_RUNS} folders can run at once.")
    lines = [f"**{a['folder']}** in <#{cid}>: {a['state']}"
             + (f", {a['parts']} parts" if a["parts"] else "") + f" ({int(time.time() - a['since']) // 60} min)"
             for cid, a in ACTIVE.items()]
    await inter.response.send_message("\n".join(lines) + f"\n{MAX_RUNS} folders can run at once.")


async def read_folder(ch):
    """(name, messages after the latest marker, oldest first). Raises D02 if there is no folder."""
    history = [m async for m in ch.history(limit=HISTORY_LIMIT)]
    name, _, after = fo.split_folder(history, bot.user.id)
    if not name:
        raise fo.FolderError("BEAR-D02")
    return name, after


async def run_folder(ch):
    a = ACTIVE[ch.id]
    folder, msgs = await read_folder(ch)
    a["folder"] = folder
    car = (ch.topic or "").strip()
    if not car:
        raise fo.FolderError("BEAR-D01")
    # The bot can't see an upload still in progress: wait for UPLOAD_WAIT seconds of quiet.
    waited, told = 0, False
    while waited < MAX_UPLOAD_WAIT:
        age = fo.seconds_since_last_upload(msgs)
        if age is None or age >= UPLOAD_WAIT:
            break
        if not told:
            await ch.send(f"Folder **{folder}**: photos are still uploading, waiting until none arrive for {UPLOAD_WAIT} s ...")
            told = True
        pause = UPLOAD_WAIT - age + 1
        await asyncio.sleep(pause)
        waited += pause
        folder, msgs = await read_folder(ch)
        a["folder"] = folder
    picks = fo.flagged_photos(msgs)
    a.update(state="downloading photos", parts=len(picks))

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
    (run_dir / "photos.tsv").write_text("\n".join(manifest) + "\n")   # 001.jpg -> the Discord message

    if SLOTS.locked():
        a["state"] = "queued"
        await ch.send(f"Folder **{folder}**: {len(picks)} parts queued. {MAX_RUNS} folders are already running; "
                      "it starts as soon as one finishes.")
    async with SLOTS:
        a.update(state="running", since=time.time())
        await ch.send(f"\N{BEAR FACE} Running {len(picks)} parts for folder **{folder}** ({car}) ...")
        rc = await run_bear(photos, car, results, run_dir / "bear.log")
    await report(ch, folder, car, rc, run_dir, results)
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


async def report(ch, folder, car, rc, run_dir, results):
    logfile = run_dir / "bear.log"
    text = logfile.read_text(errors="replace") if logfile.exists() else ""
    xlsx = results / "results.xlsx"
    if rc is None:
        return await bot.fail(ch, folder, "BEAR-T01", text[-1200:], logfile)
    if rc != 0 or not xlsx.exists():
        return await bot.fail(ch, folder, fo.classify(text), text[-1200:], logfile)
    a2 = results / "agent2_results.md"
    photos, priced = fo.count_results(a2.read_text() if a2.exists() else "")
    await ch.send(f"\N{WHITE HEAVY CHECK MARK} Folder **{folder}**: BEAR found {priced} listings "
                  f"for {photos} parts ({photos - priced} not priced).",
                  file=discord.File(xlsx, filename=fo.xlsx_name(folder, car)))
    trace = results / "trace.json"
    code = fo.partial_problem(trace.read_text(errors="replace")) if trace.exists() else None
    if code:
        await bot.fail(ch, folder, code, "The spreadsheet was posted, but some parts failed because of this.", logfile)


@bot.tree.error
async def on_command_error(inter: discord.Interaction, error):
    log.error("command error: %s", error, exc_info=error)
    msg = "Something went wrong (BEAR-R01). The owner can see it in the bot's log."
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
