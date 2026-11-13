"""BEAR v2 shared plumbing: env loading (never printed), eBay Browse search with disk
cache, OpenRouter chat + Jev decisions calls with a cost ledger.

Secrets: loaded from BEAR/.env into this process only. Nothing here ever prints,
logs or returns a secret value.
"""
import base64, hashlib, json, os, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import jev_client  # noqa: E402

CACHE = ROOT / "bear2" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
LEDGER = Path(os.environ.get("BEAR_SPEND_LEDGER") or ROOT / "bear2" / "spend.jsonl")   # the Discord bot gives each run its own
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")   # photos BEAR reads; everything else in the folder is ignored


def _env(name):
    v = os.environ.get(name)
    if v:
        return v.strip()
    v = jev_client._parse_dotenv(jev_client.ENV_FILE).get(name)
    if not v:
        raise RuntimeError(f"{name} missing from environment/.env")
    return v.strip()


def tokens(usage):
    """Token counts from an OpenRouter usage block, for the ledger: prompt, completion, reasoning."""
    usage = usage or {}
    return {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")}


def log_spend(kind, model, cost, extra=None, usage=None):
    """One ledger line: cost, and the token counts (prompt, completion, reasoning) when known."""
    with LEDGER.open("a") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, "model": model,
                            "cost": cost, **tokens(usage), **(extra or {})}) + "\n")


def total_spend():
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(l).get("cost") or 0 for l in LEDGER.read_text().splitlines() if l.strip())


_SPEND_AT_IMPORT = total_spend()  # per-run cap: only spend since this process started counts


def _check_cap():
    cap = float(os.environ.get("BEAR_RUN_CAP_USD", "1.00"))
    s = total_spend() - _SPEND_AT_IMPORT
    if s >= cap:
        raise RuntimeError(f"spend cap reached: ${s:.4f} this run (cap ${cap:.2f})")


# ---------------- eBay ----------------
_tok = {"v": None, "exp": 0}


# eBay hiccups (HTTP 429/5xx, a timeout, a dropped connection) are retried with backoff,
# 2+4+8s (or Retry-After), before a search counts as "eBay Lookup Unavailable". Other 4xx
# answers mean the request itself is wrong, so they are not retried.
EBAY_ATTEMPTS = 4
EBAY_DOWN_AFTER = 3   # this many searches in a row failing even with retries = eBay is down: later
_ebay_fails = [0]     # searches try once, no backoff, until one works (a run can't stall for hours)
NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError)


def _transient(e):
    return isinstance(e, NETWORK_ERRORS) and not isinstance(e, urllib.error.HTTPError) or \
        isinstance(e, urllib.error.HTTPError) and (e.code == 429 or e.code >= 500)


