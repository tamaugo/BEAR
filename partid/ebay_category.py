#!/usr/bin/env python3
"""#part-id's eBay category for a part number: eBay UK is searched for the number the same way /run
checks a number (car parts only, the number as given and without spaces or dashes, kept only if the
listing really carries the number), and the category is the eBay category ID most of those listings
are filed under ("33546" = HVAC Blower Motors & Wheels), as in the "ebay ID Category:" column of the
main sheet. A tie goes to the listing eBay put first. No listing: no category ("").

Uses bear2/common.py's eBay search as it is (shared plumbing, like the rest of partid/). Free: eBay's
API only. Searches are kept for 24 hours, so the same number twice is one search.

Prints one JSON object on stdout: {"number", "category", "listings"} (listings = how many carry the number).

BEAR_SIM set (dev mode): a made-up category, no call.

usage: python3 partid/ebay_category.py <part number>
"""
import collections, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bear2"))

SIM = "33546"


def pick(categories):
    """The category most listings share ("" if none); a tie goes to the one seen first."""
    counts = collections.Counter(x for x in categories if x)
    if not counts:
        return ""
    best = max(counts.values())
    return next(x for x in categories if counts.get(x) == best)


def lookup(number):
    """{"number", "category", "listings"} for one part number."""
    if os.environ.get("BEAR_SIM"):
        return {"number": number, "category": SIM, "listings": 3}
    import common as c
    found = c.ebay_exact(number)
    return {"number": number, "category": pick([c.category_id(it) for it in found]), "listings": len(found)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.split("usage: ")[1])
    print(json.dumps(lookup(sys.argv[1])))
