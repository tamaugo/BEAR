"""Discord BEAR: how everything the bot posts looks and reads. The bot (bot.py) decides *when* to
post; this file decides *what it looks like*. Kept free of discord.py so it can be tested offline
(tests/test_discord_look_offline.py) and drawn as a mockup (discordbot/mockup.py).

Every function returns a post: {"content": str or None, "embeds": [embed dict]}. Send it with
    await channel.send(**look.kwargs(post))      or      await message.edit(**look.kwargs(post))

The feel, in short (discordbot/FRONTEND.md has the full layout and reasoning):
- One live card per /run. It is edited through checking -> waiting -> downloading -> queued ->
  running -> done/failed, so a folder leaves one message in the car channel, not six.
- Colour says the state: grey = working, amber = waiting on you, green = done, red = problem.
- The car channel says only what the uploader can do. Anything the owner has to fix (name model,
  credit, logs) goes to the error channel, and the car channel just says "the owner has been told".
- Phone first: short lines, the action in bold, no walls of text.
"""
# Colours (the web page's palette: --brand, --ok, --error; plus Discord's own amber and grey).
BRAND = 0x9F3434
GREEN = 0x3DDC84
RED = 0xFF8A80
AMBER = 0xF0B232
GREY = 0x4E5058

BEAR = "\N{BEAR FACE}"
FOLDER = "\N{FILE FOLDER}"
TAG = "\N{LABEL}\N{VARIATION SELECTOR-16}"

# Slash commands: names are agreed, this is the text people see when they type "/".
# Discord's limit is 100 characters for each description.
COMMANDS = {
    "newfolder": {
        "description": "Start a new folder (one box of parts) in this car's channel",
        "options": {"name": "Folder name, e.g. Q184"},
    },
    "run": {
        "description": "Finish the folder and price every photo in it",
        "options": {},
    },
    "status": {
        "description": "See which folders BEAR is working on",
        "options": {},
    },
    "rename": {
        "description": "Rename every photo in this folder to SKU-1, SKU-2 ... and get them back as a zip",
        "options": {"sku": "The SKU the photos are named after, e.g. MYSKU"},
    },
    "quit": {
        "description": "Stop everything /run or /rename is doing in this channel",
        "options": {},
    },
}

# What the person in the car channel should do, per error code: short, phone-sized, no settings
# or log talk. None = nothing for them to do, the owner fixes it (see OWNER_FIX).
UPLOADER_FIX = {
    "BEAR-D01": "This channel has no car yet. Put the car in the **channel topic**, make first "
                "(e.g. `FORD FIESTA MK7 2012 1.4 DIESEL`), then try again.",
    "BEAR-D02": "There's no folder open here. Start one with **/newfolder**, upload the photos, then **/run**.",
    "BEAR-D03": "There are no photos in this folder yet. Upload the **part-number photos** below the folder, "
                "then **/run** again.",
    "BEAR-D05": "A photo below isn't one BEAR can read (iPhone HEIC?). Re-send it as a normal photo, "
                "**delete the original**, then **/run** again.",
    "BEAR-D06": "Discord didn't hand over a photo. **/run** again; if it keeps happening, re-send that photo.",
    "BEAR-D07": "The photos couldn't be renamed. **/rename** again with the same SKU; if it keeps happening, "
                "re-send the photo below.",
    "BEAR-N01": None, "BEAR-N02": None, "BEAR-N03": None,
    "BEAR-K01": None, "BEAR-K02": None, "BEAR-T01": None, "BEAR-R01": None,
}

# Short titles for the problem card, so the code means something at a glance.
TITLES = {
    "BEAR-D01": "No car in the channel topic",
    "BEAR-D02": "No folder open",
    "BEAR-D03": "No photos in the folder",
    "BEAR-D05": "Photo type BEAR can't read",
    "BEAR-D06": "A photo didn't download",
    "BEAR-D07": "Photos couldn't be renamed",
    "BEAR-N01": "Name model is busy",
    "BEAR-N02": "Name model isn't answering",
    "BEAR-N03": "Name model gave bad names",
    "BEAR-K01": "Out of OpenRouter credit",
    "BEAR-K02": "Folder hit BEAR's spend cap",
    "BEAR-T01": "Run took too long",
    "BEAR-R01": "BEAR run failed",
}

