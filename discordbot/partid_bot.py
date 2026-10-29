"""#part-id, a framework for now: someone posts a part-number photo, the bot runs #part-id's own Agent 1 on it
(partid/agent1.py) and replies with the model's raw output. Kept apart from /run while the new
pipeline is decided (owner, 2026-10-29): no folders, no spreadsheet, nothing in bear2/ changes.

One reply per photo, posted as soon as its read is done. Text messages are left alone. Each photo
and its read are kept in <storage>/part-id/ (<message id>-<n>.<ext> and .json), and the spend goes
in <storage>/part-id/spend.jsonl, apart from the runs.

The channel is PART_ID_CHANNEL_ID, or else the channel named part-id (setup_server.py makes it).
How the reply looks is reply_text() below, the one place to change it.
"""
import asyncio, json, logging, os, signal, sys
from pathlib import Path, PurePath

import folders as fo
from renames import is_image

log = logging.getLogger("bear-bot")
AGENT1 = Path(__file__).resolve().parent.parent / "partid" / "agent1.py"
CHANNEL = "part-id"
READS = asyncio.Semaphore(4)   # photos read at once
TIMEOUT = 180                  # seconds before a read is stopped
LIMIT = 2000                   # Discord's message length


def is_partid(channel, channel_id):
    """channel_id: PART_ID_CHANNEL_ID (None: find the channel by its name)."""
    return channel.id == channel_id if channel_id else getattr(channel, "name", None) == CHANNEL


def reply_text(name, out):
    """The reply for one photo: a header line, then the raw read. None if it is too long for one
    message (it then goes up as a file). The look is to be designed later (owner, 2026-10-29)."""
    raw = (out["raw"] or "(empty)").replace("```", "'''")   # would end the code block early
    text = (f"**Agent 1** · `{name}` · {out['model']} · {out['seconds']} s · ${out['cost']:.4f}\n"
            f"```json\n{raw}\n```")
    return text if len(text) <= LIMIT else None


async def handle(msg, storage, env, discord):
    """Read every photo on msg, each replied to on its own as soon as it is done."""
    photos = [a for a in msg.attachments if fo.is_photo(a)]
    unreadable = [a.filename for a in msg.attachments if is_image(a) and not fo.is_photo(a)]
    if unreadable:
        await safe(msg.reply(f"Can't read {', '.join(unreadable)}: send it as JPG, PNG or WEBP.",
                             mention_author=False))
    await asyncio.gather(*(one(msg, att, n, storage, env, discord) for n, att in enumerate(photos, 1)))


async def one(msg, att, n, storage, env, discord):
    folder = Path(storage) / "part-id"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{msg.id}-{n}{PurePath(att.filename).suffix.lower()}"
    try:
        await att.save(path)
        async with READS:
            out = await run_agent1(path, {**env, "BEAR_SPEND_LEDGER": str(folder / "spend.jsonl")})
        path.with_suffix(".json").write_text(json.dumps(out, indent=1))
        text = reply_text(att.filename, out)
        if text:
            return await safe(msg.reply(text, mention_author=False))
        await safe(msg.reply(f"**Agent 1** · `{att.filename}`: too long for a message, it's in the file.",
                             file=discord.File(path.with_suffix(".json"), filename=f"{path.stem}.json"),
                             mention_author=False))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("part-id read failed for %s: %s", att.filename, e)
        await safe(msg.reply(f"**Agent 1** · `{att.filename}` failed:\n```\n{str(e)[-1500:]}\n```",
                             mention_author=False))


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
