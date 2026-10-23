"""Discord BEAR: the bot's own rules (folders, 💸 photos, file names, error codes), kept free of
discord.py so they can be tested offline (tests/test_discord_offline.py).

Messages are anything shaped like a discord.py Message: .author (.id, .bot), .attachments
(.filename, .content_type), .reactions (.emoji), .created_at, .jump_url, .content.
"""
import re
from datetime import datetime, timezone
from pathlib import PurePath

MONEY = "\N{MONEY WITH WINGS}"   # 💸 flags the part-number photo
MARKER = re.compile(r"^\N{FILE FOLDER} Folder \*\*([A-Za-z0-9][A-Za-z0-9_-]{0,39})\*\*")
FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")   # same as bear2/common.py PHOTO_EXT

# code: (what went wrong, how to fix it). D = Discord side, N = name model, K = credit, R = anything else.
ERRORS = {
    "BEAR-D01": ("The channel has no topic, so BEAR doesn't know the car.",
                 "Put the vehicle text in the channel topic (make first, e.g. FORD FIESTA MK7 2012 1.4 DIESEL), then /run again."),
    "BEAR-D02": ("/run was used but no folder was started in this channel.",
                 "Use /newfolder first, upload the photos, then /run."),
    "BEAR-D03": ("No photo in the folder has the 💸 reaction.",
                 "Add 💸 to each part-number photo, then /run again."),
    "BEAR-D04": ("A 💸 message holds more than one photo, so BEAR can't tell which is the part number.",
                 "Post the part-number photo on its own, flag that one with 💸, then /run again."),
    "BEAR-D05": ("A 💸 file is not a photo BEAR can read (e.g. HEIC).",
                 "Re-upload it as JPG, PNG or WEBP, flag it with 💸, then /run again."),
    "BEAR-D06": ("A 💸 photo couldn't be downloaded from Discord.",
                 "/run again. If it keeps failing, re-upload that photo."),
    "BEAR-D07": ("The photos couldn't be renamed: one didn't download, or a zip couldn't be posted.",
                 "/rename again with the same SKU. If it keeps failing, re-upload that photo or look at the bot's log."),
    "BEAR-N01": ("The name model is rate limited.",
                 "Wait a few minutes and /run again, or set BEAR_NAME_MODEL in the server's .env to another name model."),
    "BEAR-N02": ("The name model is not responding.",
                 "/run again later, or set BEAR_NAME_MODEL in the server's .env to another name model."),
    "BEAR-N03": ("The name model gave part names BEAR can't use.",
                 "Set BEAR_NAME_MODEL in the server's .env to another name model, then /run again."),
    "BEAR-K01": ("OpenRouter refused: out of credit or the key's spend cap was reached (HTTP 402).",
                 "Top up OpenRouter or raise the key's cap, then /run again."),
    "BEAR-K02": ("BEAR's own spend cap for one folder was reached, so some parts were not priced.",
                 "Raise BEAR_RUN_CAP_USD in the server's .env, then /run again."),
    "BEAR-T01": ("The BEAR run took too long and was stopped.",
                 "/run again. If it happens again, the owner looks at the log."),
    "BEAR-R01": ("The BEAR run failed.",
                 "The owner looks at the attached log."),
}


class FolderError(Exception):
    """/run can't go ahead: one of the BEAR-D codes, with the messages it is about."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


def marker(name):
    return f"\N{FILE FOLDER} Folder **{name}**"


def marker_name(msg, bot_id):
    """The folder name if msg is one of this bot's /newfolder markers, else None."""
    if msg.author.id != bot_id:
        return None
    m = MARKER.match(msg.content or "")
    return m.group(1) if m else None


def split_folder(newest_first, bot_id):
    """(folder name, marker message, messages after it oldest first) from channel history read
    newest first; (None, None, []) if no folder was started."""
    after = []
    for msg in newest_first:
        name = marker_name(msg, bot_id)
        if name:
            return name, msg, after[::-1]
        after.append(msg)
    return None, None, []


def flagged(msg):
    return any(str(r.emoji) == MONEY for r in msg.reactions)


def is_photo(att):
    return PurePath(att.filename).suffix.lower() in PHOTO_EXT


def flagged_photos(messages):
    """[(message, attachment)] for every 💸 photo, oldest first. Raises FolderError D03/D04/D05.
    Bot messages and 💸 on messages with no file are ignored."""
    picks, many, unreadable = [], [], []
    for msg in messages:
        if msg.author.bot or not msg.attachments or not flagged(msg):
            continue
        if len(msg.attachments) > 1:
            many.append(msg)
        elif not is_photo(msg.attachments[0]):
            unreadable.append((msg, msg.attachments[0].filename))
        else:
            picks.append((msg, msg.attachments[0]))
    if many:
        raise FolderError("BEAR-D04", "\n".join(f"{len(m.attachments)} files: {m.jump_url}" for m in many))
    if unreadable:
        raise FolderError("BEAR-D05", "\n".join(f"{fn}: {m.jump_url}" for m, fn in unreadable))
    if not picks:
        raise FolderError("BEAR-D03")
    return picks


def seconds_since_last_upload(messages, now=None):
    """Seconds since the newest message with a file, or None if there is none."""
    times = [m.created_at for m in messages if m.attachments and not m.author.bot]
    if not times:
        return None
    return max(0.0, ((now or datetime.now(timezone.utc)) - max(times)).total_seconds())


def photo_name(i, filename):
    """001.jpg, 002.webp ... BEAR reads row order from the first number in the name and location
    from NSF/NSR/OSF/OSR words, so the Discord name (IMG_4821.jpg, image0.jpg) is never kept."""
    return f"{i:03d}{PurePath(filename).suffix.lower()}"


def slug(text, words=None):
    parts = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(parts[:words] if words else parts) or "car"


def xlsx_name(folder, car):
    """Q184-ford-fiesta-mk7.xlsx"""
    return f"{folder}-{slug(car, 3)}.xlsx"


def count_results(agent2_text):
    """(photos, priced) from agent2_results.md."""
    rows = [l for l in agent2_text.splitlines() if l.strip()]
    return len(rows), sum(1 for l in rows if " | FAILED | " not in l)


NAME_FAIL = re.compile(r"^(.+?) (is unavailable|gave an unusable answer|gave a name BEAR can't use)", re.M)


def classify(log):
    """The error code for a failed run, from its log (the same codes as the old web page)."""
    if "OpenRouter HTTP 402" in log:
        return "BEAR-K01"
    if "spend cap reached" in log:
        return "BEAR-K02"
    m = NAME_FAIL.search(log)
    if m and m.group(2) == "is unavailable":
        return "BEAR-N01" if re.search(r"HTTP 429|rate.?limit", log[m.start():], re.I) else "BEAR-N02"
    if m:
        return "BEAR-N03"
    return "BEAR-R01"


def partial_problem(trace_text):
    """A code for a run that finished but lost parts to running out of money, else None.
    run.py turns those errors into FAILED rows, so they only show in trace.json."""
    if "OpenRouter HTTP 402" in trace_text:
        return "BEAR-K01"
    if "spend cap reached" in trace_text:
        return "BEAR-K02"
    return None


def error_report(folder, code, where, detail=""):
    """The error channel message: **Q184** encountered an issue — `BEAR-D04` — fix: ..."""
    meaning, fix = ERRORS[code]
    text = f"**{folder}** encountered an issue — `{code}` — fix: {fix}\n{meaning} Channel: {where}"
    if detail:
        text += "\n```\n" + detail.replace("```", "'''")[:1400] + "\n```"
    return text[:2000]
