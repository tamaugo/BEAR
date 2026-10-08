"""Deterministic Agent 3 replacement. The ONLY model job left is cleaning the eBay title
into a part name (one cheap call per job, JSON in/out). Everything with a contract —
vehicle string, location from filename, part number, price, URL, image, sort, failure
and NULL rows — is code, so it cannot be corrupted.

Why: live run r7, Agent 3 (qwen3.8-flash) wrote url itm/168603Z210 (part number blended
into the link) and dropped the image field. URL and image are copy-through fields; a model
has no business touching them.

Name models never fall back silently (issue 19): if the name model is unavailable or gives an
unusable answer, BEAR stops and asks (or, with no one to ask, stops). The old mechanical
cleaner that wrote the messy names now lives in legacy/ and is not used. Before a full run
the operator approves one finished line (`verify`) and can switch between the NAME_MODELS.
Questions go through an `ask(text, choices)` function: `terminal_ask` in the Terminal; the
web page can supply its own later. ask=None = stop.

usage: python3 bear2/assemble.py <run_dir> "<VEHICLE STRING>"
Writes <run_dir>/agent3_results.txt (4-field contract) and results.xlsx. Re-running it on a
saved run redoes only the names (the photo reads and eBay results are not paid for again).
"""
import json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

LOC = {"NSF": "Near Side Front", "NSR": "Near Side Rear", "OSF": "Off Side Front", "OSR": "Off Side Rear"}
MODEL = "qwen/qwen3.8-flash"   # default name model for every setup; update with the setups
NAME_MODELS = {MODEL: "Qwen 3.8 Flash",
               "google/gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
               "anthropic/claude-haiku-5.5": "Claude Haiku 5.5"}
CHECK_FILE = "names_check.json"   # the approved first line: image, model, name
CHECK_ATTEMPTS = 2                # the first-line check gives up on a busy model in seconds
INSTRUCTIONS_BAD = ("Every name model gave a bad line, so the problem is the cleaning instructions "
                    "(CLEAN_PROMPT in bear2/assemble.py), not the models. Stopped.")

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


class Stop(Exception):
    """The run stops here with a message for the operator. Nothing is written in place of names."""


class NamesFailed(Exception):
    """The name model was unavailable, errored or gave an unusable answer."""


def label(model):
    return NAME_MODELS.get(model, model)


def clean_names(rows, model=MODEL, attempts=c.CHAT_ATTEMPTS):
    """{id: agent2 row fields} -> {id: tidy name} for every row, or NamesFailed. Never partial,
    never a mechanical stand-in: a name that can't be used stops the run like an outage does."""
    if not rows:
        return {}
    user = EXAMPLES + "\nItems:\n" + json.dumps({k: title_item(f) for k, f in rows.items()}, indent=0)
    try:
        out, raw = c.chat(model, [{"role": "system", "content": CLEAN_PROMPT}, {"role": "user", "content": user}],
                          max_tokens=3000, response_format={"type": "json_object"},
                          extra={"reasoning": {"effort": "none", "exclude": True}}, tag="clean_names",
                          attempts=attempts)
    except Exception as e:
        raise NamesFailed(f"{label(model)} is unavailable: {str(e)[:160]}") from None
    m = re.search(r"\{.*\}", out, re.S)
    try:
        names = json.loads(m.group(0)).get("names")
    except Exception:
        names = None
    if not isinstance(names, dict):
        raise NamesFailed(f"{label(model)} gave an unusable answer (no names)")
    tidy = {}
    for k, f in rows.items():
        tidy[k] = tidy_name(names.get(k), f[1])
        if not tidy[k]:
            raise NamesFailed(f"{label(model)} gave a name BEAR can't use for {f[0]}: {names.get(k)!r}")
    return tidy


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


def title_item(f):
    return {"title": f[2], "locationcode": bool(location(f[0]))}


def part_line(vehicle, f, name):
    """The finished results line for a priced row, exactly as it is written to the results."""
    img, pn, price, url = f[0], f[1], f[-2], f[-1]
    loc = location(img)
    if loc:  # never repeat the operator's location words
        for w in loc.split():
            name = re.sub(rf"(?i)^{w}\b\s*", "", name) if w in ("Front", "Rear") else name
    info = f"{vehicle} - " + (f"{loc} " if loc else "") + f"{name} {c.norm(pn)}"
    return f"{info} | {price} | {url} | {img}"


