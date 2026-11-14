#!/usr/bin/env python3
"""#part-id's eBay photo search, for a part with no part number: the photo posted in #part-id is sent to
eBay UK's search-by-image (car parts only) and the 3 look-alike listings come back, used ones first,
then in eBay's own order. They are suggestions to check by eye, never a BEAR price.

The eBay call is bear2/image_hints.py's search_by_image, used as it is (shared plumbing like
bear2/common.py; nothing in bear2/ changes for #part-id). Free: eBay's API only, no model.

Prints one JSON object on stdout: {"seconds", "matches": [{"title", "price", "category", "url", "image"}]}
(up to 3; category = the eBay category ID the listing is filed under, as in the main sheet).

BEAR_SIM set (dev mode): made-up matches, no call.

usage: python3 partid/photo_search.py <photo>
"""
import collections, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bear2"))

HOW_MANY = 3
SIM = [{"title": f"(dev mode) made-up look-alike listing {k}", "price": round(10.0 * k + 4.99, 2),
        "category": str(33645 + k), "url": f"https://www.ebay.co.uk/itm/{100000000000 + k}", "image": None} for k in range(1, HOW_MANY + 1)]


def search(path):
    """Up to 3 look-alike eBay UK listings for the photo: [{"title", "price", "category", "url", "image"}]."""
    if os.environ.get("BEAR_SIM"):
        return [dict(m) for m in SIM]
    import common as c
    import image_hints as h
    items = h.rank(h.search_by_image(Path(path)), collections.Counter())[:HOW_MANY]   # no car: used first
    out = []
    for it in items:
        s = c.summarize(it)
        out.append({"title": s["title"] or "", "price": s["price"], "category": s["category"], "url": s["url"],
                    "image": s["image"]})
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__.split("usage: ")[1])
    started = time.time()
    found = search(sys.argv[1])
    print(json.dumps({"seconds": round(time.time() - started, 1), "matches": found}))
