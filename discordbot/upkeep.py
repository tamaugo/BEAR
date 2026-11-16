"""Discord BEAR: looking after itself. Kept free of discord.py so it can be tested offline
(tests/test_discord_offline.py); bot.py does the Discord side and look.py the wording.

  The usage log     <storage>/usage/usage.jsonl, kept for good: one line per /run (when, channel,
                    folder, parts, priced, cost in US dollars, how it ended) and one per update.
                    summary() adds it up per day and per week (weeks start on Monday, UK time) for
                    the weekly summary and /summary. #part-id's spend comes from its own ledger.
  Housekeeping      a run's photos (and the zips they came in) are deleted from the server after
                    BEAR_KEEP_DAYS days (4). They stay in Discord, and /run downloads them again.
                    The spreadsheet, the logs, the reads and photos.tsv are kept.
  Disk              how much room is left where the runs are kept.
  eBay calls        today's count (bear2/common.py counts them), against eBay's daily allowance.
  Health            do the OpenRouter and eBay keys still work, and how much credit is left.

Nothing here prints, logs or returns a key.
"""
import json, shutil, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import jev_client  # noqa: E402  (the .env reader BEAR itself uses)

try:
    from zoneinfo import ZoneInfo
    UK = ZoneInfo("Europe/London")
except Exception:   # no time zone data: UTC
    UK = timezone.utc

KEEP_DAYS = 4            # BEAR_KEEP_DAYS: days a run's photos stay on the server (0 = for good)
DISK_WARN_PERCENT = 10   # the error channel hears when less than this much of the disk is free
EBAY_DAILY_LIMIT = 5000  # BEAR_EBAY_DAILY_LIMIT: eBay's Browse API allowance per day
EBAY_WARN_AT = 0.8       # the error channel hears at this share of it
CREDIT_WARN_USD = 1.0    # ... and when OpenRouter has less credit than this left
OPENROUTER = "https://openrouter.ai/api/v1"


# --- The usage log -------------------------------------------------------------------------------

def usage_dir(storage):
    return Path(storage) / "usage"


def record(storage, kind, **fields):
    """Add one line to the usage log. Never raises: a run matters more than its line."""
    try:
        usage_dir(storage).mkdir(parents=True, exist_ok=True)
        with (usage_dir(storage) / "usage.jsonl").open("a") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, **fields}) + "\n")
        return True
    except OSError:
        return False


def read_lines(path):
    """The JSON lines of a file, skipping any that are damaged; [] if it isn't there."""
    out = []
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("t"), (int, float)):
            out.append(d)
    return out


def spend_total(path):
    """What a spend ledger (spend.jsonl) adds up to, in US dollars."""
    return sum(float(d.get("cost") or 0) for d in read_lines(path))