def terminal_ask(text, choices):
    """Ask in the Terminal. choices: [(key, label)]; returns a key. Input closed = Stop."""
    print(f"\n{text}", flush=True)
    for k, lab in choices:
        print(f"  {k}) {lab}", flush=True)
    keys = [k for k, _ in choices]
    while True:
        try:
            a = input("Type a letter or number and press Enter: ").strip().lower()
        except EOFError:
            raise Stop("No answer (input closed). Stopped.") from None
        if a in keys:
            return a


def pick_model(ask, exclude, stopped):
    """The operator picks the next name model; None when none is left, Stop(stopped) if they stop."""
    left = [m for m in NAME_MODELS if m not in exclude]
    if not left:
        return None
    a = ask("Which name model next?", [(str(i + 1), label(m)) for i, m in enumerate(left)] + [("q", "Stop")])
    if a == "q":
        raise Stop(stopped)
    return left[int(a) - 1]


def verify(vehicle, f, ask, model=MODEL):
    """Show the operator one finished line and return the (model, name) they approved.
    A rejected model is not offered again; if all of them are rejected, Stop(INSTRUCTIONS_BAD)."""
    bad, stopped = set(), "Stopped at the first-line check."
    while True:
        try:
            name = clean_names({"i0": f}, model, attempts=CHECK_ATTEMPTS)["i0"]
        except NamesFailed as e:
            a = ask(str(e), [("r", "Try again"), ("m", "Pick another name model"), ("q", "Stop")])
            if a == "q":
                raise Stop(stopped)
            if a == "m":
                model = pick_model(ask, bad | {model}, stopped) or model
            continue
        if ask(f"Check this line (names by {label(model)}):\n  {part_line(vehicle, f, name)}",
               [("y", "Looks right, scan the rest"), ("n", "Wrong, try another name model")]) == "y":
            return model, name
        bad.add(model)
        if len(bad) == len(NAME_MODELS):
            raise Stop(INSTRUCTIONS_BAD)
        model = pick_model(ask, bad, stopped)


def resume_hint(run, vehicle):
    return (f"The photo reads and eBay results are saved in {run}.\n"
            f"To finish only the names later, run in Terminal:\n"
            f"  python3 bear2/assemble.py \"{run}\" \"{vehicle}\"")


def main(run_dir, vehicle, ask=None):
    """ask=None: no one to ask (the web page today), so a failed name model stops the run."""
    run = Path(run_dir)
    rows = [f for f in map(parse_row, (run / "agent2_results.md").read_text().splitlines()) if f]
    nulls = [n for n in (run / "null_files.txt").read_text().split("\n") if n.strip()] if (run / "null_files.txt").exists() else []
    check = json.loads((run / CHECK_FILE).read_text()) if (run / CHECK_FILE).exists() else {}
    model = check.get("model") or MODEL
    priced = {f"i{k}": f for k, f in enumerate(rows) if f[1] != "FAILED"}
    todo = {k: f for k, f in priced.items() if f[0] != check.get("image")}
    print(f"Cleaning part names ({label(model)}) ...", file=sys.stderr, flush=True)
    while True:
        try:
            names = clean_names(todo, model)
            break
        except NamesFailed as e:
            if not ask:
                raise Stop(f"{e}. No names were written.\n" + resume_hint(run, vehicle)) from None
            a = ask(f"{e}. No names were written.",
                    [("r", "Try again"), ("m", "Switch name model (check one line first)"), ("q", "Stop")])
            if a == "q":
                raise Stop(resume_hint(run, vehicle)) from None
            if a == "m":
                new = pick_model(ask, {model}, resume_hint(run, vehicle))
                if new:
                    f = next((f for f in priced.values() if f[0] == check.get("image")), None) or next(iter(priced.values()))
                    model, name = verify(vehicle, f, ask, new)
                    check = {"image": f[0], "model": model, "name": name}
                    (run / CHECK_FILE).write_text(json.dumps(check))
                    todo = {k: f for k, f in priced.items() if f[0] != check["image"]}
    if check.get("image"):
        names.update({k: check["name"] for k, f in priced.items() if f[0] == check["image"]})
    out = []
    for k, f in enumerate(rows):
        img = f[0]
        if f[1] == "FAILED":
            out.append((image_no(img), f"FAILED - {f[2]} - {f[3]} | | | {img}"))
            continue
        out.append((image_no(img), part_line(vehicle, f, names[f"i{k}"])))
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
    try:
        print(main(sys.argv[1], sys.argv[2], terminal_ask if sys.stdin.isatty() else None))
    except Stop as e:
        sys.exit(f"\n{e}")