# Discord's limits: title 256, description 4096, field name 256, value 1024, footer 2048,
# 25 fields, 6000 characters per message across all embeds, 2000 for content.
LIMITS = {"title": 256, "description": 4096, "footer": 2048, "field_name": 256, "field_value": 1024,
          "fields": 25, "embed_total": 6000, "content": 2000}


def _cut(text, n):
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "\N{HORIZONTAL ELLIPSIS}"


def _embed(colour, title=None, description=None, fields=(), footer=None):
    e = {"color": colour}
    if title:
        e["title"] = _cut(title, LIMITS["title"])
    if description:
        e["description"] = _cut(description, LIMITS["description"])
    if fields:
        e["fields"] = [{"name": _cut(n, LIMITS["field_name"]), "value": _cut(v, LIMITS["field_value"]),
                        "inline": inline} for n, v, inline in list(fields)[: LIMITS["fields"]]]
    if footer:
        e["footer"] = {"text": _cut(footer, LIMITS["footer"])}
    return e


def _post(embed, content=None):
    return {"content": _cut(content, LIMITS["content"]) if content else None, "embeds": [embed]}


def _footer(dev=False, extra=None):
    bits = [extra] if extra else []
    if dev:
        bits.append("DEV MODE: simulated, no credit spent")
    return " · ".join(bits) or None


def _when(unix):
    """Discord shows <t:...:R> as "3 minutes ago" in each person's own time zone, and keeps it fresh."""
    return f"<t:{int(unix)}:R>"


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def kwargs(post):
    """Turn a post into channel.send / message.edit arguments (the only place discord.py is needed)."""
    import discord
    return {"content": post["content"], "embeds": [discord.Embed.from_dict(e) for e in post["embeds"]]}


# --- Folder marker -------------------------------------------------------------------------------

def folder_card(name, car, dev=False):
    """The /newfolder reply. The content line must stay exactly "📁 Folder **<name>**": /run finds the
    folder by reading it back (folders.MARKER)."""
    how = ("**1.** Upload the **part-number photos**, any way you like\n"
           "**2.** **/run** when the folder is done")
    return _post(_embed(BRAND, description=f"**{car}**\n\n{how}", footer=_footer(dev, "Every photo is one part")),
                 content=f"{FOLDER} Folder **{name}**")


def open_folder_warning(previous):
    """Ephemeral note on /newfolder when the folder before it was never /run (its photos would be skipped)."""
    return (f"Heads up: folder **{previous}** was never run. **/run** now uses this new folder. "
            f"To price the earlier photos, upload them again below this folder's marker, then **/run**.")


# --- The live run card ---------------------------------------------------------------------------
# One message per /run, edited as it goes. Make it with run_card("checking", ...) and edit it with
# the next state. done_card / problem_card are the last edit.

def run_card(state, folder, car, parts=None, got=None, queue_ahead=None, since=None,
             wait_seconds=None, max_runs=None, dev=False):
    """state: checking | waiting | downloading | queued | running. folder is None while /run is
    still looking for it."""
    p = _plural(parts, "part") if parts is not None else None
    if state == "checking":
        title = f"{FOLDER} {folder} · Checking the folder" if folder else f"{FOLDER} Checking the folder"
        colour, line = GREY, "Looking for photos ..."
    elif state == "waiting":
        title, colour = f"{FOLDER} {folder} · Waiting for uploads", AMBER
        line = (f"Photos are still arriving. BEAR starts once none have come in for "
                f"{wait_seconds or 30} seconds.")
    elif state == "downloading":
        title, colour = f"{FOLDER} {folder} · Running {p}", GREY
        line = f"Saving the photos ... {got or 0}/{parts}"
    elif state == "queued":
        title, colour = f"{FOLDER} {folder} · Running {p}", AMBER
        ahead = f"{_plural(queue_ahead, 'folder')} ahead" if queue_ahead else "next in line"
        line = f"Queued: {ahead}. BEAR prices {max_runs or 2} folders at once."
    elif state == "running":
        title, colour = f"{FOLDER} {folder} · Running {p}", GREY
        line = f"{BEAR} BEAR is pricing the parts" + (f" (started {_when(since)})" if since else "") + "."
    else:
        raise ValueError(f"unknown run state {state!r}")
    desc = f"**{car}**\n{line}"
    if parts is not None and state in ("downloading", "queued", "running"):
        desc += (f"\n\n*Uploaded more than {p}? Some photos aren't in this folder. "
                 f"Add them and **/run** again once this one is done.*")
    return _post(_embed(colour, title, desc, footer=_footer(dev)))


