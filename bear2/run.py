"""BEAR v2 end-to-end runner (stages 1-3). Writes Agent-2-shaped lines
(`filename | part_number | title | category | price | url`, category = the eBay category ID of
the listing BEAR picked) for assemble.py + validator + make_xlsx.py, plus a JSON trace.

usage: python3 bear2/run.py <photo_dir> "<VEHICLE STRING>" <out_dir> [--s1 cached_stage1.json]
       python3 bear2/run.py <photo_dir> "<VEHICLE STRING>" <out_dir> --names-only
         (finish only the names of a run in out_dir that stopped at the names)
"""
import json, sys, threading, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c, stage1_read as s1m, stage2_numbers as s2, stage2b_rescue as s2b, stage3_listing as s3, assemble, image_hints

FAIL1 = "FAILED | Agent 1 | Could Not Produce Clear Part Number"
FAIL_NF = "FAILED | Agent 2 | No eBay Listing Found"
FAIL_UN = "FAILED | Agent 2 | eBay Lookup Unavailable"
FAIL_PHOTO = "FAILED | Agent 1 | Photo Could Not Be Opened"      # corrupt or not really an image
FAIL_READ = "FAILED | Agent 1 | Photo Read Unavailable"          # the reading model failed after its retries


def stops_run(e):
    """Errors that would hit every photo, so the run still stops and the bot reports them:
    BEAR's spend cap (BEAR-K02), OpenRouter out of credit (HTTP 402, BEAR-K01), a bad key (401)."""
    return any(t in str(e) for t in ("spend cap reached", "OpenRouter HTTP 402", "OpenRouter HTTP 401"))


