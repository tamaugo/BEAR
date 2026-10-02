"""BEAR v2 end-to-end runner (stages 1-3). Writes Agent-2-shaped lines
(`filename | part_number | title | price | url`) so the existing Agent 3 +
validator + make_xlsx.py chain is unchanged downstream, plus a JSON trace.

usage: python3 bear2/run.py <photo_dir> "<VEHICLE STRING>" <out_dir> [--s1 cached_stage1.json]
"""
import json, sys, time, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c, stage1_read as s1m, stage2_numbers as s2, stage2b_rescue as s2b, stage3_listing as s3, assemble, image_hints

FAIL1 = "FAILED | Agent 1 | Could Not Produce Clear Part Number"
FAIL_NF = "FAILED | Agent 2 | No eBay Listing Found"
FAIL_UN = "FAILED | Agent 2 | eBay Lookup Unavailable"


def no_match_fail(s1):
    """A clearly-read primary number that no UK seller lists (or only lists as a different
    component) is an eBay miss, not a reading failure - tell the operator which it was."""
    clear = [x for x in s1.get("candidates") or [] if x.get("role") == "primary"
             and x.get("legibility") == "clear" and len(c.norm(x.get("text") or "")) >= 7]
    return FAIL_NF if clear else FAIL1


def process(name, s1, vehicle, make, photo_path=None):
    tr = {"s1": s1}
    if not s1 or not s1.get("candidates"):
        return f"{name} | {FAIL1}", tr
    verified = s2.verify(s1, make)
    tr["verified"] = [{"text": v["text"], "n": len(v["listings"]), "make": v["make_hits"],
                       "err": v.get("error")} for v in verified]
    if verified and all(v.get("error") for v in verified):
        return f"{name} | {FAIL_UN}", tr
    live = s3.drop_substring_readings(verified)
    # Rescue unless a PRIMARY-role reading is strongly listed. Secondary junk like "10 10 3"
    # (150 substring hits) must not suppress the rescue (IMG_3931, pt2).
    if not any(len(v["listings"]) >= s2b.STRONG and v["cand"].get("role") == "primary" for v in live):
        # hard read: try confusable-character / revision-suffix rescues
        rescued = s2b.rescue(s1, make)
        tr["rescued"] = [{"text": v["text"], "n": len(v["listings"]), "from": v["cand"].get("read_as"),
                          "how": v["cand"].get("rescue")} for v in rescued]
        live = s3.drop_substring_readings(live + rescued)
    raw_reads = [x.get("text") for x in s1.get("candidates") or [] if x.get("role") in ("primary", "unclear")] + \
                [a for x in s1.get("candidates") or [] if x.get("role") in ("primary", "unclear") for a in x.get("alt_readings") or []]
    raw_reads = [r for r in raw_reads if r]
    if not live and photo_path and raw_reads:
        st, tok = image_hints.corroborate(photo_path, "", raw_reads)
        tr["image_corroboration"] = (st, tok)
        if st == "better":
            items, err = s2.ebay_for(tok)
            if items:
                live = [{"text": tok, "cand": {"role": "primary", "rescue": "image-corroborated"},
                         "listings": items, "make_hits": 0}]
    if not live:
        return f"{name} | {no_match_fail(s1)}", tr
    chosen, info = s3.choose_number(s1, live, vehicle)
    tr["choose"] = {"text": chosen["text"], **info}
    weak = len(chosen["listings"]) < s2b.STRONG or chosen["cand"].get("rescue")
    if info.get("method") == "jev" and (info.get("confidence") or 0) < 0.5:
        prim = [v for v in live if v["cand"].get("role") == "primary" and not v["cand"].get("rescue")]
        if not (len(prim) == 1 and prim[0] is chosen):
            weak = True  # low confidence: must pass the component gate
    if weak and photo_path:
        st, tok = image_hints.corroborate(photo_path, chosen["text"], raw_reads)
        tr["image_corroboration"] = (st, tok)
        if st == "better" and c.norm(tok) not in {c.norm(v["text"]) for v in live}:
            items, err = s2.ebay_for(tok)
            if items:
                alt = {"text": tok, "cand": {"role": "primary", "rescue": "image-corroborated"},
                       "listings": items, "make_hits": 0}
                live = [alt] + live
                chosen = alt
                info = {"method": "image-corroborated", "probs": {"R1": 1.0}}
                tr["choose"] = {"text": tok, **info}
    if weak:
        ranked = sorted(live, key=lambda v: -(info.get("probs") or {}).get(f"R{live.index(v)+1}", 1 if v is chosen else 0))
        tr["gate"] = {"tried": []}
        passed = None
        for v in ranked[:3]:
            ok = s2b.visual_gate(str(photo_path), v)
            tr["gate"]["tried"].append((v["text"], ok))
            if ok:
                passed = v
                break
        if not passed:
            return f"{name} | {no_match_fail(s1)}", tr
        chosen = passed
        tr["choose"]["text"] = chosen["text"]
    out_number = chosen["cand"].get("read_as") if chosen["cand"].get("rescue") == "suffix-family" else chosen["text"]
    scored = s3.listing_match(s1, chosen["listings"], vehicle)
    tr["scored"] = [((it.get("legacyItemId") or it.get("itemId")), round(p, 2), it.get("title"),
                     it["price"]["value"], it.get("condition")) for it, p in scored]
    item, pinfo = s3.pick_listing(scored, chosen["text"], vehicle)
    tr["market_titles"] = pinfo.pop("market_titles", [])[:30]
    tr["pick"] = pinfo
    if not item:
        return f"{name} | {FAIL_NF}", tr
    s = c.summarize(item)
    title = (s["title"] or "").replace("|", " ")
    # Operator-rule sell price (x.99, floor 19.99) computed here so Agent 3's own
    # round-up rule is a no-op on it (x.99 stays x.99).
    price = f"{pinfo['sell_price']:.2f}"
    return f"{name} | {out_number} | {title} | {price} | {s['url']}", tr


