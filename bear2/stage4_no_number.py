"""Stage 4 - price a part that has NO part number (owner, 2026-11-17).

Runs only for a photo the number stages could not price (FAILED "Could Not Produce Clear Part
Number") on which stage 1 read no real part number at all (a door handle, a towing eye, a badge).
Every part BEAR prices today goes through stages 1-3 exactly as before, so this can only turn a
FAILED row into a priced one, never change a priced row.

How it prices, using what BEAR already has (pilot 2026-11-17, experiments/nonum/, 17 photos):
  1. what the part is: stage 1's own part_description (already paid for; right on about 29 of 33
     no-number photos), or a naming model if BEAR_NO_NUMBER_NAMER names one (about 0.14p a part)
  2. the side: a yard marker stage 1 read off the part (NF, OF, NR, OR, NS, OS ...), for the name only
  3. eBay UK text search for "<make> <model> <part>": the car comes from the channel, so every
     listing is already for this car. Photo-similarity search was tried and lost: it found parts
     that look alike off other cars (1 of 17 right).
  4. titles that don't name the part are dropped (free), then Jev, looking at the photo, vetoes listings that are not this kind of part (or are a pair, set or
     bigger assembly). Side and car are NOT judged: the owner's rule is that a door handle is a door
     handle when the car is the same.
  5. at least MIN_KEPT listings left: BEAR's own price rule (used first, most common x.99 price,
     floor 19.99) and the listing it came from is the link in the sheet. Fewer: not sure, the row
     stays FAILED with the eBay look-alike hints under it, as before.
Cost: about 0.03p a part (one Jev call with the photo, one Jev best-title call), eBay calls free.

Off unless BEAR_NO_NUMBER=on (.env).
"""
import base64, io, json, os, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c, stage3_listing as s3, jev_client as j

MIN_KEPT = 3        # listings Jev must keep before BEAR prices: fewer is "not sure"
KEEP_FROM = 0.5     # Jev's yes-probability for a listing to count as this kind of part
CAP = 60            # listings sent to Jev (one call)
SEARCH_LIMIT = 100  # eBay results per search

SIDES = {"NSF": "Near Side Front", "OSF": "Off Side Front", "NSR": "Near Side Rear", "OSR": "Off Side Rear",
         "NS": "Near Side", "OS": "Off Side"}
MARKER = re.compile(r"^(N|O)S?(F|R)?$")   # NF, NSF, OR, OSR, NS, OS ... as the yard writes them
TWO_WORD_MAKES = {"LAND", "ALFA", "ASTON", "ROLLS"}
STOP_WORDS = re.compile(r"^(MK\d*|\d{4}|\d\.\d|\d{2,4}CC|SALOON|SEDAN|HATCHBACK|ESTATE|DIESEL|PETROL)$")


def enabled():
    return (os.environ.get("BEAR_NO_NUMBER") or "").strip().lower() in ("1", "on", "yes", "true")


def has_real_number(s1):
    """Did stage 1 read anything that could be a part number? A part number has 6+ letters/digits
    with at least 2 digits; yard markers (NF), single characters and short codes do not count."""
    for x in (s1 or {}).get("candidates") or []:
        for t in [x.get("text")] + list(x.get("alt_readings") or []):
            n = c.norm(t or "")
            if len(n) >= 6 and sum(ch.isdigit() for ch in n) >= 2:
                return True
    return False


def side_marker(s1):
    """The side the yard wrote on the part (NF -> NSF, OR -> OSR, NS -> NS), or None."""
    for x in (s1 or {}).get("candidates") or []:
        m = MARKER.match(c.norm(x.get("text") or ""))
        if m:
            return f"{m.group(1)}S{m.group(2) or ''}"
    return None


def car_words(vehicle):
    """Make and model from the channel's car: "MAZDA CX-5 MK1 2014 2.2 DIESEL" -> "MAZDA CX-5",
    "MITSUBISHI SHOGUN/PAJERO GLS 1998" -> "MITSUBISHI SHOGUN", "LAND ROVER DISCOVERY 3" ->
    "LAND ROVER DISCOVERY". None when the car is unknown."""
    words = (vehicle or "").upper().split()
    if not words or words[0] == "UNKNOWN":
        return None
    make = words[:2] if words[0] in TWO_WORD_MAKES and len(words) > 1 else words[:1]
    rest = words[len(make):]
    if not rest or STOP_WORDS.match(rest[0]):
        return None
    return " ".join(make + [rest[0].split("/")[0]])


FILLER = {"a", "an", "the", "of", "car", "used", "assembly", "unit", "complete", "genuine", "oem", "part"}


def part_queries(desc, vehicle=""):
    """The part words to search, most specific first: "exterior door handle assembly with lock
    mechanism" -> ["exterior door handle", "door handle", "exterior door"]; "crankshaft pulley harmonic
    balancer" -> [..., "harmonic balancer", "crankshaft pulley"]. Words of the car itself (a description
    like "Mazda CX-5 MK1 climate control panel") and engine/fuel words are left out: the car is
    added to every search from the channel."""
    car = {w.lower() for w in re.findall(r"[A-Za-z0-9\-]+", vehicle or "")}
    d = re.sub(r"\(.*?\)", " ", (desc or "").lower())
    d = re.split(r"\s/\s|/| with | for | and | or |,|;", d)[0]
    words = [w for w in re.findall(r"[a-z0-9\-]+", d)
             if w not in FILLER and w not in car and not STOP_WORDS.match(w.upper())][:5]
    out = []
    for q in [words, words[-3:], words[-2:], words[:2]]:   # all, then the end (the part's name), then the start
        q = " ".join(q)
        if q and q not in out and (len(q.split()) >= 2 or not out):
            out.append(q)
    return out[:4]