def done_card(folder, car, parts, priced, filename, minutes=None, dev=False):
    """Last edit of the run card when the spreadsheet is ready. The spreadsheet itself is attached to
    the same message (or posted right under it if the card can't take a file)."""
    missed = parts - priced
    lines = [f"**{car}**",
             f"BEAR priced **{priced} of {parts}** parts" + (f" ({missed} not priced)" if missed else "") + ".",
             f"Spreadsheet: `{filename}`"]
    extra = f"took {minutes} min" if minutes is not None else None
    return _post(_embed(GREEN, f"\N{WHITE HEAVY CHECK MARK} {folder} · Done", "\n".join(lines),
                        footer=_footer(dev, extra)))


def problem_card(folder, code, error_channel_id, photo_links=(), dev=False, partial=False):
    """Last edit of the run card (or a new message) when something went wrong.
    photo_links: jump URLs of the exact photos that caused a D05/D06, so a phone user can tap to them.
    partial=True: the spreadsheet was posted but some parts were lost to this problem."""
    fix = UPLOADER_FIX.get(code)
    if fix is None:
        fix = (f"Nothing for you to do: the owner has been told in <#{error_channel_id}>. "
               + ("The rest of the spreadsheet is fine." if partial else "Your photos are saved."))
    desc = fix
    if photo_links:
        shown = list(photo_links)[:10]
        desc += "\n\n" + "\n".join(f"\N{BLACK RIGHT-POINTING TRIANGLE} [Photo {i}]({u})"
                                    for i, u in enumerate(shown, 1))
        if len(photo_links) > len(shown):
            desc += f"\n... and {len(photo_links) - len(shown)} more (see <#{error_channel_id}>)"
    name = f"{folder} · " if folder else ""
    title = f"\N{CROSS MARK} {name}{TITLES.get(code, 'Problem')}" if not partial else \
        f"\N{WARNING SIGN} {name}Some parts not priced"
    return _post(_embed(RED if not partial else AMBER, title, desc, footer=_footer(dev, code)))


def stopped_card(folder, dev=False):
    """Last edit of the run card after /quit."""
    name = f"{folder} · " if folder else ""
    return _post(_embed(RED, f"\N{BLACK SQUARE FOR STOP} {name}Stopped",
                        "Stopped with **/quit**: nothing more is posted for this folder. **/run** starts it again.",
                        footer=_footer(dev)))


# --- Renaming the photos -------------------------------------------------------------------------
# A second card next to the run card (or on its own for /rename), edited as it goes:
# offer -> skipped, or waiting -> saving -> posting -> done / nothing / stopped.

def rename_card(state, sku=None, folder=None, deadline=None, photos=None, got=None, zips=None,
                first=None, last=None, others=0, too_big=(), alone=False, dev=False):
    """alone=True for /rename on its own (no spreadsheet to wait for)."""
    tag = f"{TAG} {sku} · " if sku else f"{TAG} "
    if state == "offer":
        return _post(_embed(AMBER, f"{TAG} Rename the photos?",
                            "Tap **Rename photos** and type a SKU. Every photo in this folder comes back "
                            "named `SKU-1`, `SKU-2` ... in a zip, after the spreadsheet.\n"
                            f"Closes {_when(deadline)}. Leave it and the photos aren't renamed.",
                            footer=_footer(dev, "/quit stops the whole run")))
    if state == "skipped":
        return _post(_embed(GREY, f"{TAG} Not renamed", "No SKU given, photos not renamed.", footer=_footer(dev)))
    if state == "stopped":
        return _post(_embed(RED, f"\N{BLACK SQUARE FOR STOP} {tag}Stopped",
                            "Stopped with **/quit**: no zip will be posted.", footer=_footer(dev)))
    if state == "nothing":
        where = f"folder **{folder}**" if folder else "this folder"
        return _post(_embed(GREY, f"{tag}Nothing to rename", f"There are no photos in {where}.",
                            footer=_footer(dev)))
    if state == "waiting":
        line = "Waiting for the folder's photos ..."
    elif state == "saving":
        line = f"Saving the photos ... {got or 0}/{photos}"
    elif state == "posting":
        line = "Posting the zip ..." if alone else "Zip ready. It's posted after the spreadsheet."
    elif state == "done":
        lines = [f"Folder **{folder}**: `{first}` to `{last}`." if photos > 1 else f"Folder **{folder}**: `{first}`.",
                 f"In {_plural(zips, 'zip')} below, from `{sku}-1.zip`." if zips else "No zip: see below."]
        if others:
            lines.append(f"{_plural(others, 'file')} that isn't a photo was left out." if others == 1
                         else f"{others} files that aren't photos were left out.")
        if too_big:
            shown = ", ".join(f"`{n}`" for n in list(too_big)[:10])
            lines.append(f"Too big for Discord, kept on the server: {shown}"
                         + (f" and {len(too_big) - 10} more" if len(too_big) > 10 else "") + ".")
        return _post(_embed(GREEN, f"{TAG} {sku} · {_plural(photos, 'photo')} renamed",
                            "\n".join(lines), footer=_footer(dev)))
    else:
        raise ValueError(f"unknown rename state {state!r}")
    title = f"{tag}Renaming {_plural(photos, 'photo')}" if photos else f"{tag}Renaming"
    return _post(_embed(GREY, title, line, footer=_footer(dev)))


