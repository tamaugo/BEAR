"""Stage 3 — pick the part number (when several readings verified) and the listing.

Jev's jobs (calibrated decisions over text it can fully see):
  1. choose_number: which verified reading is the part in the photo, given the
     vision description + each reading's eBay titles.
  2. listing_match: per listing, does the title describe the same item as the photo
     (component type + quantity)?  -> filters wrong assemblies / pairs / sets.
Deterministic: used-first, consensus price among matched listings, listing whose
price is closest to consensus (price and URL always from the same listing).
"""
import statistics, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c
import jev_client as j

USED_WORDS = ("used", "refurb", "remanufactured", "pre-owned", "for parts", "open box")


def is_used(it):
    return any(w in (it.get("condition") or "").lower() for w in USED_WORDS)


def drop_substring_readings(verified):
    """If reading A (with listings) contains reading B, B is a fragment of A."""
    live = [v for v in verified if v["listings"]]
    keep = []
    for v in live:
        nv = c.norm(v["text"])
        if any(nv != c.norm(o["text"]) and nv in c.norm(o["text"]) for o in live):
            continue
        keep.append(v)
    return keep


def choose_number(s1, live, vehicle):
    if len(live) == 1:
        return live[0], {"method": "single"}
    opts, state_r = {}, {}
    for i, v in enumerate(live):
        key = f"R{i+1}"
        titles = [(it.get("title") or "")[:110] for it in v["listings"][:6]]
        opts[key] = f"reading '{v['text']}'"
        state_r[key] = {"reading": v["text"], "vision_role": v["cand"].get("role"),
                        "legibility": v["cand"].get("legibility"), "vision_note": v["cand"].get("note"),
                        "uk_listings_with_this_number": len(v["listings"]),
                        "listings_mentioning_car_make": v["make_hits"],
                        "sample_listing_titles": titles}
    state = {"car": vehicle, "photo_shows": s1.get("part_description"),
             "photo_visual": s1.get("visual_features"), "readings": state_r}
    q = {"number": {"type": "choice", "instructions": (
        "A vision model read several possible part numbers off ONE car part photo. Each reading was "
        "searched on eBay UK. Which reading is the OEM part number of the part actually in the photo? "
        "Prefer the reading whose listings describe the same component as the photo, for the stated car, "
        "and that the vision model marked as the primary number. Fragments, supplier codes and "
        "sub-component numbers are wrong."), "criteria": opts}}
    r = c.jev(state, q, tag="choose_number")
    pick = j.get_value(r, "number")
    idx = int(pick[1:]) - 1
    return live[idx], {"method": "jev", "confidence": j.get_confidence(r, "number"),
                       "probs": j.get_probabilities(r, "number")}


def listing_match(s1, listings, vehicle, cap=60):
    """Veto question. The component identity comes from the MARKET (what most sellers of this
    exact number call it), not from the vision description: a cheap vision model misnamed the
    parking-brake switch as a 'window switch' and every genuine listing got vetoed (r2, IMG_4784).
    Vision still supplies the quantity in the photo."""
    listings = listings[:cap]
    state = {"car": vehicle,
             "photo": {"items_in_photo": s1.get("item_count", 1),
                       "rough_description_may_be_imprecise": s1.get("part_description")},
             "listings": {f"L{i+1}": (it.get("title") or "") for i, it in enumerate(listings)}}
    qs = {f"L{i+1}": {"type": "noul", "instructions": (
        f"All these listings carry the same part number. Is listing L{i+1} selling the same single "
        "component that the majority of the listings are selling, in the same quantity as the photo? "
        "Answer false if L{i+1} is a pair/set/multiple pieces when the photo has one item, a larger "
        "assembly or different component that merely includes this number, or clearly a different "
        "part from what most sellers list.")}
        for i in range(len(listings))}
    r = c.jev(state, qs, tag="listing_match")
    return [(it, j.get_value(r, f"L{i+1}")) for i, it in enumerate(listings)]


import math

EXCLUDE_BELOW = 0.2   # Jev listing-match is a VETO for clear mismatches (pairs/sets/other
                      # assemblies score ~0.03), not a ranking: photo descriptions from a cheap
                      # vision model are too vague to rank genuine listings (measured 2026-09-30).


