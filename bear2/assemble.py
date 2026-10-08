"""Deterministic Agent 3 replacement. The ONLY model job left is cleaning the eBay title
into a part name (one cheap call per job, JSON in/out). Everything with a contract —
vehicle string, location from filename, part number, price, URL, image, sort, failure
and NULL rows — is code, so it cannot be corrupted.

Why: live run r7, Agent 3 (qwen3.8-flash) wrote url itm/168603Z210 (part number blended
into the link) and dropped the image field. URL and image are copy-through fields; a model
has no business touching them.

usage: python3 bear2/assemble.py <run_dir> "<VEHICLE STRING>"
Writes <run_dir>/agent3_results.txt (4-field contract) and results.xlsx.
"""
import json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

LOC = {"NSF": "Near Side Front", "NSR": "Near Side Rear", "OSF": "Off Side Front", "OSR": "Off Side Rear"}
MODEL = "qwen/qwen3.8-flash"
# Live run 2026-10-08 (Shogun): OpenRouter returned 429 "qwen3.8-flash is temporarily rate-limited
# upstream" through all retries and every name fell to the mechanical clean. The backup is the
# model that already reads the photos, so no new provider.
BACKUP_MODEL = "google/gemini-3.1-flash-lite"

CLEAN_PROMPT = """You clean eBay listing titles into short part names for a UK car breaker's spreadsheet.
For each item, return ONLY the words that say what the component is. Remove:
- vehicle words: make, model, trim, generation (MK1, FACELIFT, FL, PRE FL), years/year ranges, engine size, fuel, power, body style (ESTATE, SALOON, CRDI, STYLE, BLUE DRIVE)
- every part number, SKU, seller code, stray symbols
- seller noise: GENUINE, OEM, FREE POSTAGE, condition words
- SIDE words: Left, Right, Driver Side, Passenger Side, Near Side, Off Side, N/S, O/S, NS, OS, LH, RH (the operator adds side from his own filename code).
- Keep Front / Rear / Centre / Upper / Lower / Inner / Outer: they name which component it is (Front Roof Light, Rear Parking Sensors, Dashboard Centre Vent).
  Exception: if the item says "locationcode": true, also remove Front/Rear, because the operator's code already says it.
- quantity words when the photo shows one item (keep "Pair" only if the item is a pair).
Keep the seller's own component wording otherwise; do not invent or reword.
Capitalise The First Letter Of Every Word, lowercase the rest (acronyms like SRS, ECU, LDC become Srs, Ecu, Ldc). Replace & with & (keep it).
Return JSON: {"names": {"<id>": "<clean name>", ...}}"""

EXAMPLES = """Examples (other cars, for style only):
"MAZDA 6 2012 DRIVER SIDE FRONT BUMPER BRACKET GS1D500T1 GENUINE" -> "Bumper Bracket"
"2016 FORD FOCUS MK3 1.0 ECOBOOST REAR WIPER MOTOR 1234567 FREE POST" -> "Rear Wiper Motor"
"VW GOLF MK7 2015 N/S FRONT WINDOW CONTROL SWITCH 5G0959857 OEM" -> "Window Control Switch"
"Kia Ceed 2014 Front Right Seat Control Motor 88583-3S500 100kW" -> "Front Seat Control Motor"
"""


def tokens(fn):
    return [t.upper() for t in re.split(r"[_\-\s.]+", Path(fn).stem) if t]


def location(fn):
    for t in tokens(fn):
        if t in LOC:
            return LOC[t]
    return None


def image_no(fn):
    m = re.search(r"\d+", fn)
    return int(m.group()) if m else -1


def clean_names(titles):
    if not titles:
        return {}
    user = EXAMPLES + "\nItems:\n" + json.dumps(titles, indent=0)
    msgs = [{"role": "system", "content": CLEAN_PROMPT}, {"role": "user", "content": user}]
    for model, extra in ((MODEL, {"reasoning": {"effort": "none", "exclude": True}}), (BACKUP_MODEL, None)):
        try:
            out, raw = c.chat(model, msgs, max_tokens=3000, response_format={"type": "json_object"},
                              extra=extra, tag="clean_names")
            m = re.search(r"\{.*\}", out, re.S)
            names = json.loads(m.group(0)).get("names", {}) if m else {}
            if names:
                return names
            print(f"(part-name cleaning: {model} returned no names)", file=sys.stderr, flush=True)
        except Exception as e:
            # Names are cosmetic: a rate limit / outage here must not throw away a finished, paid-for
            # run. Try the backup model, then safe_name falls back to a mechanical clean per row.
            print(f"(part-name cleaning: {model} unavailable: {str(e)[:120]})", file=sys.stderr, flush=True)
    print("(part-name cleaning unavailable, using a plain clean of the eBay titles)", file=sys.stderr, flush=True)
    return {}


