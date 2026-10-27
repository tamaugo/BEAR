#!/usr/bin/env python3
"""Offline checks for the Discord bot's own rules (no Discord, no network, no cost): finding the
folder, picking the photos BEAR gets, the BEAR-D errors, photo and spreadsheet names, the upload wait,
which error code a failed run gets, renaming (every photo, SKU names, splitting the zips), and
the shadow test's log, note and report, and the up/down monitor's URLs and notes, and the update log.

usage: python3 tests/test_discord_offline.py
"""
import os, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "discordbot"))
sys.path.insert(0, str(ROOT / "bear2"))
import folders as fo  # noqa: E402
import heartbeat as hb  # noqa: E402
import renames as rn  # noqa: E402
import shadow as sh  # noqa: E402

BOT, ALICE = NS(id=1, bot=True), NS(id=2, bot=False)
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
_n = [0]


def msg(author=ALICE, files=(), content="", ago=120):
    _n[0] += 1
    return NS(author=author, content=content, created_at=NOW - timedelta(seconds=ago),
              attachments=[NS(filename=f) for f in files], jump_url=f"https://discord.com/x/{_n[0]}",
              reactions=[NS(emoji="\N{THUMBS UP SIGN}")])


fails = []


def check(what, got, want):
    if got != want:
        fails.append(f"{what}: got {got!r}, want {want!r}")


def raises(what, fn, code):
    try:
        fn()
        fails.append(f"{what}: no error, want {code}")
    except fo.FolderError as e:
        check(what, e.code, code)


# Finding the folder: the latest marker posted by this bot wins; other people's look-alikes don't count.
old = msg(BOT, content=fo.marker("Q183"))
fake = msg(ALICE, content=fo.marker("FAKE"))
mark = msg(BOT, content=fo.marker("Q184"))
p1, label, p2 = msg(files=["IMG_1.jpg", "IMG_2.jpg"]), msg(files=["IMG_4821.JPG"]), msg(files=["b.png"])
reply = msg(BOT, content="Checking the folder ...", files=[])
history = [old, msg(files=["x.jpg"]), fake, mark, p1, label, p2, reply]
name, m, after = fo.split_folder(history[::-1], BOT.id)
check("folder name", name, "Q184")
check("folder messages", after, [p1, label, p2, reply])
check("no folder", fo.split_folder([p1, fake][::-1], BOT.id)[0], None)
check("marker round trip", fo.marker_name(msg(BOT, content=fo.marker("Box_7-a")), BOT.id), "Box_7-a")

# Picking the photos: every photo people posted is a part, in order, several to a message too.
picks = fo.part_photos(after)
check("every photo, in order", [a.filename for _, a in picks], ["IMG_1.jpg", "IMG_2.jpg", "IMG_4821.JPG", "b.png"])
check("webp accepted", [a.filename for _, a in fo.part_photos([msg(files=["c.webp"])])], ["c.webp"])
check("bot's own files ignored", len(fo.part_photos([msg(BOT, files=["r.jpg", "results.xlsx"]), label])), 1)
check("videos and other files ignored", len(fo.part_photos([msg(files=["clip.mov", "notes.pdf"]), label])), 1)
raises("no photos", lambda: fo.part_photos([reply, msg(content="hi")]), "BEAR-D03")
raises("only a video", lambda: fo.part_photos([msg(files=["clip.mp4"])]), "BEAR-D03")
heic = msg(files=["IMG_9.HEIC"])
raises("HEIC", lambda: fo.part_photos([label, heic]), "BEAR-D05")
try:
    fo.part_photos([label, heic])
except fo.FolderError as e:
    check("D05 says which message", heic.jump_url in e.detail, True)
check("BEAR and the bot read the same photo types", fo.PHOTO_EXT, __import__("common").PHOTO_EXT)

# Upload wait: the newest file from a person counts, not the bot's messages.
check("upload age", fo.seconds_since_last_upload([p1, msg(files=["n.jpg"], ago=5), msg(BOT, files=["r.xlsx"], ago=1)], NOW), 5)
check("no uploads", fo.seconds_since_last_upload([msg(content="x")], NOW), None)

# Names.
check("photo names", [fo.photo_name(i, f) for i, f in [(1, "IMG_4821.JPG"), (12, "image0.webp"), (100, "a.jpeg")]],
      ["001.jpg", "012.webp", "100.jpeg"])
import assemble  # noqa: E402
check("BEAR names carry no location or NULL codes", [fo.photo_name(i, "IMG_NSF_NULL.jpg") for i in (1, 2)],
      ["001.jpg", "002.jpg"])