def ebay_token():
    if _tok["v"] and time.time() < _tok["exp"] - 60:
        return _tok["v"]
    basic = base64.b64encode(f"{_env('EBAY_APP_ID')}:{_env('EBAY_CERT_ID')}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
    attempts = 1 if _ebay_fails[0] >= EBAY_DOWN_AFTER else EBAY_ATTEMPTS   # eBay down: fail fast
    for attempt in range(attempts):
        req = urllib.request.Request("https://api.ebay.com/identity/v1/oauth2/token", data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Authorization", f"Basic {basic}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            break
        except Exception as e:
            if not _transient(e) or attempt + 1 == attempts:
                if _transient(e):
                    _ebay_fails[0] += 1   # a login outage counts towards "eBay is down" too
                why = f"HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else type(e).__name__
                raise RuntimeError(f"eBay OAuth failed {why}") from None
            time.sleep(_retry_wait(e, attempt))
    _tok["v"], _tok["exp"] = d["access_token"], time.time() + int(d.get("expires_in", 7200))
    return _tok["v"]


CAR_PARTS_CATEGORY = "131090"   # eBay UK Vehicle Parts & Accessories. Without it a misread
                                # number ("0165-18", IMG_3931) matched a gold watch listing.


def prune_ebay_cache(max_age_h=24):
    """Delete eBay search results older than their 24-hour life (ebay_search_raw never reads them
    again), and half-written temp files left by a stopped run. Returns how many went."""
    gone, cutoff = 0, time.time() - max_age_h * 3600
    for f in list(CACHE.glob("ebay_*.json")) + list(CACHE.glob("ebay_*.tmp")):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                gone += 1
        except OSError:   # another run removed it first
            pass
    return gone


def ebay_search_raw(q, limit=200, max_age_h=24, category=CAR_PARTS_CATEGORY):
    key = hashlib.sha1(f"{q}|{limit}|{category}".encode()).hexdigest()[:16]
    cf = CACHE / f"ebay_{key}.json"
    if cf.exists() and time.time() - cf.stat().st_mtime < max_age_h * 3600:
        return json.loads(cf.read_text())["items"]
    params = {"q": q, "filter": "itemLocationCountry:GB", "limit": str(limit), "fieldgroups": "EXTENDED"}
    if category:
        params["category_ids"] = category
    items = []
    attempts = 1 if _ebay_fails[0] >= EBAY_DOWN_AFTER else EBAY_ATTEMPTS
    for attempt in range(attempts):
        req = urllib.request.Request("https://api.ebay.com/buy/browse/v1/item_summary/search?"
                                     + urllib.parse.urlencode(params))
        req.add_header("Authorization", f"Bearer {ebay_token()}")
        req.add_header("X-EBAY-C-MARKETPLACE-ID", "EBAY_GB")
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                items = json.loads(r.read()).get("itemSummaries", []) or []
        except Exception as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 401 and attempt + 1 < attempts:
                _tok["v"] = None   # token expired early: get a new one and try again
                continue
            if not _transient(e) or attempt + 1 == attempts:
                if _transient(e):
                    _ebay_fails[0] += 1
                raise
            time.sleep(_retry_wait(e, attempt))
            continue
        _ebay_fails[0] = 0
        # Measured (IMG_3974): eBay occasionally returns a degraded payload with no
        # condition field on any item, which silently disables the used-first rule.
        if not items or sum(1 for i in items if i.get("condition")) >= 0.5 * len(items):
            # temp file + rename: two runs at once (Discord bot) never read a half-written file
            tmp = cf.with_name(f"{cf.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"q": q, "items": items}))
            os.replace(tmp, cf)
            return items
        time.sleep(1 + attempt)
    return items  # degraded, not cached


def norm(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def match_text(it):
    chunks = [it.get(k) for k in ("title", "shortDescription", "mpn", "subtitle")]
    for a in it.get("localizedAspects") or []:
        if isinstance(a, dict):
            chunks += [a.get("name"), a.get("value")]
    return " ".join(c for c in chunks if isinstance(c, str))


def ebay_exact(part_number):
    """All UK active listings whose title/aspects contain the part number (alnum-normalised).
    Queries raw + normalised forms, dedup on itemId."""
    qs = [part_number] + ([norm(part_number)] if norm(part_number) != part_number else [])
    seen, out = set(), []
    needle = norm(part_number)
    for q in qs:
        for it in ebay_search_raw(q):
            iid = it.get("itemId")
            if iid in seen:
                continue
            seen.add(iid)
            if needle and needle in norm(match_text(it)):
                out.append(it)
    return out


def summarize(it):
    img = (it.get("image") or {}).get("imageUrl")
    if not img:
        for t in it.get("thumbnailImages") or []:
            img = t.get("imageUrl"); break
    url = it.get("itemWebUrl") or ""
    return {"id": it.get("legacyItemId") or it.get("itemId"), "title": it.get("title"),
            "price": float((it.get("price") or {}).get("value") or 0),
            "condition": it.get("condition") or "", "seller": (it.get("seller") or {}).get("username"),
            "url": url.split("?")[0], "image": img, "category": category_id(it)}


def category_id(it):
    """The eBay category the seller listed the item in, as its ID ("33546" = HVAC Blower Motors
    & Wheels); "" if eBay gave none. The ID, not the name: it is what a listing is filed under."""
    leaf = it.get("leafCategoryIds") or [x.get("categoryId") for x in it.get("categories") or []]
    return str(leaf[0] or "") if leaf else ""


# ---------------- OpenRouter chat ----------------
# Upstream rate limits (HTTP 429, e.g. "qwen3.8-flash is temporarily rate-limited upstream")
# outlast a few seconds of backoff: give it ~1 minute (2+4+8+16+30s, or Retry-After) before failing.
CHAT_ATTEMPTS = 6


def _retry_wait(err, attempt):
    try:
        ra = float(err.headers.get("Retry-After") or 0)
    except (TypeError, ValueError, AttributeError):
        ra = 0
    return min(30, max(ra, 2 ** (attempt + 1)))


def chat(model, messages, *, temperature=0, max_tokens=1500, response_format=None, extra=None, tag="",
         attempts=CHAT_ATTEMPTS):
    _check_cap()
    body = {"model": model, "messages": messages, "temperature": temperature,
            "max_tokens": max_tokens, "usage": {"include": True}}
    if response_format:
        body["response_format"] = response_format
    if extra:
        body.update(extra)
    last = None
    for attempt in range(attempts):
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions",
                                     data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", f"Bearer {jev_client.resolve_api_key()}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            cost = (d.get("usage") or {}).get("cost") or 0
            log_spend("chat", model, cost, {"tag": tag}, d.get("usage"))
            return d["choices"][0]["message"].get("content") or "", d
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            last = RuntimeError(f"OpenRouter HTTP {e.code}: {msg}")
            if e.code in (401, 402, 400):
                raise last from None
            if attempt + 1 < attempts:
                time.sleep(_retry_wait(e, attempt))
        except Exception as e:  # network
            last = RuntimeError(f"OpenRouter call failed: {type(e).__name__}: {str(e)[:200]}")
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise last


def img_data_uri(path, max_side=1600, rotate=0):
    from PIL import Image, ImageOps
    import io
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if rotate:
        im = im.rotate(rotate, expand=True)
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------- Jev ----------------
JEV_MODEL = "typesafe/jev-1.13"


def jev(state, questions, tag=""):
    return decide(JEV_MODEL, state, questions, tag)


class JevFailed(RuntimeError):
    """A Decisions (Jev) call failed after its retries. Its own type, so a part it costs is
    labelled "Jev Unavailable", not blamed on eBay (bear2/run.py fail_cause)."""


JEV_DOWN_AFTER = 3   # this many Jev calls in a row failing after their minute of retries = Jev is
_jev_fails = [0]     # down: later calls try once, until one works (a run can't stall for hours)


def decide(model, state, questions, tag=""):
    """One Decisions API call (Jev, or openai/gpt-6-luna-decisions, which also takes photos).
    Retried like chat calls (CHAT_ATTEMPTS, about a minute), not jev_client's own ~3 seconds."""
    _check_cap()
    attempts = 1 if _jev_fails[0] >= JEV_DOWN_AFTER else CHAT_ATTEMPTS
    try:
        r = jev_client.call_decisions(model, state, questions, max_attempts=attempts, wait=_retry_wait)
    except jev_client.JevPaymentError as e:   # same words as chat's 402, so the bot reports BEAR-K01
        raise JevFailed(f"OpenRouter HTTP 402 (Jev): {str(e)[:200]}") from None
    except Exception as e:
        _jev_fails[0] += 1
        raise JevFailed(f"Jev failed: {type(e).__name__}: {str(e)[:200]}") from None
    _jev_fails[0] = 0
    log_spend("decisions", model, jev_client.get_cost(r), {"tag": tag}, r.get("usage"))
    return r