MAKES = ("alfa romeo audi bmw chevrolet chrysler citroen dacia daewoo daihatsu dodge fiat ford honda "
         "hyundai infiniti isuzu jaguar jeep kia lancia land rover range lexus mazda mercedes benz mini "
         "mitsubishi nissan peugeot porsche proton renault rover saab skoda ssangyong subaru "
         "suzuki toyota vauxhall opel volkswagen vw volvo").split()
VEHICLE_WORDS = ("mk facelift fl pre lwb swb gls glx gsr se sx sxi lx gl gt td tdi tdci crdi dci hdi "
                 "di-d did cdti cdi vtec bhp ps kw diesel petrol hybrid turbo manual auto automatic "
                 "estate saloon hatchback coupe convertible van").split()
NOISE = ("genuine oem original used new free post postage p&p quick delivery uk seller fits fit for to "
         "from with in x").split()
SIDE = ("left right lh rh l/h r/h n/s o/s ns os nsf nsr osf osr n/s/f n/s/r o/s/f o/s/r near off side "
        "driver drivers driver's passenger passengers passenger's").split()


def mechanical_name(title, vehicle=""):
    """Last-resort clean when no model is available: drop vehicle words (the job's own vehicle
    string plus common makes / trims), anything with a digit (part numbers, years, 2.8, 4M40),
    side words, seller noise and punctuation-only leftovers. Words keep their eBay order."""
    drop = set(MAKES + VEHICLE_WORDS + NOISE + SIDE)
    drop |= {w.lower() for w in re.split(r"[^\w-]+", vehicle) if w}
    seen, keep = set(), []
    for w in re.sub(r"[()\[\],;:|*#!+]", " ", title).split():
        w = w.strip(".-/&'")
        lw = w.lower()
        if not w or not re.search(r"[A-Za-z]", w) or re.search(r"\d", w) or lw in drop \
                or re.sub(r"\d+$", "", lw) in ("mk",) or lw in seen:
            continue
        seen.add(lw)
        keep.append(w[:1].upper() + w[1:].lower())
    return " ".join(keep)


def safe_name(name, title, pn, vehicle=""):
    """Guard rails on the model's one job. Falls back to a mechanical clean if violated."""
    bad = (not name or "|" in name or len(name) > 90 or c.norm(pn) in c.norm(name)
           or re.search(r"\d{4,}", name))
    if not bad:
        return " ".join(w[:1].upper() + w[1:].lower() for w in name.split())
    return mechanical_name(title, vehicle)


def main(run_dir, vehicle):
    run = Path(run_dir)
    rows = []
    for line in (run / "agent2_results.md").read_text().splitlines():
        f = [s.strip() for s in line.split("|")]
        if len(f) >= 2:
            rows.append(f)
    nulls = [n for n in (run / "null_files.txt").read_text().split("\n") if n.strip()] if (run / "null_files.txt").exists() else []
    titles = {f"i{k}": {"title": f[2], "locationcode": bool(location(f[0]))} for k, f in enumerate(rows) if f[1] != "FAILED"}
    print("Cleaning part names ...", file=sys.stderr, flush=True)
    names = clean_names(titles)
    out = []
    for k, f in enumerate(rows):
        img = f[0]
        loc = location(img)
        if f[1] == "FAILED":
            out.append((image_no(img), f"FAILED - {f[2]} - {f[3]} | | | {img}"))
            continue
        pn, title, price, url = f[1], f[2], f[-2], f[-1]
        name = safe_name(names.get(f"i{k}"), title, pn, vehicle)
        if loc:  # never repeat the operator's location words
            for w in loc.split():
                name = re.sub(rf"(?i)^{w}\b\s*", "", name) if w in ("Front", "Rear") else name
        info = f"{vehicle} - " + (f"{loc} " if loc else "") + f"{name} {c.norm(pn)}"
        out.append((image_no(img), f"{info} | {price} | {url} | {img}"))
    for img in nulls:
        loc = location(img)
        out.append((image_no(img), f"NO PART NUMBER - {vehicle}" + (f" - {loc}" if loc else "") + f" | | | {img}"))
    out.sort(key=lambda x: x[0])                      # stable: same number keeps arrival order
    text = "\n".join(l for _, l in out) + "\n"
    (run / "agent3_results.txt").write_text(text)
    print("Writing results.xlsx ...", file=sys.stderr, flush=True)
    v = subprocess.run([sys.executable, str(c.ROOT / "tools/agent3_validator.py"), str(run / "agent3_results.txt"),
                        str(run / "agent2_results.md")], capture_output=True, text=True)
    x = subprocess.run([sys.executable, str(c.ROOT / "harness/make_xlsx.py"), str(run / "agent3_results.txt"),
                        str(run / "results.xlsx")], capture_output=True, text=True)
    print(f"validator exit {v.returncode} | {(x.stdout or x.stderr).strip()[-120:]}")
    if v.returncode:
        print(v.stdout[-1200:])
    return text


if __name__ == "__main__":
    print(main(sys.argv[1], sys.argv[2]))
