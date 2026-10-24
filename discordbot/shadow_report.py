#!/usr/bin/env python3
"""What the shadow test (shadow.py) found, from <storage>/shadow/shadow.jsonl. No network, no cost.

1. Part-number photos: could the model have picked the 💸 photos on its own? For each cut-off:
   the 💸 photos it would have missed, and the other photos it would have picked by mistake
   (split into ones next to a 💸 photo, likely a second shot of the label, and the rest).
2. Locations on the 💸 photos: what each model read, how often the models agree. Staff's
   locations aren't in the log, so to score the models:
     --review review.csv   writes one row per 💸 photo with a link and each model's answer;
                           fill in the "truth" column with NF, OF, NR, OR or NONE (blank = skip)
     --truth review.csv    scores each model, and Luna confirmed by a second model, against it

usage: python3 discordbot/shadow_report.py [shadow.jsonl] [--review review.csv] [--truth review.csv]
"""
import argparse, csv, os, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import jev_client  # noqa: E402
import shadow as sh  # noqa: E402

CUTS = (0.5, 0.7, 0.8, 0.9, 0.95)
SURE = 0.85   # Luna alone at or above this; below it, a second model has to agree
CODES = (*sh.LOCATIONS, "NONE")


def default_log():
    storage = os.environ.get("BEAR_STORAGE") or jev_client._parse_dotenv(jev_client.ENV_FILE).get("BEAR_STORAGE")
    return Path(storage or HERE.parent / "runs") / "shadow" / "shadow.jsonl"


def short(name):
    return name.split("/")[-1]


def label_section(rows):
    ok = [r for r in rows if r.get("model") == sh.LABEL_MODEL and r.get("label") is not None]
    flagged = [r for r in ok if r["flagged"]]
    others = [r for r in ok if not r["flagged"]]
    # Photos right before or after a 💸 photo in the same folder run: likely another shot of the label.
    near = {(r["channel"], r["marker"], r["n"] + d) for r in flagged for d in (-1, 1)}
    out = [f"## 1. Finding the part-number photo ({short(sh.LABEL_MODEL)})", "",
           f"{len(flagged)} 💸 photos and {len(others)} other photos answered.", "",
           "| Cut-off | 💸 missed | Others picked: next to a 💸 | Others picked: elsewhere |",
           "|---|---|---|---|"]
    for cut in CUTS:
        missed = sum(1 for r in flagged if r["label"] < cut)
        picked = [r for r in others if r["label"] >= cut]
        by_label = sum(1 for r in picked if (r["channel"], r["marker"], r["n"]) in near)
        out.append(f"| {cut} | {missed} of {len(flagged)} | {by_label} | {len(picked) - by_label} |")
    out += ["", "Lowest-scored 💸 photos (would be missed first):"]
    out += [f"- {r['label']:.2f} {r['folder']} #{r['n']} {r['url']}" for r in sorted(flagged, key=lambda r: r["label"])[:5]]
    out += ["", "Highest-scored other photos (would be picked first by mistake):"]
    out += [f"- {r['label']:.2f} {r['folder']} #{r['n']} {r['url']}"
            for r in sorted(others, key=lambda r: -r["label"])[:5]]
    return out


def by_photo(rows):
    """{url: {model: row}} for the 💸 photos' location answers."""
    out = {}
    for r in rows:
        if r.get("flagged") and r.get("loc"):
            out.setdefault(r["url"], {})[r["model"]] = r
    return out


def models_of(photos):
    return [sh.LABEL_MODEL] + sorted({m for p in photos.values() for m in p} - {sh.LABEL_MODEL})


def confirmed(luna, other):
    """Luna's answer if it is sure, or if the other model picked the same code; else blank."""
    if not luna:
        return None
    if luna["loc_p"].get(luna["loc"], 0) >= SURE:
        return luna["loc"]
    return luna["loc"] if other and other["loc"] == luna["loc"] else None


