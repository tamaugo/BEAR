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
    listings = listings[:cap]
    state = {"photo_of_part": {"description": s1.get("part_description"),
                               "items_in_photo": s1.get("item_count", 1),
                               "visual": s1.get("visual_features"), "car": vehicle},
             "listings": {f"L{i+1}": (it.get("title") or "") for i, it in enumerate(listings)}}
    qs = {f"L{i+1}": {"type": "noul", "instructions": (
        f"Is listing L{i+1} selling the same thing that is in the photo: the same kind of component and "
        "the same quantity? A listing for a pair/set/multiple pieces, a larger assembly the part is only "
        "attached to, or a different component that shares the number does NOT match.")}
        for i in range(len(listings))}
    r = c.jev(state, qs, tag="listing_match")
    return [(it, j.get_value(r, f"L{i+1}")) for i, it in enumerate(listings)]


def pick_listing(scored):
    """scored: [(item, p)]. Returns (item, info)."""
    if not scored:
        return None, {}
    best = max(p for _, p in scored)
    thr = max(0.5, best - 0.2)
    matched = [(it, p) for it, p in scored if p >= thr] or [max(scored, key=lambda x: x[1])]
    used = [(it, p) for it, p in matched if is_used(it)]
    pool = used or matched
    prices = sorted(float(it["price"]["value"]) for it, _ in pool)
    # consensus: most common price if strictly most common, else lower median
    counts = {}
    for pr in prices:
        counts[pr] = counts.get(pr, 0) + 1
    top = max(counts.values())
    tops = [pr for pr, n in counts.items() if n == top]
    consensus = tops[0] if len(tops) == 1 and top > 1 else prices[(len(prices) - 1) // 2]
    # listing closest to consensus; tie -> highest Jev match, then eBay order
    order = {id(it): k for k, (it, _) in enumerate(pool)}
    chosen = min(pool, key=lambda x: (abs(float(x[0]["price"]["value"]) - consensus), -x[1], order[id(x[0])]))
    return chosen[0], {"matched": len(matched), "used": len(used), "consensus": consensus,
                       "jev_p": chosen[1], "thr": thr}