check("BEAR keeps upload order", sorted([fo.photo_name(i, "x.jpg") for i in (10, 2, 1)], key=assemble.image_no),
      ["001.jpg", "002.jpg", "010.jpg"])
check("xlsx name", fo.xlsx_name("Q184", "FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL"), "Q184-ford-fiesta-mk7.xlsx")
check("folder names", [bool(fo.FOLDER_NAME.match(n)) for n in ["Q184", "box_2-b", "", "-x", "a b", "../x", "x" * 41]],
      [True, True, False, False, False, False, False])

# Results and error codes.
a2 = "001.jpg | 1810A001 | T | 45.99 | u\n002.jpg | FAILED | Agent 2 | No eBay Listing Found\n\n"
check("count results", fo.count_results(a2), (2, 1))
LOGS = [
    ("Qwen 3.8 Flash is unavailable: OpenRouter HTTP 429: rate-limited upstream. No names were written.", "BEAR-N01"),
    ("Qwen 3.8 Flash is unavailable: <urlopen error timed out> (simulated). No names were written.", "BEAR-N02"),
    ("Qwen 3.8 Flash gave a name BEAR can't use for 001.jpg: 'Relay 25252701'. No names were written.", "BEAR-N03"),
    ("Qwen 3.8 Flash is unavailable: OpenRouter HTTP 402: insufficient credits. No names were written.", "BEAR-K01"),
    ("RuntimeError: spend cap reached: $3.0100 this run (cap $3.00)", "BEAR-K02"),
    ("Traceback ...\nRuntimeError: simulated crash while pricing on eBay (BEAR_SIM=crash)", "BEAR-R01"),
]
for text, code in LOGS:
    check(f"classify {code}", fo.classify("5 photos to price.\nReading part numbers 4/4\n" + text), code)
check("partial: cap", fo.partial_problem('{"003.jpg": {"error": "RuntimeError: spend cap reached: $1"}}'), "BEAR-K02")
check("partial: clean", fo.partial_problem('{"003.jpg": {"s1": {}}}'), None)
rep = fo.error_report("Q184", "BEAR-D05", "<#9>", "x" * 5000)
check("error report format", (rep.startswith("**Q184** encountered an issue — `BEAR-D05` — fix: "), len(rep) <= 2000), (True, True))
check("every code has a meaning and a fix", all(len(v) == 2 and all(v) for v in fo.ERRORS.values()), True)

# Renaming: every photo people posted, in order, flags or not; other files and the bot's left out.
both = msg(files=["a.jpg", "b.HEIC", "clip.mov"])
photos, others = rn.all_photos([mark, p1, label, both, reply, msg(BOT, files=["r.jpg"])])
check("rename takes every photo", [a.filename for _, a in photos], ["IMG_1.jpg", "IMG_2.jpg", "IMG_4821.JPG", "a.jpg", "b.HEIC"])
check("rename leaves out other files", others, 1)
check("rename by content type", rn.is_image(NS(filename="photo", content_type="image/jpeg")), True)
check("rename names", [rn.new_name("MYSKU", i, f) for i, f in [(1, "IMG_4821.JPG"), (12, "x.webp"), (3, "noext")]],
      ["MYSKU-1.jpg", "MYSKU-12.webp", "MYSKU-3.jpg"])
check("zip names", [rn.zip_name("MYSKU", 1), rn.zip_name("MYSKU", 2)], ["MYSKU-1.zip", "MYSKU-2.zip"])
check("SKUs", [bool(rn.SKU.match(n)) for n in ["MYSKU", "AB-12_c", "", "-x", "a b", "../x", "x" * 41]],
      [True, True, False, False, False, False, False])
MB = 1024 * 1024
files = [(f"S-{i}.jpg", 3 * MB) for i in range(1, 8)]
plan, big = rn.plan_zips(files, 10 * MB)
check("zips split in order", plan, [[0, 1, 2], [3, 4, 5], [6]])
check("every zip fits", all(sum(files[i][1] + 100 for i in z) < 10 * MB for z in plan), True)
plan, big = rn.plan_zips([("S-1.jpg", MB), ("S-2.jpg", 11 * MB), ("S-3.jpg", MB)], 10 * MB)
check("too big for any zip", (plan, big), ([[0, 2]], [1]))
check("nothing to zip", rn.plan_zips([], 10 * MB), ([], []))
import tempfile, zipfile  # noqa: E402
with tempfile.TemporaryDirectory() as d:
    src = Path(d) / "x.jpg"
    src.write_bytes(b"\xff\xd8" + b"x" * 5000)
    rn.write_zip(Path(d) / "S-1.zip", [(src, "S-1.jpg"), (src, "S-2.jpg")])
    z = zipfile.ZipFile(Path(d) / "S-1.zip")
    check("zip holds the renamed photos", z.namelist(), ["S-1.jpg", "S-2.jpg"])
    check("zip is stored, not compressed", {i.compress_type for i in z.infolist()}, {zipfile.ZIP_STORED})
    real = (Path(d) / "S-1.zip").stat().st_size
    check("zip size planned right", real <= 2 * (5002 + rn.ENTRY_BYTES + 2 * 7) + rn.END_BYTES, True)
