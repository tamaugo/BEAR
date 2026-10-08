#!/usr/bin/env python3
"""Offline checks for part-name tidying and the finished line layout (no network, no cost).

The layout is the owner-approved Q269 sheet (2026-10-05, listed on eBay):
  HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL - Off Side Front Fog Light 922023Z010 | 24.99 | <url> | IMG_4969-OSF.JPEG

usage: python3 tests/test_names_offline.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bear2"))
import assemble as a  # noqa: E402

V = "HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL"
FOG_OSF = ["IMG_4969-OSF.JPEG", "922023Z010", "HYUNDAI I40 FRONT RIGHT FOG LIGHT 92202-3Z010",
           "24.99", "https://www.ebay.co.uk/itm/800068400352"]
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
    want = ["HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL - Off Side Front Fog Light 922023Z010 | 24.99 | "
            "https://www.ebay.co.uk/itm/800068400352 | IMG_4969-OSF.JPEG",
            "HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL - Front Fog Light 922013Z010 | 24.99 | "
            "https://www.ebay.co.uk/itm/167617751562 | IMG_4976.-NSFJPEG.JPEG"]
    for got, exp in zip(lines, want):
        if got != exp:
            bad += 1
            print(f"FAIL line\n  got  {got}\n  want {exp}")
    print("all passed" if not bad else f"{bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