def location_section(rows, truth):
    photos = by_photo(rows)
    models = models_of(photos)
    out = ["", "## 2. Reading the location on the 💸 photos", "", f"{len(photos)} 💸 photos answered.", "",
           "| Model | " + " | ".join(CODES) + " |", "|---" * (len(CODES) + 1) + "|"]
    for m in models:
        c = Counter(p[m]["loc"] for p in photos.values() if m in p)
        out.append(f"| {short(m)} | " + " | ".join(str(c[k]) for k in CODES) + " |")
    luna = sh.LABEL_MODEL
    for m in models[1:]:
        both = [p for p in photos.values() if luna in p and m in p]
        same = sum(1 for p in both if p[luna]["loc"] == p[m]["loc"])
        out.append(f"\n{short(luna)} and {short(m)} agree on {same} of {len(both)}.")
    if not truth:
        return out + ["", "To score them: --review review.csv, fill in the truth column, then --truth review.csv."]
    known = {u: t for u, t in truth.items() if u in photos}
    out += ["", f"Scored against {len(known)} photos with a truth filled in.", "",
            "| Model | Cut-off | Right | Wrong | Left blank |", "|---|---|---|---|---|"]
    for m in models:
        for cut in CUTS:
            right = wrong = blank = 0
            for u, t in known.items():
                r = photos[u].get(m)
                if not r or r["loc_p"].get(r["loc"], 0) < cut:
                    blank += 1
                elif r["loc"] == t:
                    right += 1
                else:
                    wrong += 1
            out.append(f"| {short(m)} | {cut} | {right} | {wrong} | {blank} |")
    out += ["", f"Luna alone at {SURE} or more, otherwise only if the second model agrees:", "",
            "| Second model | Right | Wrong | Left blank |", "|---|---|---|---|"]
    for m in models[1:]:
        got = [(confirmed(photos[u].get(luna), photos[u].get(m)), t) for u, t in known.items()]
        right = sum(1 for g, t in got if g is not None and g == t)
        wrong = sum(1 for g, t in got if g is not None and g != t)
        out.append(f"| {short(m)} | {right} | {wrong} | {len(got) - right - wrong} |")
    return out


def write_review(rows, path):
    photos = by_photo(rows)
    models = models_of(photos)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["folder", "photo", "link", *(short(m) for m in models), "truth"])
        for u, p in photos.items():
            any_row = next(iter(p.values()))
            w.writerow([any_row["folder"], any_row["n"], u,
                        *(f"{p[m]['loc']} {p[m]['loc_p'].get(p[m]['loc'], 0):.2f}" if m in p else "" for m in models), ""])
    print(f"wrote {len(photos)} rows to {path}: fill in the truth column (NF, OF, NR, OR or NONE)")


def read_truth(path):
    with open(path, newline="") as f:
        return {r["link"]: r["truth"].strip().upper() for r in csv.DictReader(f)
                if r.get("truth", "").strip().upper() in CODES}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log", nargs="?", type=Path, default=None)
    ap.add_argument("--review", type=Path)
    ap.add_argument("--truth", type=Path)
    args = ap.parse_args()
    path = args.log or default_log()
    records = sh.read_log(path)
    if not records:
        sys.exit(f"Nothing logged yet in {path}")
    rows = sh.latest_runs(records)
    folders, parts = sh.counts(records)
    errors = Counter(short(r["model"]) for r in rows if r.get("error"))
    cost = sum(r.get("cost") or 0 for r in records)
    out = [f"# Shadow test: {folders} folders, {parts} 💸 photos", "",
           f"Spent ${cost:.4f} in all." + (f" Errors: {dict(errors)}." if errors else " No errors."), ""]
    out += label_section(rows)
    out += location_section(rows, read_truth(args.truth) if args.truth else None)
    print("\n".join(out))
    if args.review:
        write_review(rows, args.review)


if __name__ == "__main__":
    main()