def sell_price(p):
    """Operator rule, read off his corrected sheet: smallest x.99 >= price-0.01, floor 19.99.
    25.00->24.99, 24.98->24.99, 23.57->23.99, 20.42->20.99, 12.49->19.99, 100.00->99.99."""
    p = round(float(p), 2)
    r = math.floor(p - 0.01 + 1e-9) + 0.99
    if r < p - 0.01 - 1e-9:
        r += 1
    return max(19.99, round(r, 2))


def price_bucket(p):
    """x.99 bucket WITHOUT the 19.99 floor, so 12.49/12.50 group together but cheap
    listings never merge with a real 19.99 (floor merging would let junk win the vote)."""
    p = round(float(p), 2)
    r = math.floor(p - 0.01 + 1e-9) + 0.99
    if r < p - 0.01 - 1e-9:
        r += 1
    return round(r, 2)


def consensus_price(prices):
    """Operator rule (2026-09-30): the MOST COMMON price wins. e.g. 2x19.99, 4x64.99,
    3x43.99 + 6 singles -> 64.99. Tie between most-common prices -> lower median of the
    tied values. No price repeats at all -> lower median of everything."""
    b = sorted(price_bucket(p) for p in prices)
    counts = {}
    for x in b:
        counts[x] = counts.get(x, 0) + 1
    top = max(counts.values())
    if top == 1:
        return b[(len(b) - 1) // 2]
    tied = sorted(x for x, n in counts.items() if n == top)
    if len(tied) > 1:
        # Tie-break: sellers at the IDENTICAL price is stronger agreement than prices that
        # only round to the same .99 (2x139.99 beats 104.70+105.00).
        exact = {x: max(sum(1 for p in prices if round(float(p), 2) == q)
                        for q in {round(float(p), 2) for p in prices if price_bucket(p) == x}) for x in tied}
        best = max(exact.values())
        tied = [x for x in tied if exact[x] == best]
    return tied[(len(tied) - 1) // 2]


def best_title(bucket, all_titles, part_number, vehicle):
    """Jev picks which of the equal-sell-price listings names the part best. State carries
    every title for the number so Jev can see what the market calls this part."""
    if len(bucket) == 1:
        return bucket[0], {"method": "single"}
    bucket = bucket[:40]
    opts = {f"T{i+1}": "" for i in range(len(bucket))}
    state = {"car": vehicle, "part_number": part_number,
             "what_all_uk_sellers_call_this_part_number": all_titles[:40],
             "candidate_titles": {f"T{i+1}": (it.get("title") or "") for i, it in enumerate(bucket)}}
    q = {"title": {"type": "choice", "instructions": (
        "These eBay listings all sell the same used car part at the same price. Which candidate title "
        "names the part most accurately and completely, the way most sellers of this part number "
        "describe it? Reject titles that name a different or larger component, a pair/set, only a "
        "vague word, or that are mostly seller codes."), "criteria": opts}}
    r = c.jev(state, q, tag="best_title")
    k = j.get_value(r, "title")
    return bucket[int(k[1:]) - 1], {"method": "jev", "confidence": j.get_confidence(r, "title")}


def pick_listing(scored, part_number="", vehicle=""):
    """scored: [(item, p)]. Returns (item, info). Price and URL always from the same listing."""
    if not scored:
        return None, {}
    matched = [(it, p) for it, p in scored if p >= EXCLUDE_BELOW] or [max(scored, key=lambda x: x[1])]
    used = [(it, p) for it, p in matched if is_used(it)]
    pool = used or matched
    consensus = consensus_price([float(it["price"]["value"]) for it, _ in pool])
    target = max(19.99, consensus)
    bucket = [it for it, _ in pool if price_bucket(it["price"]["value"]) == consensus]
    all_titles = [it.get("title") or "" for it, _ in pool]
    chosen, tinfo = best_title(bucket, all_titles, part_number, vehicle)
    return chosen, {"matched": len(matched), "used": len(used), "consensus": consensus,
                    "market_titles": all_titles,
                    "sell_price": target, "bucket": len(bucket), "title_pick": tinfo}