def zip_post(sku, n, total, first, last):
    """The line on each zip message: MYSKU-1.zip (1 of 2): MYSKU-1.jpg to MYSKU-14.jpg."""
    span = f"`{first}` to `{last}`" if first != last else f"`{first}`"
    return {"content": _cut(f"{TAG} **{sku}-{n}.zip** ({n} of {total}): {span}", LIMITS["content"]), "embeds": []}


# --- Error channel -------------------------------------------------------------------------------

def error_report(folder, code, meaning, fix, channel_id, car=None, detail="", jump_url=None, dev=False):
    """The error channel post. meaning/fix are the owner-facing text (folders.ERRORS). The content
    line keeps the agreed format so it reads right in notifications and search:
    **Q184** encountered an issue — `BEAR-D05` — fix: ..."""
    content = f"**{folder}** encountered an issue — `{code}` — fix: {fix}"
    fields = [("Car channel", f"<#{channel_id}>" + (f" · [jump to the folder]({jump_url})" if jump_url else ""), True)]
    if car:
        fields.append(("Car", car, True))
    desc = meaning
    if detail:
        desc += "\n```\n" + detail.replace("```", "'''")[:1400] + "\n```"
    return _post(_embed(RED, f"{TITLES.get(code, 'Problem')} · {code}", desc, fields, _footer(dev)), content=content)


def bot_started(max_runs, sim=None, version=None):
    """Error channel, each time the bot starts (after an update, a restart or a crash)."""
    lines = [f"**Version {version}**" if version else None,
             f"Ready to price {_plural(max_runs, 'folder')} at once.",
             f"**Dev mode**: runs are simulated (`{sim}`), no credit is spent." if sim else None,
             "Anything that was running before this needs **/run** again."]
    return _post(_embed(GREEN, "\N{LARGE GREEN CIRCLE} BEAR is up", "\n".join(l for l in lines if l)))


REPO_URL = "https://github.com/tamaugo/BEAR"


def update_log(changes, version=None, more=0):
    """#update-log, after setup.sh updated the bot (heartbeat.py). changes: [(pull request number
    or None, title)], newest first; more: how many older ones didn't fit."""
    lines = [f"\N{BULLET} [#{n}]({REPO_URL}/pull/{n}) {title}" if n else f"\N{BULLET} {title}"
             for n, title in changes]
    if more:
        lines.append(f"... and {_plural(more, 'older change')}")
    return _post(_embed(GREEN, f"{BEAR} BEAR updated" + (f" to {version}" if version else ""),
                        "\n".join(lines) or "Nothing new in the code."))


def shadow_ping(folders, parts, log_path, user_id=None):
    """The shadow test (shadow.py) has enough new data to look at."""
    lines = [f"The shadow test has logged **{_plural(parts, 'part photo')}** from **{_plural(folders, 'folder')}**. "
             "Time to look at whether a model could read the locations.",
             f"On the server: `/opt/bear/.venv/bin/python /opt/bear/discordbot/shadow_report.py {log_path}`, "
             "or send that file to Claude.",
             "It keeps collecting. Turn it off with `BEAR_SHADOW=0` in `.env` (no restart)."]
    return _post(_embed(AMBER, "\N{TEST TUBE} Shadow test: time to look at the data", "\n\n".join(lines)),
                 content=f"<@{user_id}>" if user_id else None)


