"""Discord BEAR: the part check. Someone posts a photo of a part's number in any channel; the bot
replies with the number Agent 1 (bear2/stage1_read.py) reads off it, people tap ✅ if it's right
or fix it, and the answer goes in a text file (<storage>/checks/part-numbers.txt). No eBay
lookup, no spreadsheet: only the read, so the answer comes back in seconds.

Agent 1 runs as its own short process for each photo (like a /run, but one photo):
    python3 discordbot/partcheck.py <photo> "<car>"      prints one line of JSON
so the bot can always stop it after BEAR_CHECK_TIMEOUT seconds, and BEAR's spend cap counts one
photo. A person is waiting, so its limits are tighter than a /run's: CALL_TIMEOUT seconds per
model call and one retry (a /run allows 120 s and 6 tries), and when nothing is found upright the
three rotated re-reads run at the same time instead of one after another.

The rest of this file (which number to show, the other readings, the text file, the saved state
of each card) is kept free of discord.py so it can be tested offline (tests/test_discord_offline.py);
bot.py does the Discord side.
"""
import json, os, re, sys, time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CALL_TIMEOUT = 20   # seconds per model call
ATTEMPTS = 2        # one retry on a network error or rate limit
MAX_ALTS = 3        # other readings offered as buttons: with ✅ and ✏️ that is one row of 5
MAX_TYPED = 40
TYPED = re.compile(r"^[A-Z0-9][A-Z0-9 ./-]*$")
LOG_NAME = "part-numbers.txt"
LOG_HEADER = "time\tchannel\twho\tpart_number\tbear_read\thow\twait_s\tread_s\tphoto\tsaved_photo\n"
HOW = {"ok": "correct", "alt": "picked another reading", "fix": "typed"}

# Dev mode (BEAR_SIM set): a made-up read, no credit spent. BEAR_SIM=no_number or read_fails tries
# the other two outcomes.
SIM_READ = {"part_description": "rear door window regulator", "item_count": 1, "cost": 0, "candidates": [
    {"text": "82481-3Z000", "role": "primary", "legibility": "clear", "alt_readings": ["82481-3Z0O0"]},
    {"text": "82481-3Z010", "role": "secondary", "legibility": "partly clear", "alt_readings": []}]}


def norm(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def answer(read):
    """(the number to show or None, up to MAX_ALTS other readings) from an Agent 1 read: the first
    "primary" candidate, else the first one; then its look-alike readings, then the other numbers."""
    cands = [x for x in read.get("candidates") or [] if (x.get("text") or "").strip()]
    if not cands:
        return None, []
    best = next((x for x in cands if x.get("role") == "primary"), cands[0])
    others = list(best.get("alt_readings") or [])
    for x in cands:
        if x is not best:
            others += [x["text"], *(x.get("alt_readings") or [])]
    seen, alts = {norm(best["text"])}, []
    for t in others:
        t = (t or "").strip()
        if t and norm(t) not in seen and len(t) <= MAX_TYPED:
            seen.add(norm(t))
            alts.append(t)
    return best["text"].strip(), alts[:MAX_ALTS]


def typed(text):
    """A part number typed in the ✏️ box, tidied (upper case, single spaces), or None if it isn't one."""
    t = " ".join((text or "").upper().split())
    return t if t and len(t) <= MAX_TYPED and TYPED.fullmatch(t) else None


def save_pending(folder, card_id, rec):
    """The read behind a card, kept on disk until someone answers, so the buttons still work after
    the bot restarts."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{card_id}.json").write_text(json.dumps(rec))


def peek(folder, card_id):
    try:
        return json.loads((folder / f"{card_id}.json").read_text())
    except (OSError, ValueError):
        return None


def take(folder, card_id):
    """The card's read, removed so a second tap can't log it twice; None if it was already answered.
    No awaits in here: two taps at once can't both get it."""
    rec = peek(folder, card_id)
    if rec is not None:
        (folder / f"{card_id}.json").unlink(missing_ok=True)
    return rec


def log_answer(path, rec, number, how, who, when=None):
    """One line in the text file (tab-separated, header on the first line): when, where, who, the
    part number, what BEAR read, how it was answered, seconds from the photo to BEAR's answer and
    for the read alone, the photo's link and the saved copy."""
    clean = lambda v: " ".join(str(v if v is not None else "").split())   # noqa: E731  no tabs or newlines
    row = [(when or datetime.now()).astimezone().isoformat(timespec="seconds"), rec.get("channel"), who, number,
           rec.get("read") or "", HOW[how], rec.get("wait_s"), rec.get("read_s"), rec.get("photo_url"),
           rec.get("saved")]
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write((LOG_HEADER if new else "") + "\t".join(clean(v) for v in row) + "\n")


def read_lines(path):
    """The text file as dicts (for the tests and anyone looking at it from Python)."""
    lines = path.read_text().splitlines()
    keys = lines[0].split("\t")
    return [dict(zip(keys, l.split("\t"))) for l in lines[1:] if l.strip()]


def read(photo, car):
    """Agent 1 on one photo, with the live limits. Raises on failure."""
    sim = os.environ.get("BEAR_SIM")
    if sim:
        time.sleep(float(os.environ.get("BEAR_SIM_PAUSE", "0.15")))
        if sim == "read_fails":
            raise RuntimeError("simulated read failure")
        return {**SIM_READ, "candidates": [] if sim == "no_number" else SIM_READ["candidates"]}
    sys.path.insert(0, str(REPO / "bear2"))
    import concurrent.futures as cf
    import stage1_read as s1
    opts = {"attempts": ATTEMPTS, "timeout": CALL_TIMEOUT}
    d = s1.read_photo(photo, car, **opts)
    cost = d.get("_cost") or 0
    if not d.get("candidates"):
        # As stage1_read.read_photo_robust, but the three turns at once: one call's wait, not three.
        with cf.ThreadPoolExecutor(3) as ex:
            turned = dict(zip((90, 180, 270), ex.map(lambda r: s1.read_photo(photo, car, rotate=r, **opts),
                                                     (90, 180, 270))))
        extra = []
        for rot, r in turned.items():
            cost += r.get("_cost") or 0
            for cand in r.get("candidates") or []:
                cand["note"] = f"(read after rotating {rot}deg) " + (cand.get("note") or "")
                extra.append(cand)
            if not d.get("part_description") and r.get("part_description"):
                d["part_description"] = r["part_description"]
        d["candidates"], d["rotated"] = s1.dedupe(extra), True
    return {"candidates": d.get("candidates") or [], "part_description": d.get("part_description"),
            "item_count": d.get("item_count"), "rotated": bool(d.get("rotated")), "cost": cost}


def main():
    photo, car = sys.argv[1], sys.argv[2]
    started = time.time()
    try:
        out = read(photo, car)
    except Exception as e:
        out = {"error": f"{type(e).__name__}: {e}"[:600]}
    out["read_s"] = round(time.time() - started, 1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
