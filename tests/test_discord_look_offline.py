#!/usr/bin/env python3
"""Offline checks for how the Discord bot's posts look (discordbot/look.py): every error code has
wording, every post fits Discord's limits, the folder marker still reads back, commands fit.
No Discord, no network, no cost.

usage: python3 tests/test_discord_look_offline.py
"""
import re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "discordbot"))
import look  # noqa: E402

CODES = ["BEAR-D01", "BEAR-D02", "BEAR-D03", "BEAR-D04", "BEAR-D05", "BEAR-D06", "BEAR-N01", "BEAR-N02",
         "BEAR-N03", "BEAR-K01", "BEAR-K02", "BEAR-T01", "BEAR-R01"]
# The pattern /run reads the marker back with (discordbot/folders.py MARKER).
MARKER = re.compile(r"^\N{FILE FOLDER} Folder \*\*([A-Za-z0-9][A-Za-z0-9_-]{0,39})\*\*")
CAR = "FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL"
fails = []


def check(what, ok):
    if not ok:
        fails.append(what)


def fits(what, post):
    L = look.LIMITS
    check(f"{what}: content too long", len(post["content"] or "") <= L["content"])
    check(f"{what}: too many embeds", 1 <= len(post["embeds"]) <= 10)
    total = 0
    for e in post["embeds"]:
        check(f"{what}: no colour", isinstance(e.get("color"), int))
        check(f"{what}: title", len(e.get("title", "")) <= L["title"])
        check(f"{what}: description", len(e.get("description", "")) <= L["description"])
        check(f"{what}: fields", len(e.get("fields", [])) <= L["fields"])
        for f in e.get("fields", []):
            check(f"{what}: field", len(f["name"]) <= L["field_name"] and len(f["value"]) <= L["field_value"])
        total += look.embed_length(e)
    check(f"{what}: embeds over 6000", total <= L["embed_total"])


for code in CODES:
    check(f"{code} has an uploader entry", code in look.UPLOADER_FIX)
    check(f"{code} has a title", code in look.TITLES)
    fits(code, look.problem_card("Q184", code, 1, ["https://discord.com/x"] * 30))
    fits(code, look.error_report("Q184", code, "meaning", "fix", 2, CAR, "x" * 5000, "https://discord.com/x"))
    check(f"{code} error report keeps the agreed first line",
          look.error_report("Q184", code, "m", "do this", 2)["content"].startswith(f"**Q184** encountered an issue — `{code}` — fix: do this"))
# D codes are for the uploader; the rest must not tell a phone user to edit .env or read logs.
for code, fix in look.UPLOADER_FIX.items():
    check(f"{code}: uploader text mentions settings", fix is None or (".env" not in fix and "log" not in fix))
    check(f"{code}: D codes need uploader text", (fix is not None) == code.startswith("BEAR-D"))
check("owner problem says nothing to do", "Nothing for you to do" in look.problem_card("Q1", "BEAR-N01", 9)["embeds"][0]["description"])
check("photo links capped at 10", look.problem_card("Q1", "BEAR-D04", 9, ["u"] * 14)["embeds"][0]["description"].count("[Photo") == 10)

m = MARKER.match(look.folder_card("Q184", CAR)["content"])
check("marker reads back", m and m.group(1) == "Q184")
fits("folder", look.folder_card("Q184", CAR, dev=True))
for state in ("checking", "waiting", "downloading", "queued", "running"):
    p = look.run_card(state, "Q184", CAR, parts=12, got=3, queue_ahead=2, since=1, max_runs=2, dev=True)
    fits(state, p)
    if state not in ("checking", "waiting"):
        check(f"{state} says Running x parts", "Running 12 parts" in p["embeds"][0]["title"])
check("1 part is singular", "Running 1 part " in look.run_card("running", "Q", CAR, parts=1)["embeds"][0]["title"] + " ")
check("checking before the folder is known", look.run_card("checking", None, CAR)["embeds"][0]["title"].endswith("Checking the folder"))
check("problem with no folder", "None" not in look.problem_card(None, "BEAR-D02", 9)["embeds"][0]["title"])
try:
    look.run_card("bogus", "Q", CAR)
    fails.append("unknown state accepted")
except ValueError:
    pass
fits("done", look.done_card("Q184", CAR, 12, 10, "Q184-ford-fiesta-mk7.xlsx", 9, dev=True))
check("done says 2 not priced", "2 not priced" in look.done_card("Q", CAR, 12, 10, "f.xlsx")["embeds"][0]["description"])
check("done all priced has no 'not priced'", "not priced" not in look.done_card("Q", CAR, 5, 5, "f.xlsx")["embeds"][0]["description"])
fits("status empty", look.status_card([], 2, 1000))
fits("status", look.status_card([{"folder": "Q1", "channel_id": 5, "state": "running", "parts": 3, "since": 0}] * 40, 2, 600))
fits("started", look.bot_started(2, "all_ok", "0.4"))
fits("guide", look.guide(9))
for key in look.REPLIES:
    text = look.reply(key, folder="Q1", state="running", name="Q1", first="2012")
    check(f"reply {key} fits", 0 < len(text) <= 2000)
for name, c in look.COMMANDS.items():
    check(f"/{name} name", re.fullmatch(r"[a-z0-9_-]{1,32}", name) is not None)
    check(f"/{name} description", 1 <= len(c["description"]) <= 100)
    check(f"/{name} options", all(1 <= len(d) <= 100 for d in c["options"].values()))
check("messages say folder, not box", "box" not in str([look.guide(), look.REPLIES, look.UPLOADER_FIX, look.TITLES]).replace("box of parts", ""))
check("agreed command names", set(look.COMMANDS) == {"newfolder", "run", "status"})

if fails:
    print("\n".join("FAIL " + f for f in fails))
    sys.exit(1)
print("discord look: all checks passed")