# --- /status -------------------------------------------------------------------------------------

def status_card(active, max_runs, now, dev=False):
    """active: [{"folder", "channel_id", "state", "parts", "since"}]."""
    if not active:
        return _post(_embed(GREY, f"{BEAR} Nothing running",
                            f"BEAR can price {_plural(max_runs, 'folder')} at once.", footer=_footer(dev)))
    rows = []
    for a in active:
        mins = int((now - a["since"]) // 60)
        parts = f" · {_plural(a['parts'], 'part')}" if a.get("parts") else ""
        rows.append(f"**{a['folder']}** in <#{a['channel_id']}> · {a['state']}{parts} · {mins} min")
    running = sum(1 for a in active if a["state"] == "running")
    return _post(_embed(GREY, f"{BEAR} {running} of {max_runs} running", "\n".join(rows), footer=_footer(dev)))


# --- Small replies -------------------------------------------------------------------------------
# Only the person who typed the command sees these (ephemeral), so they never clutter the channel.

REPLIES = {
    "not_car_channel": "Use this in a car's channel (the ones under **Cars**).",
    "bad_name": "Folder names are letters, numbers, `-` and `_` only, up to 40, e.g. `Q184`.",
    "busy": "Folder **{folder}** here is still {state}. **/run** again once it's done.",
    "no_topic": "Folder **{name}** not started: this channel has no car in its topic yet.",
    "topic_order": "Check this channel's topic: it should start with the make (e.g. `FORD ...`), not "
                   "`{first}`. BEAR uses the first word as the make.",
    "on_it": "On it: the card below shows how it's going.",
    "oops": "Something went wrong on BEAR's side (`BEAR-R01`). The owner can see it in the bot's log.",
    "text_removed": "Only photos stay in car channels, so your message was removed. "
                    "Use **/newfolder**, photos and **/run**.",
    "bad_sku": "SKUs are letters, numbers, `-` and `_` only, up to 40, e.g. `MYSKU`.",
    "too_late": "Too late: renaming closed after {wait} seconds. Use **/rename** to rename the photos.",
    "sku_ok": "Got it: the photos will be named **{sku}-1**, **{sku}-2** ...",
    "rename_on_it": "Renaming the photos as **{sku}-1**, **{sku}-2** ...: the card below shows how it's going.",
    "quit_none": "Nothing is running in this channel.",
    "quit_done": "Stopping {what}.",
}


def reply(key, **values):
    return REPLIES[key].format(**values)


# --- Pinned guide --------------------------------------------------------------------------------

def guide(error_channel_id=None):
    """The how-to, pinned in #how-to-bear (and worth pinning in each car channel)."""
    steps = (
        "**1. One channel per car.** The **channel topic** is the car, make first:\n"
        "`FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL`\n\n"
        "**2. /newfolder** `Q184` opens a folder. Everything after it belongs to that folder.\n\n"
        "**3. Upload the part-number photos** in any groups you like. Only part-number photos: "
        "every photo is priced as one part.\n\n"
        "**4. /run** when the folder is done. BEAR says how many parts it found, then posts the "
        "spreadsheet. If that number is lower than you expect, a photo is missing."
    )
    tips = ("Text messages are removed: car channels are photos only.\n"
            "**/run** again re-does the whole folder.\n"
            "**/rename** renames every photo to `SKU-1`, `SKU-2` ... and posts them as a zip.\n"
            "**/quit** stops whatever is running in the channel.\n"
            "**/status** shows what BEAR is working on.")
    if error_channel_id:
        tips += f"\nProblems also go to <#{error_channel_id}>."
    return _post(_embed(BRAND, f"{BEAR} How to use BEAR", steps, [("Good to know", tips, False)]))


# --- Helpers for checks and the mockup ------------------------------------------------------------

def embed_length(e):
    """Characters Discord counts toward its 6000 per-message embed limit."""
    n = len(e.get("title", "")) + len(e.get("description", "")) + len(e.get("footer", {}).get("text", ""))
    return n + sum(len(f["name"]) + len(f["value"]) for f in e.get("fields", []))

