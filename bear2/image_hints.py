"""Possible-match hints for photos BEAR could not price (FAILED rows and NULL photos).

eBay's search-by-image returns listings that LOOK like the photo. Measured 2026-10-01:
right part in the top 50 for 5/9 photos with known answers, and a vision "same part?"
check on listing photos said SAME for 3/4 wrong parts. So hints are never written into
results.xlsx and never carry a BEAR price: they go to a separate possible_matches.xlsx
for the operator to eyeball (one click instead of a Google image search).

Ranking: the parts in one job come off one car, so listings whose titles share words with
the vehicle string and with the titles of this job's successfully matched parts (make,
engine, model) rank first; eBay's visual order breaks ties. Cost: free (eBay API only).
"""
import base64, collections, io, json, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

PER_PHOTO = 3
GENERIC = set("""USED GENUINE OEM NEW PART PARTS UNIT FREE POSTAGE FITS FOR WITH AND THE MK1 MK2 MK3 MK4
FRONT REAR LEFT RIGHT DIESEL PETROL ENGINE SENSOR PUMP MODULE ASSEMBLY X1 1X PCS SET""".split())


def _b64(path, side):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((side, side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def search_by_image(path, limit=50):
    """eBay UK car-parts listings visually similar to the photo. Retries at a smaller size
    (measured: one photo got HTTP 500 at 800px on one attempt, fine on the next)."""
    params = {"limit": str(limit), "filter": "itemLocationCountry:GB", "category_ids": c.CAR_PARTS_CATEGORY}
    for side in (800, 640, 512):
        req = urllib.request.Request(
            "https://api.ebay.com/buy/browse/v1/item_summary/search_by_image?" + urllib.parse.urlencode(params),
            data=json.dumps({"image": _b64(path, side)}).encode(), method="POST")
        req.add_header("Authorization", f"Bearer {c.ebay_token()}")
        req.add_header("X-EBAY-C-MARKETPLACE-ID", "EBAY_GB")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read()).get("itemSummaries", []) or []
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            time.sleep(1)
    return []


def words(text):
    return {w for w in re.findall(r"[A-Z0-9][A-Z0-9.\-]*", (text or "").upper())
            if len(w) >= 2 and w not in GENERIC and not re.fullmatch(r"\d{1,2}", w)}


def job_context(vehicle, matched_titles):
    """Words that identify THIS car: vehicle string + words repeated across the job's
    matched listing titles (e.g. FORD, S-MAX, 2.0, TDCI, HDI)."""
    ctx = collections.Counter()
    for w in words(vehicle) - {"UNKNOWN", "VEHICLE"}:
        ctx[w] += 3
    seen = collections.Counter(w for t in matched_titles for w in words(t))
    for w, n in seen.items():
        if n >= 2:
            ctx[w] += 1
    return ctx


def rank(items, ctx):
    scored = []
    for pos, it in enumerate(items):
        s = sum(ctx.get(w, 0) for w in words(it.get("title")))
        used = (it.get("condition") or "").lower().startswith("used")
        scored.append((-s, not used, pos, it))
    scored.sort(key=lambda x: x[:3])
    return [x[3] for x in scored]


def main(run_dir, photo_dir, vehicle):
    run, photo_dir = Path(run_dir), Path(photo_dir)
    a3 = [l.split("|") for l in (run / "agent3_results.txt").read_text().splitlines() if l.strip()]
    need = [f[3].strip() for f in a3 if len(f) == 4 and f[0].strip().startswith(("FAILED", "NO PART NUMBER"))]
    a2 = [l.split("|") for l in (run / "agent2_results.md").read_text().splitlines() if l.strip()]
    matched = [f[2] for f in a2 if len(f) >= 5 and f[1].strip() != "FAILED"]
    ctx = job_context(vehicle, matched)
    rows, trace = [], {}
    for img in need:
        items = search_by_image(photo_dir / img)
        top = rank(items, ctx)[:PER_PHOTO]
        trace[img] = [(it.get("title"), it["price"]["value"]) for it in top]
        if not top:
            rows.append(f"NO VISUAL MATCH FOUND | | | {img}")
        for k, it in enumerate(top, 1):
            s = c.summarize(it)
            title = (s["title"] or "").replace("|", " ")
            rows.append(f"POSSIBLE MATCH {k} (check by eye) - {title} | {it['price']['value']} | {s['url']} | {img}")
    (run / "image_hints.json").write_text(json.dumps({"context": ctx.most_common(15), "hints": trace}, indent=1))
    if not rows:
        return None
    (run / "possible_matches.txt").write_text("\n".join(rows) + "\n")
    subprocess.run([sys.executable, str(c.ROOT / "harness/make_xlsx.py"), str(run / "possible_matches.txt"),
                    str(run / "possible_matches.xlsx")], capture_output=True, text=True, check=True)
    return run / "possible_matches.xlsx"


if __name__ == "__main__":
    print(main(sys.argv[1], sys.argv[2], sys.argv[3]))


# ---------------- corroboration (used inside the pipeline) ----------------
_sbi_cache = {}


def image_tokens(photo_path):
    """Part-number-shaped tokens from the titles of visually similar listings."""
    key = str(photo_path)
    if key not in _sbi_cache:
        toks = collections.Counter()
        for it in search_by_image(photo_path):
            t = (it.get("title") or "").upper()
            for m in re.findall(r"[A-Z0-9][A-Z0-9\-.]{4,}[A-Z0-9]", t):
                n = c.norm(m)
                if len(n) >= 6 and re.search(r"\d", n) and re.search(r"\d.*\d.*\d", n):
                    toks[n] += 1
            # numbers printed in spaced groups, e.g. "96 436 957 80"
            for m in re.findall(r"\b\d{2,3}(?: \d{2,4}){2,4}\b", t):
                n = c.norm(m)
                if 8 <= len(n) <= 12:
                    toks[n] += 1
        _sbi_cache[key] = toks
    return _sbi_cache[key]


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def corroborate(photo_path, chosen_text, raw_readings):
    """Returns (status, token).
    'agrees'  - the chosen number (or its family) appears in visually similar listings.
    'better'  - a listing token within 1-2 characters of what vision READ off the part
                (two independent signals agreeing) that the chosen number is not.
    'none'    - image search adds nothing."""
    toks = image_tokens(photo_path)
    ch = c.norm(chosen_text)
    if any(ch in t or (len(t) >= 7 and t in ch) for t in toks):
        return "agrees", ch
    best = None
    for raw in raw_readings:
        r = c.norm(raw)
        if len(r) < 7:
            continue
        for t in toks:
            if abs(len(t) - len(r)) > 2:
                continue
            d = lev(r, t)
            if d <= (1 if len(r) < 9 else 2) and (best is None or (d, -toks[t]) < best[0]):
                best = ((d, -toks[t]), t)
    return ("better", best[1]) if best else ("none", None)