line = rn.log_line("car-1", "Q184", "MYSKU", "posted", 6, 1, "/x")
check("log line", line.rstrip("\n").split("\t")[1:], ["car-1", "Q184", "MYSKU", "posted", "6", "1", "/x"])

# --- Shadow test (shadow.py, shadow_report.py) ---
import csv, io, json, subprocess, tempfile  # noqa: E402
check("label + location asked together", list(sh.questions(True)), ["label", "loc"])
check("location only", list(sh.questions(False)), ["loc"])
check("location choices", list(sh.LOC_Q["criteria"]), ["NF", "OF", "NR", "OR", "NONE"])
check("answers read", sh.answers({"answers": {"label": {"noul": 0.8}, "loc": {"choice": "NF", "probabilities": {"NF": 0.9}}},
                                  "usage": {"cost": 0.0001}}),
      {"label": 0.8, "loc": "NF", "loc_p": {"NF": 0.9}, "cost": 0.0001})
check("location-only answers", sh.answers({"answers": {"loc": {"choice": "OR", "probabilities": {"OR": 1}}}})["label"], None)
try:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (3000, 1500), "white").save(buf, "JPEG")
    uri = sh.data_uri(buf.getvalue())
    import base64
    small = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    check("photo shrunk to 800px", small.size, (800, 400))
except ImportError:
    pass   # Pillow is in the server's .venv; the plain Mac python may not have it


def srow(marker, run, n, flagged, model=sh.LABEL_MODEL, label=0.9, loc="NF", p=0.9, channel="car-1"):
    return {"channel": channel, "folder": f"Q{marker}", "marker": marker, "run": run, "n": n, "flagged": flagged,
            "url": f"https://discord.com/{marker}/{n}", "model": model, "label": label if model == sh.LABEL_MODEL else None,
            "loc": loc, "loc_p": {loc: p}, "cost": 0.0001}


rows = [srow(1, "a", 1, False, label=0.2), srow(1, "a", 2, True),            # first run of folder 1
        srow(1, "b", 1, False, label=0.1), srow(1, "b", 2, True, label=0.95),  # /run again: replaces run a
        srow(1, "b", 2, True, model=sh.LOC_MODELS[0], loc="NR", p=0.6),
        srow(1, "b", 3, False, label=0.92),                                  # next to the 💸 photo
        srow(2, "c", 1, True, label=0.4, loc="OF", p=0.5),                   # a 💸 photo it would miss
        srow(2, "c", 1, True, model=sh.LOC_MODELS[0], loc="OF", p=0.7)]
check("newest run of each folder only", sorted((r["marker"], r["run"]) for r in sh.latest_runs(rows))[:1], [(1, "b")])
check("old run dropped", any(r["run"] == "a" for r in sh.latest_runs(rows)), False)
check("folders and 💸 photos counted", sh.counts(rows), (2, 2))
check("same marker in another channel is another folder", sh.counts(rows + [srow(1, "z", 1, True, channel="car-2")]), (3, 3))
check("no note before the first 300", sh.pings_due(299, 0), None)
check("note at 300", sh.pings_due(300, 0), 1)
check("no second note at 450", sh.pings_due(450, 1), None)
check("second note at 600", sh.pings_due(610, 1), 2)
check("note every N set in .env", sh.pings_due(4, 0, every=3), 1)