def load_state(storage):
    try:
        d = json.loads((usage_dir(storage) / "state.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(storage, state):
    try:
        usage_dir(storage).mkdir(parents=True, exist_ok=True)
        tmp = usage_dir(storage) / "state.json.tmp"
        tmp.write_text(json.dumps(state))
        tmp.replace(usage_dir(storage) / "state.json")
    except OSError:
        pass


def uk_now():
    return datetime.now(UK)


def week_start(now):
    """The Monday this week started on, at midnight UK time (owner, 2026-11-16: weeks start on Monday)."""
    day = now.astimezone(UK).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())   # Monday is 0


def summary(storage, now=None, whole_week=False):
    """What BEAR did and cost over a week, from the usage log and #part-id's ledger.
    whole_week=False (/summary): this week so far, Monday to now, compared with last week up to
    the same day and time, so a Wednesday is compared with last week's Monday to Wednesday.
    whole_week=True (the weekly post): the week that just ended, compared with the one before it.
    Dev-mode runs (simulated, no credit) are left out. Money is in US dollars, as OpenRouter bills."""
    now = (now or uk_now()).astimezone(UK)
    start = week_start(now)
    if whole_week:
        start, end = start - timedelta(days=7), start
    else:
        end = now
    before = (start - timedelta(days=7), end - timedelta(days=7))
    log = read_lines(usage_dir(storage) / "usage.jsonl")
    partid = read_lines(Path(storage) / "part-id" / "spend.jsonl")

    def between(rows, a, b):
        return [r for r in rows if a.timestamp() <= r["t"] < b.timestamp()]

    def totals(a, b):
        runs = [r for r in between(log, a, b) if r.get("kind") == "run" and not r.get("dev")]
        ids = between(partid, a, b)
        return {"runs": len(runs), "parts": sum(int(r.get("parts") or 0) for r in runs),
                "priced": sum(int(r.get("priced") or 0) for r in runs),
                "run_cost": sum(float(r.get("cost") or 0) for r in runs),
                "partid_cost": sum(float(r.get("cost") or 0) for r in ids),
                "partid_photos": sum(1 for r in ids if str(r.get("tag") or "").startswith("partid:") and r.get("kind") == "chat"),
                "updates": sum(1 for r in between(log, a, b) if r.get("kind") == "update")}
    this, last = totals(start, end), totals(*before)
    for t in (this, last):
        t["cost"] = t["run_cost"] + t["partid_cost"]
    days, day = [], start
    while day < end:
        nxt = min(day + timedelta(days=1), end)
        d = totals(day, nxt)
        days.append({"day": day.strftime("%a %d %b"), "runs": d["runs"], "parts": d["parts"],
                     "cost": d["run_cost"] + d["partid_cost"]})
        day = day + timedelta(days=1)
    change = None if last["cost"] <= 0 else round((this["cost"] - last["cost"]) / last["cost"] * 100)
    return {**this, "whole_week": whole_week, "start": start, "end": end, "days": days, "last": last,
            "change": change, "all_time": sum(float(r.get("cost") or 0) for r in log if r.get("kind") == "run" and not r.get("dev"))
            + sum(float(r.get("cost") or 0) for r in partid)}


# --- Housekeeping --------------------------------------------------------------------------------

def tree_bytes(path):
    total = 0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def clear_old_photos(storage, keep_days=KEEP_DAYS, now=None, busy=()):
    """Delete photos/ and zips/ from every run folder older than keep_days (by photos.tsv, written
    when its photos were downloaded). Returns (run folders cleared, bytes freed). keep_days 0 or
    less: nothing is deleted. busy: run folders in use now, never touched. Only folders /run made
    (they hold photos.tsv) are looked at: renames, #part-id and the shadow data are left alone."""
    if keep_days <= 0:
        return 0, 0
    cutoff = (now or time.time()) - keep_days * 86400
    busy = {Path(b).resolve() for b in busy}
    cleared = freed = 0
    for note in Path(storage).glob("*/*/photos.tsv"):
        run = note.parent
        try:
            if note.stat().st_mtime >= cutoff or run.resolve() in busy:
                continue
        except OSError:
            continue
        did = False
        for name in ("photos", "zips"):
            d = run / name
            if d.is_dir() and not d.is_symlink():
                freed += tree_bytes(d)
                shutil.rmtree(d, ignore_errors=True)
                did = True
        cleared += did
    return cleared, freed


def disk(storage):
    """(GB free, percent free) where the runs are kept; (None, None) if it can't be read."""
    try:
        u = shutil.disk_usage(storage)
    except OSError:
        return None, None
    return u.free / 2**30, u.free / u.total * 100 if u.total else 0.0


# --- eBay calls ----------------------------------------------------------------------------------

def ebay_calls(cache, day=None):
    """How many eBay API calls BEAR made today (UTC): bear2/common.py adds a byte per call."""
    day = day or time.strftime("%Y-%m-%d", time.gmtime())
    try:
        return (Path(cache) / f"calls-ebay-{day}.count").stat().st_size
    except OSError:
        return 0


def prune_ebay_counts(cache, keep_days=14, now=None):
    cutoff = (now or time.time()) - keep_days * 86400
    for f in Path(cache).glob("calls-ebay-*.count"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


# --- Health --------------------------------------------------------------------------------------

def _get_json(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def openrouter(get=_get_json, key=None):
    """{"ok", "text", "spent", "left"}: does the OpenRouter key work, what it has spent so far (US
    dollars, all time) and how much credit is left (None when OpenRouter doesn't say). The credit
    is the smaller of the key's own limit and the account's balance, whichever OpenRouter reports."""
    try:
        key = key or jev_client.resolve_api_key()
    except RuntimeError:
        return {"ok": False, "text": "OPENROUTER_API_KEY is not filled in, in .env", "spent": None, "left": None}
    try:
        d = (get(f"{OPENROUTER}/key", key) or {}).get("data") or {}
    except urllib.error.HTTPError as e:
        why = "OpenRouter refused the key (wrong or revoked)" if e.code in (401, 403) else f"OpenRouter answered HTTP {e.code}"
        return {"ok": False, "text": why, "spent": None, "left": None}
    except Exception as e:
        return {"ok": False, "text": f"OpenRouter can't be reached ({type(e).__name__})", "spent": None, "left": None}
    spent = d.get("usage") if isinstance(d.get("usage"), (int, float)) else None
    left = [d["limit_remaining"]] if isinstance(d.get("limit_remaining"), (int, float)) else []
    try:   # the account's balance: not every key may read it, so a refusal here is not a problem
        c = (get(f"{OPENROUTER}/credits", key) or {}).get("data") or {}
        if isinstance(c.get("total_credits"), (int, float)) and isinstance(c.get("total_usage"), (int, float)):
            left.append(c["total_credits"] - c["total_usage"])
    except Exception:
        pass
    left = min(left) if left else None
    if left is not None and left < CREDIT_WARN_USD:
        return {"ok": False, "text": f"OpenRouter credit is nearly gone: ${max(left, 0):.2f} left", "spent": spent, "left": left}
    text = "key works" + (f", ${left:.2f} credit left" if left is not None else "")
    return {"ok": True, "text": text, "spent": spent, "left": left}


def ebay():
    """{"ok", "text"}: can BEAR still sign in to eBay with its keys (one call to eBay)."""
    sys.path.insert(0, str(REPO / "bear2"))
    try:
        import common as c
        c._tok["v"] = None   # a real sign-in, not a token from earlier
        c.ebay_token()
    except Exception as e:   # common's messages name the failure (HTTP 401 ...) and never a key
        return {"ok": False, "text": f"eBay sign-in failed: {str(e)[:120]}"}
    return {"ok": True, "text": "keys work"}


def health(storage, cache, dev=False, limit=EBAY_DAILY_LIMIT, check_openrouter=openrouter, check_ebay=ebay):
    """[(what, ok, text)] for /health and the daily check. ok is True, False (a problem to act on)
    or None (not checked). In dev mode the keys aren't checked: a dev server may have none."""
    rows = []
    if dev:
        rows += [("OpenRouter", None, "not checked in dev mode"), ("eBay", None, "not checked in dev mode")]
    else:
        o, e = check_openrouter(), check_ebay()
        rows += [("OpenRouter", o["ok"], o["text"]), ("eBay", e["ok"], e["text"])]
    calls = ebay_calls(cache)
    rows.append(("eBay calls today", calls < limit * EBAY_WARN_AT, f"{calls} of {limit}"))
    free, percent = disk(storage)
    if free is None:
        rows.append(("Disk", None, "can't be read"))
    else:
        rows.append(("Disk", percent >= DISK_WARN_PERCENT, f"{free:.1f} GB free ({percent:.0f}%)"))
    return rows
