#!/usr/bin/env python3
"""Offline checks for part-name tidying and the finished line layout (no network, no cost).

The layout is the owner-approved Q269 sheet (2026-10-05, listed on eBay):
  HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL - Front Fog Light 922023Z010 | 24.99 | <url> | IMG_4969-OSF.JPEG
with the eBay category ID added after the price (2026-11-08):
  ... 922023Z010 | 24.99 | 33709 | <url> | IMG_4969-OSF.JPEG

The NSF/NSR/OSF/OSR location words were removed from the server code (the bot names photos
001.jpg ...), so the finished line carries the tidied name as-is and the filename is passed
through untouched, even when it contains a location word.

usage: python3 tests/test_names_offline.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bear2"))
import assemble as a  # noqa: E402

V = "HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL"
FOG_OSF = ["IMG_4969-OSF.JPEG", "922023Z010", "HYUNDAI I40 FRONT RIGHT FOG LIGHT 92202-3Z010",
           "33709", "24.99", "https://www.ebay.co.uk/itm/800068400352"]
# A run saved before the category field: the category is left blank.
FOG = ["IMG_4976.-NSFJPEG.JPEG", "922013Z010", "HYUNDAI I40 FRONT LEFT FOG LIGHT 92201-3Z010",
       "24.99", "https://www.ebay.co.uk/itm/167617751562"]

CASES = [  # (model's name, part number, expected tidy name or None = BEAR stops and asks)
    ("Fog Light", "922023Z010", "Fog Light"),
    ("fog LIGHT", "922023Z010", "Fog Light"),
    ("Relay MB627895", "MB627895", "Relay"),                     # part number left in: removed
    ("Headlamp Cap 1061 KFA04", "LP 1061 KFA04", "Headlamp Cap"),
    ("Srs & Ecu Module", "959103Z300", "Srs & Ecu Module"),
    ("Relay | Omron", "MB627895", "Relay Omron"),
    ("", "MB627895", None),
    ("MB627895", "MB627895", None),                              # nothing left but the number
    ("Relay 25252701", "MB686443", None),                        # a different long number
    (None, "MB627895", None),
    (42, "MB627895", None),
    ("x" * 95, "MB627895", None),
]


def main():
    bad = 0
    for name, pn, want in CASES:
        got = a.tidy_name(name, pn)
        if got != want:
            bad += 1
            print(f"FAIL tidy_name({name!r}, {pn!r}) = {got!r}, want {want!r}")
    lines = [a.part_line(V, FOG_OSF, "Front Fog Light"), a.part_line(V, FOG, "Front Fog Light")]
    want = ["HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL - Front Fog Light 922023Z010 | 24.99 | 33709 | "
            "https://www.ebay.co.uk/itm/800068400352 | IMG_4969-OSF.JPEG",
            "HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL - Front Fog Light 922013Z010 | 24.99 |  | "
            "https://www.ebay.co.uk/itm/167617751562 | IMG_4976.-NSFJPEG.JPEG"]
    for got, exp in zip(lines, want):
        if got != exp:
            bad += 1
            print(f"FAIL line\n  got  {got}\n  want {exp}")
    bad += spend_checks()
    print("all passed" if not bad else f"{bad} failed")
    return 1 if bad else 0


def spend_checks():
    """Spend saving without changing results: token counts in the ledger, saved reads reused for a
    byte-identical photo, no Jev call for a single listing, old eBay cache files deleted."""
    import json, os, tempfile, time
    import common as c, stage1_read as s1, stage3_listing as s3
    fails = []

    def check(what, got, want):
        if got != want:
            fails.append(what)
            print(f"FAIL {what}: got {got!r}, want {want!r}")
    tmp = Path(tempfile.mkdtemp(prefix="bear-spend-test-"))
    saved = c.LEDGER, c.CACHE, s1.READS, s1.read_photo_robust, c.jev
    c.LEDGER, c.CACHE, s1.READS = tmp / "spend.jsonl", tmp, tmp / "reads"
    try:
        # a. token counts next to the cost
        c.log_spend("chat", "m", 0.001, {"tag": "x"}, {"prompt_tokens": 1200, "completion_tokens": 80,
                                                       "completion_tokens_details": {"reasoning_tokens": 30}})
        line = json.loads(c.LEDGER.read_text().splitlines()[-1])
        check("ledger tokens", (line["cost"], line["prompt_tokens"], line["completion_tokens"], line["reasoning_tokens"]),
              (0.001, 1200, 80, 30))

        # b. a saved read is reused for the same photo, model, prompt and vehicle, at cost 0
        photo = tmp / "001.jpg"
        photo.write_bytes(b"photo bytes A")
        reads = []

        def fake_read(path, vehicle, model=s1.MODEL):
            reads.append((Path(path).read_bytes(), vehicle, model))
            found = b"blank" not in Path(path).read_bytes()
            return {"candidates": [{"text": "1K0615601", "role": "primary"}] if found else [], "_cost": 0.002}
        s1.read_photo_robust = fake_read
        first = s1.read_photo_cached(photo, "VW GOLF")
        again = s1.read_photo_cached(photo, "VW GOLF")
        check("first read pays", (len(reads), first["_cost"]), (1, 0.002))
        check("same photo reused at cost 0", (len(reads), again["_cost"], again["candidates"]), (1, 0, first["candidates"]))
        check("reuse logged with cost 0", json.loads(c.LEDGER.read_text().splitlines()[-1])["cost"], 0)
        s1.read_photo_cached(photo, "VW POLO")
        check("other vehicle reads again", len(reads), 2)
        s1.read_photo_cached(photo, "VW GOLF", model="other/model")
        check("other model reads again", len(reads), 3)
        prompt = s1.PROMPT
        s1.PROMPT = prompt + " "
        s1.read_photo_cached(photo, "VW GOLF")
        s1.PROMPT = prompt
        check("changed prompt reads again", len(reads), 4)
        photo.write_bytes(b"photo bytes B")
        s1.read_photo_cached(photo, "VW GOLF")
        check("changed photo reads again", len(reads), 5)
        blank = tmp / "002.jpg"
        blank.write_bytes(b"blank photo")
        s1.read_photo_cached(blank, "VW GOLF")
        s1.read_photo_cached(blank, "VW GOLF")
        check("no number found: read fresh every time", len(reads), 7)

        # c. one listing: no Jev call, and pick_listing gives the same answer whatever Jev would say
        calls = []
        c.jev = lambda *a, **k: calls.append(1)
        it = {"title": "VW GOLF ABS PUMP 1K0615601", "price": {"value": "34.50"}, "condition": "Used",
              "itemWebUrl": "https://www.ebay.co.uk/itm/1"}
        scored = s3.listing_match({"item_count": 1}, [it], "VW GOLF")
        check("one listing: no Jev call", calls, [])
        picks = [s3.pick_listing([(it, p)], "1K0615601", "VW GOLF") for p in (0.0, 0.1, 0.19, 0.2, 0.5, 1.0)]
        check("one listing: same pick whatever Jev scores", all(p == picks[0] for p in picks), True)
        check("one listing: skip gives that same pick", s3.pick_listing(scored, "1K0615601", "VW GOLF"), picks[0])

        # d. eBay cache files past their 24 hours are deleted; fresh ones and saved reads stay
        old, new = tmp / "ebay_old.json", tmp / "ebay_new.json"
        for f in (old, new):
            f.write_text("{}")
        os.utime(old, (time.time() - 25 * 3600,) * 2)
        check("prune: one old file", c.prune_ebay_cache(), 1)
        check("prune: fresh kept, old gone", (new.exists(), old.exists(), any(s1.READS.iterdir())), (True, False, True))
    finally:
        c.LEDGER, c.CACHE, s1.READS, s1.read_photo_robust, c.jev = saved
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