with tempfile.TemporaryDirectory() as d:
    log = Path(d) / "shadow.jsonl"
    sh.append(log, rows[:4])
    with open(log, "a") as f:
        f.write('{"cut short')   # a crash mid-line is skipped
    sh.append(log, rows[4:])
    check("log read back", len(sh.read_log(log)), len(rows))
    review, script = Path(d) / "review.csv", ROOT / "discordbot" / "shadow_report.py"
    out = subprocess.run([sys.executable, str(script), str(log), "--review", str(review)],
                         capture_output=True, text=True)
    check("report runs", out.returncode, 0)
    check("report: folders and 💸 photos", "2 folders, 2 💸 photos" in out.stdout, True)
    check("report: a miss at 0.5", "| 0.5 | 1 of 2 | 1 | 0 |" in out.stdout, True)
    table = list(csv.DictReader(open(review)))
    check("review: one row per 💸 photo", len(table), 2)
    for r in table:
        r["truth"] = "NF" if r["folder"] == "Q1" else "OF"
    with open(review, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    out = subprocess.run([sys.executable, str(script), str(log), "--truth", str(review)], capture_output=True, text=True)
    check("report with truth runs", out.returncode, 0)
    # Luna: NF 0.9 (right, sure) and OF 0.5 (right, not sure). Jev: NR 0.6 (wrong) and OF 0.7 (right).
    check("report: Luna at 0.5", "| gpt-6-luna-decisions | 0.5 | 2 | 0 | 0 |" in out.stdout, True)
    check("report: Jev at 0.5", "| jev-1.13 | 0.5 | 1 | 1 | 0 |" in out.stdout, True)
    check("report: confirmed by Jev", "| jev-1.13 | 2 | 0 | 0 |" in out.stdout, True)
    if out.returncode:
        print(out.stderr)

# Up/down monitor (heartbeat.py): healthchecks.io URLs, and nothing is sent when it isn't set up.
URL = "https://hc-ping.com/abc"
check("heartbeat up URL", hb.ping_url(URL + "/"), URL)
check("heartbeat down URL", hb.ping_url(URL, "fail"), URL + "/fail")
check("heartbeat every 10 minutes", hb.EVERY, 600)
check("update failed names the step", "Python packages" in hb.update_failed_text("Python packages"), True)
_saved = {k: os.environ.pop(k, None) for k in ("BEAR_HEARTBEAT_URL", "DISCORD_TOKEN", "ERROR_CHANNEL_ID")}
_env_file = hb.jev_client.ENV_FILE
with tempfile.TemporaryDirectory() as d:
    hb.jev_client.ENV_FILE = Path(d) / ".env"
    hb.jev_client.ENV_FILE.write_text("BEAR_HEARTBEAT_URL=PASTE_HERE\nDISCORD_TOKEN=\n")
    check("heartbeat placeholder is off", hb.setting("BEAR_HEARTBEAT_URL"), None)
    check("heartbeat off: no ping", hb.ping(), False)
    check("no token: nothing posted", hb.post_error("x"), False)
    hb.jev_client.ENV_FILE.write_text(f"BEAR_HEARTBEAT_URL={URL}\n")
    check("heartbeat URL read from .env", hb.setting("BEAR_HEARTBEAT_URL"), URL)
hb.jev_client.ENV_FILE = _env_file
os.environ.update({k: v for k, v in _saved.items() if v is not None})

# Update log: what changed since the last commit posted, a pull request under its own title, and
# the automatic version (VERSION's major.minor + merges since it last changed).
with tempfile.TemporaryDirectory() as d:
    g = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                  check=True, capture_output=True, text=True).stdout.strip()
    g("init", "-q", "-b", "main")
    Path(d, "VERSION").write_text("0.4.0\n")
    g("add", "VERSION"); g("commit", "-q", "-m", "Bump version to 0.4")
    first = g("rev-parse", "HEAD")
    for n, title in ((41, "Update log"), (42, "Faster runs")):
        g("checkout", "-q", "-b", f"pr{n}")
        Path(d, f"f{n}").write_text("x"); g("add", "."); g("commit", "-q", "-m", "work in progress")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", f"pr{n}", "-m", f"Merge pull request #{n} from tamaugo/pr{n}\n\n{title}")
    Path(d, "g").write_text("x"); g("add", "."); g("commit", "-q", "-m", "A direct commit")
    _repo, hb.REPO = hb.REPO, Path(d)
    check("changes since last posted", hb.changes(first, "HEAD"), [(None, "A direct commit"), (42, "Faster runs"), (41, "Update log")])
    check("first update log: just the latest", hb.changes(None, "HEAD"), [(None, "A direct commit")])
    check("automatic version", hb.version(), "0.4.3")
    _channel, hb.update_channel = hb.update_channel, lambda: None
    state = Path(d) / "last"
    check("nowhere to post: nothing posted", hb.update_log(state), False)
    check("nowhere to post: kept for next time", state.exists(), False)
    state.write_text(g("rev-parse", "HEAD") + "\n")
    check("same code: nothing posted", hb.update_log(state), False)
    hb.REPO, hb.update_channel = _repo, _channel

if fails:
    print("\n".join(fails))
    sys.exit(f"{len(fails)} failed")
print("all Discord bot checks passed")
