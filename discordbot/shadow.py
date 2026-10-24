"""Discord BEAR: the shadow test. It runs after each /run and changes nothing people see.

Every photo in the folder goes to a Decisions model (OpenRouter's Decisions API) with two
questions: is this the part-number photo, and which location is handwritten on the part (NF, OF,
NR or OR, as staff write it). On the 💸 photos two more Decisions models answer the location
question, to test using a second model to confirm the first. Staff's 💸 reactions are the right
answers to the first question, so after enough folders shadow_report.py can say whether a model
could find the part-number photos on its own, and which model reads the locations best.

One line per photo per model goes in <storage>/shadow/shadow.jsonl. Nothing is posted, except a
note in the error channel each time another BEAR_SHADOW_PING_PARTS 💸 photos have been logged
(300 by default), so the owner remembers to look. Kept free of discord.py so it can be tested
offline (tests/test_discord_offline.py); bot.py does the Discord side.
"""
import base64, io, json
from datetime import datetime

LABEL_MODEL = "openai/gpt-6-luna-decisions"          # every photo, both questions
LOC_MODELS = ("typesafe/jev-1.13", "cloudflare/clef")   # 💸 photos only, the location question
MAX_SIDE = 800   # Jev refuses 1600px photos; Luna read the one test photo best at 800 (2026-10-24)
PING_EVERY = 300
LOCATIONS = {"NF": "Near Side Front", "OF": "Off Side Front", "NR": "Near Side Rear", "OR": "Off Side Rear"}

LABEL_Q = {"type": "noul",
           "instructions": "Is this the part-number photo: a close, readable shot of this part's own label, "
                           "sticker, stamp or printed number that identifies it? Text in the background, on "
                           "other parts, on boxes or on stock tags does not count.",
           "criteria": {"true": "a close, readable shot of the part's own part-number label or stamp",
                        "false": "another angle of the part, or only background or unreadable text"}}
LOC_Q = {"type": "choice",
         "instructions": "Someone may have handwritten a location code on this car part in marker pen (often "
                         "messy). Which code is written? Ignore printed part numbers and logos.",
         "criteria": {**{code: f"{code} handwritten: {name.lower()}" for code, name in LOCATIONS.items()},
                      "NONE": "no handwritten location code"}}


def questions(with_label):
    return {"label": LABEL_Q, "loc": LOC_Q} if with_label else {"loc": LOC_Q}


def data_uri(raw, max_side=MAX_SIDE):
    """A photo's bytes as a JPEG data URI, upright and at most max_side pixels (as bear2/common.img_data_uri)."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def state(uri):
    # A chat-style image_url part is read as a picture (bear2/stage2b_rescue.py).
    return [{"type": "text", "text": "Photo of one used car part."},
            {"type": "image_url", "image_url": {"url": uri}}]


def answers(response):
    """{"label": chance it is the part-number photo or None, "loc": top code, "loc_p": {code: chance}, "cost"}"""
    a = response.get("answers", {})
    loc = a.get("loc") or {}
    return {"label": (a.get("label") or {}).get("noul"), "loc": loc.get("choice"),
            "loc_p": loc.get("probabilities"), "cost": (response.get("usage") or {}).get("cost")}


def check(model, uri, with_label):
    """Ask one model about one photo. Never raises: a failure comes back as {"error": ...}."""
    try:
        import jev_client
        return answers(jev_client.call_decisions(model, state(uri), questions(with_label), timeout=60))
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def record(base, n, file, url, flagged, model, result):
    """One line of shadow.jsonl."""
    return {"t": datetime.now().astimezone().isoformat(timespec="seconds"), **base, "n": n, "file": file,
            "url": url, "flagged": flagged, "model": model, **result}


def append(path, records):
    """Add lines to the log. A line cut short by a crash is ended first, so it can't swallow the next."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab+") as f:   # appends always go to the end, whatever seek says
        cut = False
        if f.seek(0, 2):
            f.seek(-1, 2)
            cut = f.read(1) != b"\n"
        f.write((b"\n" if cut else b"") + "".join(json.dumps(r) + "\n" for r in records).encode())


def read_log(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass   # a line cut short by a crash
    return out


def latest_runs(records):
    """Only the newest run of each folder: /run again replaces the earlier answers (the 💸 flags
    were usually fixed in between)."""
    newest = {}
    for r in records:
        key = (r.get("channel"), r.get("marker"))
        newest[key] = max(newest.get(key, ""), r.get("run", ""))
    return [r for r in records if r.get("run", "") == newest[(r.get("channel"), r.get("marker"))]]


def counts(records):
    """(folders, 💸 photos) in the log, counting each folder's newest run only."""
    rows = [r for r in latest_runs(records) if r.get("model") == LABEL_MODEL]
    return len({(r.get("channel"), r.get("marker")) for r in rows}), sum(1 for r in rows if r.get("flagged"))


def pings_due(parts, done, every=PING_EVERY):
    """How many pings there should have been by now (one per `every` 💸 photos), if more than done."""
    level = parts // max(1, every)
    return level if level > done else None