def read_failure(path, e):
    """The FAILED reason for a photo whose read raised e: the photo itself, or the reading model."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
    except Exception:
        return FAIL_PHOTO
    return FAIL_READ


def read_all(photos, read, tick=None):
    """{name: stage 1 read} for every photo, read 6 at a time. One photo that can't be read (a
    corrupt image, or a model call that fails after all its retries) becomes a FAILED row instead
    of ending the run: returns (reads, {name: (FAILED reason, error text)}). Errors that would hit
    every photo (stops_run), or every photo failing, still stop the run as before."""
    errors = {}

    def one(p):
        try:
            return read(p)
        except Exception as e:
            if stops_run(e):
                raise
            errors[p.name] = (read_failure(p, e), e)
            return None
        finally:
            if tick:
                tick()
    with cf.ThreadPoolExecutor(6) as ex:
        reads = dict(zip([p.name for p in photos], ex.map(one, photos)))
    # The reading model failed on some photos (a busy spell): give each one more try at the end.
    for p in [p for p in photos if errors.get(p.name, ("",))[0] == FAIL_READ]:
        try:
            reads[p.name] = read(p)
            del errors[p.name]
        except Exception as e:
            if stops_run(e):
                raise
            errors[p.name] = (FAIL_READ, e)
    if errors and len(errors) == len(photos) and any(why != FAIL_PHOTO for why, _ in errors.values()):
        raise next(iter(errors.values()))[1]   # nothing was read at all: an outage, not a photo
    reads = {k: v for k, v in reads.items() if k not in errors}   # stage1.json holds real reads only
    return reads, {k: (why, f"{type(e).__name__}: {str(e)[:200]}") for k, (why, e) in errors.items()}


FAIL_JEV = "FAILED | Agent 2 | Jev Unavailable"
FAIL_MODEL = "FAILED | Agent 2 | Model Unavailable"        # an OpenRouter chat call (the photo check)
FAIL_MONEY = "FAILED | Agent 2 | Spend Limit Reached"      # BEAR's cap or OpenRouter credit (K02 / K01)
FAIL_ERR = "FAILED | Agent 2 | Unexpected Error"


def fail_cause(e):
    """The FAILED row for a part whose pricing raised e: the service that really failed."""
    text = str(e)
    if "spend cap reached" in text or "OpenRouter HTTP 402" in text:
        return FAIL_MONEY
    if isinstance(e, c.JevFailed):
        return FAIL_JEV
    if "OpenRouter" in text:
        return FAIL_MODEL
    if "eBay" in text or isinstance(e, c.NETWORK_ERRORS):
        return FAIL_UN
    return FAIL_ERR


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
    ebay_errors = [f"{v['text']}: {v['error']}" for v in verified if v.get("error")]
    live = s3.drop_substring_readings(verified)
    # Rescue unless a PRIMARY-role reading is strongly listed. Secondary junk like "10 10 3"
    # (150 substring hits) must not suppress the rescue (IMG_3931, pt2).
    if not any(len(v["listings"]) >= s2b.STRONG and v["cand"].get("role") == "primary" for v in live):
        # hard read: try confusable-character / revision-suffix rescues
        rescued = s2b.rescue(s1, make, ebay_errors)
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
        if ebay_errors:   # a search that failed might have found it: say eBay, not "no listing"
            tr["ebay_errors"] = ebay_errors[:20]
            return f"{name} | {FAIL_UN}", tr
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
    return f"{name} | {out_number} | {title} | {s['category']} | {price} | {s['url']}", tr


def progress(label, total):
    """Thread-safe `label n/total` counter on stderr, so long jobs visibly move."""
    lock, done = threading.Lock(), [0]

    def tick(*_):
        with lock:
            done[0] += 1
            end = "\n" if done[0] >= total else ""
            print(f"\r{label} {done[0]}/{total}", end=end, file=sys.stderr, flush=True)
    return tick


def main():
    photo_dir, vehicle, out_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    make = vehicle.split()[0]
    s1_cache = sys.argv[sys.argv.index("--s1") + 1] if "--s1" in sys.argv else None
    out_dir.mkdir(parents=True, exist_ok=True)
    c.prune_ebay_cache()
    spend0 = c.total_spend()
    photos = sorted(p for p in photo_dir.iterdir() if p.suffix.lower() in c.PHOTO_EXT)
    if "--names-only" in sys.argv:
        return finish(out_dir, photo_dir, vehicle, spend0, len(photos))
    print(f"{len(photos)} photos to price. This takes a few minutes for a big job.", file=sys.stderr, flush=True)
    S1 = json.loads(Path(s1_cache).read_text()) if s1_cache else {}
    rest = photos
    if not s1_cache:
        reads, unread = read_all(rest, lambda p: s1m.read_photo_cached(p, vehicle),
                                 progress("Reading part numbers", len(rest)))
        S1.update(reads)
    else:
        unread = {}
    (out_dir / "stage1.json").write_text(json.dumps(S1, indent=1))
    lines, trace = {}, {}
    for name, (why, err) in unread.items():
        lines[name], trace[name] = f"{name} | {why}", {"error": err}
    rest = [p for p in rest if p.name not in unread]
    with cf.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(process, p.name, S1.get(p.name), vehicle, make, p): p.name for p in rest}
        tick = progress("Pricing on eBay", len(rest))
        for f in futs:
            f.add_done_callback(tick)
        for f in futs:
            try:
                lines[futs[f]], trace[futs[f]] = f.result()
            except Exception as e:
                lines[futs[f]] = f"{futs[f]} | {fail_cause(e)}"
                trace[futs[f]] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
    ordered = [lines[p.name] for p in photos]
    (out_dir / "agent2_results.md").write_text("\n".join(ordered) + "\n")
    (out_dir / "trace.json").write_text(json.dumps(trace, indent=1, default=str))
    finish(out_dir, photo_dir, vehicle, spend0, len(photos))


def finish(out_dir, photo_dir, vehicle, spend0, n):
    """Names, results.xlsx and image hints."""
    print("Building results.xlsx ...", file=sys.stderr, flush=True)
    try:
        print(assemble.main(out_dir, vehicle))
    except assemble.Stop as e:
        assemble.stop_exit(e)
    print("Looking for possible matches for unpriced photos ...", file=sys.stderr, flush=True)
    try:
        added = image_hints.main(out_dir, photo_dir, vehicle)
        if added:
            print(f"Added {added} possible-match rows (shaded, check by eye) under unpriced photos in results.xlsx")
    except Exception as e:  # hints are a convenience; never fail the run over them
        print(f"(image hints skipped: {type(e).__name__})")
    cost = c.total_spend() - spend0
    print(f"\nrun cost ${cost:.4f} for {n} parts (${cost/max(1,n):.5f}/part); total spend ${c.total_spend():.4f}")


if __name__ == "__main__":
    main()
