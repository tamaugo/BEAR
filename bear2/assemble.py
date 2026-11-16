"""Deterministic Agent 3 replacement. The ONLY model job left is cleaning the eBay title
into a part name (one cheap call per job, JSON in/out). Everything with a contract —
vehicle string, part number, price, URL, image, sort and failure rows — is code, so it
cannot be corrupted.

Why: live run r7, Agent 3 (qwen3.8-flash) wrote url itm/168603Z210 (part number blended
into the link) and dropped the image field. URL and image are copy-through fields; a model
has no business touching them.

Name models never fall back silently (issue 19): if the name model is unavailable or gives an
unusable answer, BEAR stops with no names written (the Discord bot then retries or reports
BEAR-N01 to N03). The old mechanical cleaner that wrote the messy names now lives in legacy/
and is not used. The name model is BEAR_NAME_MODEL (one of NAME_MODELS), else MODEL.

usage: python3 bear2/assemble.py <run_dir> "<VEHICLE STRING>"
Writes <run_dir>/agent3_results.txt (5-field contract) and results.xlsx. Re-running it on a
saved run redoes only the names (the photo reads and eBay results are not paid for again).
"""
import json, os, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

MODEL = "qwen/qwen3.8-flash"   # default name model for every setup; update with the setups
NAME_MODELS = {MODEL: "Qwen 3.8 Flash",
               "google/gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
               "anthropic/claude-haiku-5.5": "Claude Haiku 5.5"}