def name_part(photo_path, s1, vehicle):
    """(part description, side): BEAR_NO_NUMBER_NAMER's model when set, else stage 1's description."""
    model = (os.environ.get("BEAR_NO_NUMBER_NAMER") or "").strip()
    side = side_marker(s1)
    if not model or not photo_path:
        return (s1 or {}).get("part_description"), side
    prompt = ("This used car part has no part number. Car: " + vehicle + ". The yard may write the side on "
              "the part: NF/OF/NR/OR = near/off side front/rear. Reply with JSON only: {\"part\": \"what UK eBay "
              "sellers call this part, 2-5 words, no car, no side\", \"side\": \"NSF|OSF|NSR|OSR|NS|OS|NONE\"}")
    txt, _ = c.chat(model, [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": c.img_data_uri(photo_path, 1024)}}]}],
        max_tokens=600, tag="no_number_name", extra={"reasoning": {"effort": "low"}})
    try:
        d = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except (AttributeError, ValueError):
        return (s1 or {}).get("part_description"), side
    s = str(d.get("side") or "").upper()
    return d.get("part") or (s1 or {}).get("part_description"), side or (s if s in SIDES else None)


def names_part(title, words):
    """Does the listing title name the part? One of the search's last two words (the part's own name:
    "pulley", "connector housing") must be in it, so a long search that also finds a whole engine or a
    bumper does not send those on. Free; Jev still judges every listing that passes."""
    t = re.findall(r"[a-z0-9]+", (title or "").lower())
    for w in words.split()[-2:]:
        stem = w.replace("-", "")[:5]
        if len(stem) >= 3 and any(x.startswith(stem) for x in t):
            return True
    return False


def search(car, desc):  # car: car_words(vehicle)
    """eBay UK listings for car + part whose titles name the part, trying shorter part words until a
    search finds at least MIN_KEPT."""
    tried = []
    for words in part_queries(desc, car):
        q = f"{car} {words}"
        tried.append(q)
        items = [it for it in c.ebay_search_raw(q, limit=SEARCH_LIMIT) if names_part(it.get("title"), words)]
        if len(items) >= MIN_KEPT:
            return items, tried
    return [], tried


def _photo_b64(photo_path):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    im.thumbnail((1024, 1024))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def same_kind(photo_path, desc, listings):
    """[(listing, yes-probability)]: Jev looks at the photo and each title and says whether the listing
    sells this kind of part as one item. Car and side are not judged (owner's rule)."""
    listings = listings[:CAP]
    state = {"described_as": desc, "listings": {f"L{i+1}": (it.get("title") or "") for i, it in enumerate(listings)}}
    assets = None
    if photo_path:
        state["photo_of_the_part"] = "@part"
        assets = {"@part": {"type": "image", "format": "jpeg", "data_base64": _photo_b64(photo_path)}}
    qs = {f"L{i+1}": {"type": "noul", "instructions": (
        f"photo_of_the_part is one used car part with no part number. Is listing L{i+1} selling the same kind "
        "of part (the same component), as one single item? Which car, which side and front/rear do not "
        "matter. Answer false for a different component, a bigger assembly that only includes it, a small "
        "piece of it, or a pair/set/multiple pieces.")} for i in range(len(listings))}
    r = c.jev(state, qs, tag="no_number_kind", assets=assets)
    return [(it, j.get_value(r, f"L{i+1}")) for i, it in enumerate(listings)]


def price(name, s1, vehicle, photo_path=None):
    """(agent-2 line or None, trace). None = not sure: the caller keeps the FAILED row."""
    tr = {}
    car = car_words(vehicle)
    desc, side = name_part(photo_path, s1, vehicle)
    tr.update(car=car, described_as=desc, side=side)
    if not car or not desc:
        tr["not_sure"] = "car or part unknown"
        return None, tr
    items, tried = search(car, desc)
    tr["searches"] = tried
    if not items:
        tr["not_sure"] = "eBay has too few listings"
        return None, tr
    scored = same_kind(photo_path, desc, items)
    kept = [(it, p) for it, p in scored if p >= KEEP_FROM]
    tr["kept"] = len(kept)
    tr["of"] = len(scored)
    if len(kept) < MIN_KEPT:
        tr["not_sure"] = f"only {len(kept)} listings are this kind of part"
        return None, tr
    item, pinfo = s3.pick_listing(kept, "", vehicle)
    tr["market_titles"] = pinfo.pop("market_titles", [])[:30]
    tr["pick"] = pinfo
    if not item:
        tr["not_sure"] = "no listing picked"
        return None, tr
    s = c.summarize(item)
    title = (s["title"] or "").replace("|", " ")
    return f"{name} |  | {title} | {s['category']} | {pinfo['sell_price']:.2f} | {s['url']}", tr