def main():
    photo_dir, vehicle, out_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    make = vehicle.split()[0]
    s1_cache = sys.argv[sys.argv.index("--s1") + 1] if "--s1" in sys.argv else None
    out_dir.mkdir(parents=True, exist_ok=True)
    spend0 = c.total_spend()
    photos = sorted(p for p in photo_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    nulls = [p.name for p in photos if "NULL" in p.stem.upper().replace("-", " ").replace("_", " ").split()]
    photos = [p for p in photos if p.name not in nulls]
    if s1_cache:
        S1 = json.loads(Path(s1_cache).read_text())
    else:
        with cf.ThreadPoolExecutor(6) as ex:
            S1 = dict(zip([p.name for p in photos], ex.map(lambda p: s1m.read_photo_robust(p, vehicle), photos)))
    (out_dir / "stage1.json").write_text(json.dumps(S1, indent=1))
    lines, trace = {}, {}
    with cf.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(process, p.name, S1.get(p.name), vehicle, make, p): p.name for p in photos}
        for f in futs:
            try:
                lines[futs[f]], trace[futs[f]] = f.result()
            except Exception as e:
                lines[futs[f]] = f"{futs[f]} | {FAIL_UN}"
                trace[futs[f]] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    ordered = [lines[p.name] for p in photos]
    (out_dir / "agent2_results.md").write_text("\n".join(ordered) + "\n")
    (out_dir / "null_files.txt").write_text("\n".join(nulls))
    (out_dir / "trace.json").write_text(json.dumps(trace, indent=1, default=str))
    (out_dir / "null_files.txt").write_text("\n".join(nulls))
    (out_dir / "market_titles.json").write_text(json.dumps({k: v.get("market_titles", []) for k, v in trace.items()}))
    print(assemble.main(out_dir, vehicle))
    try:
        n = image_hints.main(out_dir, photo_dir, vehicle)
        if n:
            print(f"Added {n} possible-match rows (shaded, check by eye) under unpriced photos in results.xlsx")
    except Exception as e:  # hints are a convenience; never fail the run over them
        print(f"(image hints skipped: {type(e).__name__})")
    cost = c.total_spend() - spend0
    print(f"\nrun cost ${cost:.4f} for {len(photos)} parts (${cost/max(1,len(photos)):.5f}/part); total spend ${c.total_spend():.4f}")


if __name__ == "__main__":
    main()