NAME_BATCH = 25                   # rows per name-model call: a big folder can't be cut off at max_tokens
NAME_RETRY_TEMPERATURE = 0.4      # the second ask for a name that couldn't be used (the first is at 0)
OTHER_TITLES = 10                 # other sellers' titles sent with each part, for titles not in English

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
- If the title's component words are not in English (a seller abroad, e.g. German "Wischergriff"), give the English name UK sellers use instead: take it from "other_titles" (other UK listings of the same part number) when they name it, otherwise translate it to the usual UK trade name. Use "other_titles" only for this: never change an English title's wording because of them.
Capitalise The First Letter Of Every Word, lowercase the rest (acronyms like SRS, ECU, LDC become Srs, Ecu, Ldc). Replace & with & (keep it).
Return JSON: {"names": {"<id>": "<clean name>", ...}}"""

EXAMPLES = """Examples (other cars, for style only):
"MAZDA 6 2012 DRIVER SIDE FRONT BUMPER BRACKET GS1D500T1 GENUINE" -> "Bumper Bracket"
"2016 FORD FOCUS MK3 1.0 ECOBOOST REAR WIPER MOTOR 1234567 FREE POST" -> "Rear Wiper Motor"
"VW GOLF MK7 2015 N/S FRONT WINDOW CONTROL SWITCH 5G0959857 OEM" -> "Window Control Switch"
"Kia Ceed 2014 Front Right Seat Control Motor 88583-3S500 100kW" -> "Front Seat Control Motor"
"VW GOLF 7 Blinkerschalter 5Q0953513 Original" with other_titles ["VW GOLF MK7 INDICATOR STALK SWITCH 5Q0953513"] -> "Indicator Stalk Switch"
"""


def image_no(fn):
    m = re.search(r"\d+", fn)
    return int(m.group()) if m else -1


class Stop(Exception):
    """The run stops here with a message for the log. Nothing is written in place of names."""


class NamesFailed(Exception):
    """The name model was unavailable, errored or gave an unusable answer."""


def label(model):
    return NAME_MODELS.get(model, model)


def clean_names(rows, model=MODEL, attempts=c.CHAT_ATTEMPTS, others=None):
    """{id: agent2 row fields} -> {id: tidy name} for every row, or NamesFailed. Never partial,
    never a mechanical stand-in: a name that can't be used stops the run like an outage does.
    Sent NAME_BATCH rows per call, so a very large folder can't run past max_tokens.
    others: {id: other UK sellers' titles for that part number} (market_titles), so a title in
    another language gets the English name (run 2026-11-15: a German seller's "Wischergriff")."""
    items, tidy = list(rows.items()), {}
    for i in range(0, len(items), NAME_BATCH):
        tidy.update(clean_batch(dict(items[i:i + NAME_BATCH]), model, attempts, others))
    return tidy


def clean_batch(rows, model, attempts, others=None):
    """The names for up to NAME_BATCH rows (clean_names). A row whose name can't be used (missing,
    a year or number left in it, too long) is asked for once more on its own, a little less
    strictly: the first ask is at temperature 0, where asking again gives the same answer, so one
    bad name used to cost the whole folder its spreadsheet however often it was retried. Still
    never partial: a name that can't be used after the second ask stops the run as before."""
    if not rows:
        return {}
    names = ask_names(rows, model, attempts, others=others)
    bad = {k: f for k, f in rows.items() if not tidy_name(names.get(k), f[1])}
    if bad:
        print(f"Asking again for {len(bad)} part name(s) {label(model)} got wrong ...", file=sys.stderr, flush=True)
        names.update(ask_names(bad, model, attempts, NAME_RETRY_TEMPERATURE, others))
    tidy = {}
    for k, f in rows.items():
        tidy[k] = tidy_name(names.get(k), f[1])
        if not tidy[k]:
            raise NamesFailed(f"{label(model)} gave a name BEAR can't use for {f[0]}: {names.get(k)!r}")
    return tidy


def ask_names(rows, model, attempts, temperature=0, others=None):
    """One name-model call: {id: the model's name, as it gave it}. NamesFailed if the model is
    unavailable or its answer has no names at all."""
    others = others or {}
    user = EXAMPLES + "\nItems:\n" + json.dumps({k: title_item(f, others.get(k)) for k, f in rows.items()}, indent=0)
    # Not held back by the folder's spend cap (BEAR_RUN_CAP_USD): the names cost a fraction of a
    # penny and are what turns the parts already read and priced into a spreadsheet. With the cap
    # applied here, a folder that reached it lost every part it had paid for, not just the rest.
    try:
        out, raw = c.chat(model, [{"role": "system", "content": CLEAN_PROMPT}, {"role": "user", "content": user}],
                          max_tokens=3000, response_format={"type": "json_object"},
                          extra={"reasoning": {"effort": "none", "exclude": True}}, tag="clean_names",
                          attempts=attempts, capped=False, temperature=temperature)
    except Exception as e:
        raise NamesFailed(f"{label(model)} is unavailable: {str(e)[:160]}") from None
    m = re.search(r"\{.*\}", out, re.S)
    try:
        names = json.loads(m.group(0)).get("names")
    except Exception:
        names = None
    if not isinstance(names, dict):
        raise NamesFailed(f"{label(model)} gave an unusable answer (no names)")
    return names


def tidy_name(name, pn):
    """The model's part name in the approved layout ("Fog Light"), or None if it can't be used.
    The code adds the part number after the name, so a copy the model left in is removed."""
    if not isinstance(name, str):
        return None
    pnn = c.norm(pn)
    words = [w for w in name.replace("|", " ").split() if not (len(c.norm(w)) >= 4 and c.norm(w) in pnn)]
    name = " ".join(w[:1].upper() + w[1:].lower() for w in words)
    if not name or len(name) > 90 or re.search(r"\d{4,}", name) or (pnn and pnn in c.norm(name)):
        return None
    return name


def parse_row(line):
    """One agent2_results.md line -> its fields, or None for a blank/short line."""
    f = [s.strip() for s in line.split("|")]
    return f if len(f) >= 2 else None


def title_item(f, others=None):
    # "locationcode" is always false on the server (no location words in 001.jpg names), but it
    # stays so the name model gets exactly the same input its instructions above describe.
    item = {"title": f[2], "locationcode": False}
    own = " ".join(f[2].split()).lower()
    rest = []
    for t in others or []:
        t = " ".join(str(t).replace("|", " ").split())
        if t and t.lower() != own and t not in rest:
            rest.append(t)
    if rest:
        item["other_titles"] = rest[:OTHER_TITLES]
    return item


def market_titles(run):
    """{photo name: every UK title BEAR saw for its part number} from the run's trace.json, or {}
    for a run saved without one (the names are then made from the chosen title alone, as before)."""
    try:
        trace = json.loads((Path(run) / "trace.json").read_text())
    except (OSError, ValueError):
        return {}
    return {img: t.get("market_titles") or [] for img, t in trace.items() if isinstance(t, dict)}


def part_line(vehicle, f, name):
    """The finished results line for a priced row, exactly as it is written to the results.
    A run saved before the category field (5 fields, no category) gets a blank category."""
    img, pn, price, url = f[0], f[1], f[-2], f[-1]
    category = f[3] if len(f) >= 6 else ""
    info = f"{vehicle} - {name} {c.norm(pn)}"
    return f"{info} | {price} | {category} | {url} | {img}"


def start_model():
    """The name model to start with: BEAR_NAME_MODEL (set in .env on the Discord server), else the default."""
    m = (os.environ.get("BEAR_NAME_MODEL") or "").strip()
    if m and m not in NAME_MODELS:   # a typo used to be ignored without a word
        print(f"BEAR_NAME_MODEL {m!r} is not a name model BEAR knows ({', '.join(NAME_MODELS)}): "
              f"using {label(MODEL)}", file=sys.stderr, flush=True)
    return m if m in NAME_MODELS else MODEL


def stop_exit(e):
    sys.exit(f"\n{e}")


def resume_hint(run, vehicle):
    return (f"The photo reads and eBay results are saved in {run}.\n"
            f"To finish only the names later, run in Terminal:\n"
            f"  python3 bear2/assemble.py \"{run}\" \"{vehicle}\"")


def main(run_dir, vehicle):
    """Names, agent3_results.txt, the final check and results.xlsx for a run whose photos are read
    and priced (agent2_results.md). A name model that fails stops with Stop: no names are written."""
    run = Path(run_dir)
    rows = [f for f in map(parse_row, (run / "agent2_results.md").read_text().splitlines()) if f]
    priced = {f"i{k}": f for k, f in enumerate(rows) if f[1] != "FAILED"}
    seen = market_titles(run)
    others = {k: seen.get(f[0], []) for k, f in priced.items()}
    model = start_model()
    print(f"Cleaning part names ({label(model)}) ...", file=sys.stderr, flush=True)
    try:
        names = clean_names(priced, model, others=others)
    except NamesFailed as e:
        raise Stop(f"{e}. No names were written.\n" + resume_hint(run, vehicle)) from None
    out = []
    for k, f in enumerate(rows):
        img = f[0]
        if f[1] == "FAILED":
            out.append((image_no(img), f"FAILED - {f[2]} - {f[3]} | | | | {img}"))
            continue
        out.append((image_no(img), part_line(vehicle, f, names[f"i{k}"])))
    out.sort(key=lambda x: x[0])                      # stable: same number keeps arrival order
    text = "\n".join(l for _, l in out) + "\n"
    (run / "agent3_results.txt").write_text(text)
    print("Writing results.xlsx ...", file=sys.stderr, flush=True)
    v = subprocess.run([sys.executable, str(c.ROOT / "tools/agent3_validator.py"), str(run / "agent3_results.txt"),
                        str(run / "agent2_results.md")], capture_output=True, text=True)
    x = subprocess.run([sys.executable, str(c.ROOT / "harness/make_xlsx.py"), str(run / "agent3_results.txt"),
                        str(run / "results.xlsx")], capture_output=True, text=True)
    print(f"validator exit {v.returncode} | {(x.stdout or x.stderr).strip()[-120:]}")
    if v.returncode == 2:   # rows flagged: the whole report, so the bot's BEAR-V01 can list every one
        print(v.stdout)
    elif v.returncode:      # the check itself broke
        print((v.stderr or v.stdout)[-1200:])
    return text


if __name__ == "__main__":
    try:
        print(main(sys.argv[1], sys.argv[2]))
    except Stop as e:
        stop_exit(e)
