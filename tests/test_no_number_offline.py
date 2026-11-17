#!/usr/bin/env python3
"""Offline checks for stage 4, parts with no part number (bear2/stage4_no_number.py). No network, no cost:
eBay, Jev and the photo search are faked.

Owner's rules (2026-11-17): a part with no number is priced from eBay listings of the same kind of part
for the channel's car; which side or position the listing is for does not matter ("a door handle is a
door handle"); the side the yard wrote on the part goes first in the name ("Near Side Front Door Handle");
the listing the price came from is the link; not sure = the FAILED row stays, as before.

usage: python3 tests/test_no_number_offline.py
"""
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="bear-nonum-test-"))
os.environ["BEAR_SPEND_LEDGER"] = str(TMP / "spend.jsonl")   # never the real ledger
sys.path.insert(0, str(ROOT / "bear2"))
sys.path.insert(0, str(ROOT / "tools"))
import common as c  # noqa: E402
import stage4_no_number as s4  # noqa: E402
import run as R  # noqa: E402
import assemble as a  # noqa: E402
import jev_client  # noqa: E402
from agent3_validator import run_validator  # noqa: E402

V = "MAZDA 6 MK2 2008 SEDAN 2.5 PETROL"
FAILS = []


def check(what, got, want):
    if got != want:
        FAILS.append(f"{what}: got {got!r}, want {want!r}")


def item(n, title, price, used=True):
    return {"itemId": f"v1|{n}|0", "legacyItemId": str(n), "title": title, "price": {"value": str(price)},
            "condition": "Used" if used else "New", "itemWebUrl": f"https://www.ebay.co.uk/itm/{n}?x=1",
            "leafCategoryIds": ["33716"]}


LISTINGS = [item(1, "MAZDA 6 GH 2008 FRONT LEFT EXTERIOR DOOR HANDLE", 24.0),
            item(2, "Mazda 6 2010 rear right outer door handle", 24.5),
            item(3, "MAZDA 6 MK2 DOOR HANDLE OSF BLACK", 23.9),
            item(4, "MAZDA 6 PAIR OF FRONT DOOR HANDLES", 45.0),        # a pair: Jev says no
            item(5, "MAZDA 6 FRONT DOOR LOCK ACTUATOR", 35.0),          # a different part: Jev says no
            item(6, "Mazda 6 exterior door handle 2009", 12.0)]


def fake_jev(state, qs, tag="", assets=None):
    """Listing check: yes for a single door handle. Best title: the first one."""
    fake_jev.calls.append((tag, assets is not None))
    if "title" in qs:
        return {"answers": {"title": {"type": "choice", "choice": "T1", "confidence": 0.9}}}
    ans = {}
    for k in qs:
        t = state["listings"][k].upper()
        ans[k] = {"type": "noul", "noul": 0.9 if "HANDLE" in t and "PAIR" not in t and "HANDLES" not in t else 0.05}
    return {"answers": ans}


fake_jev.calls = []


def fake_search(q, limit=200, **k):
    fake_search.queries.append(q)
    return LISTINGS if "door handle" in q.lower() else []


fake_search.queries = []


def unit_checks():
    check("marker only is no number", s4.has_real_number({"candidates": [{"text": "NF"}, {"text": "2"}]}), False)
    check("short code is no number", s4.has_real_number({"candidates": [{"text": "FC 502"}, {"text": "GS1D"}]}), False)
    check("a part number is a number", s4.has_real_number({"candidates": [{"text": "x", "alt_readings": ["9643695780"]}]}), True)
    check("side NF", s4.side_marker({"candidates": [{"text": "NF"}]}), "NSF")
    check("side OR", s4.side_marker({"candidates": [{"text": "O R"}]}), "OSR")
    check("side NS", s4.side_marker({"candidates": [{"text": "NS"}, {"text": "NF"}]}), "NS")
    check("no side", s4.side_marker({"candidates": [{"text": "GS1D"}]}), None)
    check("car", s4.car_words("MAZDA CX-5 MK1 2014 2.2 DIESEL"), "MAZDA CX-5")
    check("car slash", s4.car_words("MITSUBISHI SHOGUN/PAJERO GLS 1998 2.8 DIESEL"), "MITSUBISHI SHOGUN")
    check("car two-word make", s4.car_words("LAND ROVER DISCOVERY 3 2006"), "LAND ROVER DISCOVERY")
    check("car unknown", s4.car_words("UNKNOWN VEHICLE"), None)
    check("queries", s4.part_queries("exterior door handle assembly with lock mechanism"),
          ["exterior door handle", "door handle", "exterior door"])
    check("queries try the start too", s4.part_queries("crankshaft pulley harmonic balancer")[-1], "crankshaft pulley")
    check("queries drop car words", s4.part_queries("Mazda CX-5 MK1 climate control panel unit", "MAZDA CX-5"),
          ["climate control panel", "control panel", "climate control"])
    check("queries alternatives", s4.part_queries("fuel injector leak off return pipe / fuel rail feed pipe")[0],
          "fuel injector leak off return")
    check("name, side first", a.no_number_name("Rear Door Handle", "NSF"), "Near Side Front Door Handle")
    check("name, no side", a.no_number_name("Towing Eye", None), "Towing Eye")
    check("name, only position words", a.no_number_name("Front", "OS"), "Off Side Front")


def pipeline_checks():
    from PIL import Image
    photo = TMP / "001.jpg"
    Image.new("RGB", (64, 64), (40, 40, 40)).save(photo)
    s1 = {"candidates": [{"text": "NF", "role": "unclear", "legibility": "clear", "alt_readings": []}],
          "part_description": "exterior door handle assembly with lock mechanism", "item_count": 1}
    saved = (c.ebay_search_raw, c.jev, R.image_hints.corroborate, os.environ.get("BEAR_NO_NUMBER"))
    c.ebay_search_raw, c.jev = fake_search, fake_jev
    R.image_hints.corroborate = lambda *a, **k: ("none", None)
    try:
        # off (the default): exactly today's FAILED row, no stage 4 search
        os.environ.pop("BEAR_NO_NUMBER", None)
        line, tr = R.process("001.jpg", s1, V, "MAZDA", photo)
        check("off: FAILED as before", line, f"001.jpg | {R.FAIL1}")
        check("off: no stage 4 search", [q for q in fake_search.queries if "door handle" in q.lower()], [])

        os.environ["BEAR_NO_NUMBER"] = "on"
        line, tr = R.process("001.jpg", s1, V, "MAZDA", photo)
        f = [x.strip() for x in line.split("|")]
        check("priced: blank number", f[1], "")
        # kept: 24.00, 24.50, 23.90, 12.00 (used) -> most common x.99 = 23.99/24.99 tie... see consensus
        check("priced: BEAR's price rule", f[4], f"{s4.s3.sell_price(s4.s3.consensus_price([24.0, 24.5, 23.9, 12.0])):.2f}")
        check("priced: link is a kept listing", f[5] in {"https://www.ebay.co.uk/itm/1", "https://www.ebay.co.uk/itm/2",
                                                     "https://www.ebay.co.uk/itm/3", "https://www.ebay.co.uk/itm/6"}, True)
        check("priced: side from the yard marker", tr["no_number"]["side"], "NSF")
        check("priced: search is car + part", fake_search.queries[-1], "MAZDA 6 exterior door handle")
        check("priced: pair and other part vetoed", tr["no_number"]["kept"], 4)
        check("Jev was shown the photo", ("no_number_kind", True) in fake_jev.calls, True)

        # not sure: too few listings of this kind -> FAILED row kept
        LISTINGS[:] = LISTINGS[3:5] + LISTINGS[:1]
        line, tr = R.process("001.jpg", s1, V, "MAZDA", photo)
        check("not sure: FAILED kept", line, f"001.jpg | {R.FAIL1}")
        check("not sure: reason saved", "not_sure" in tr["no_number"], True)

        # a real number was read but not found: stage 4 never prices it (a number decides the price)
        before = len(fake_search.queries)
        s1n = dict(s1, candidates=[{"text": "GS1D-58-410", "role": "primary", "legibility": "poor", "alt_readings": []}])
        line, tr = R.process("001.jpg", s1n, V, "MAZDA", photo)
        check("real number: FAILED as before", line.endswith(R.FAIL1) or line.endswith(R.FAIL_NF), True)
        check("real number: no stage 4", "no_number" in tr, False)

        # eBay failing in stage 4 keeps the FAILED row; a spend stop still stops the run
        c.ebay_search_raw = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("eBay 503"))
        line, tr = R.process("001.jpg", s1, V, "MAZDA", photo)
        check("stage 4 error: FAILED kept", line, f"001.jpg | {R.FAIL1}")
        c.ebay_search_raw = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("OpenRouter HTTP 402 (Jev): no credit"))
        try:
            R.process("001.jpg", s1, V, "MAZDA", photo)
            FAILS.append("a spend stop in stage 4 did not stop the run")
        except RuntimeError:
            pass
    finally:
        c.ebay_search_raw, c.jev, R.image_hints.corroborate = saved[:3]
        if saved[3] is None:
            os.environ.pop("BEAR_NO_NUMBER", None)
        else:
            os.environ["BEAR_NO_NUMBER"] = saved[3]


def sheet_checks():
    """The finished line of a no-number part, through assemble and the final check."""
    run = TMP / "run"
    run.mkdir()
    a2 = ["001.jpg | 9657144580 | FORD INJECTOR 9657144580 | 33553 | 44.99 | https://www.ebay.co.uk/itm/10",
          "002.jpg |  | MAZDA 6 FRONT LEFT EXTERIOR DOOR HANDLE | 33716 | 24.99 | https://www.ebay.co.uk/itm/1",
          f"003.jpg | {R.FAIL1}"]
    (run / "agent2_results.md").write_text("\n".join(a2) + "\n")
    (run / "trace.json").write_text(json.dumps({"002.jpg": {"no_number": {"side": "NSF"}}, "001.jpg": {}}))
    check("sides from trace", a.no_number_sides(run), {"002.jpg": "NSF"})
    f = a.parse_row(a2[1])
    line = a.part_line(V, f, a.no_number_name("Exterior Door Handle", "NSF"))
    check("finished line", line, f"{V} - Near Side Front Exterior Door Handle | 24.99 | 33716 | "
                                 "https://www.ebay.co.uk/itm/1 | 002.jpg")
    out = [a.part_line(V, a.parse_row(a2[0]), "Fuel Injector"), line, f"FAILED - Agent 1 - Could Not Produce Clear Part Number | | | | 003.jpg"]
    (run / "agent3_results.txt").write_text("\n".join(out) + "\n")
    report, marked = run_validator(str(run / "agent3_results.txt"), str(run / "agent2_results.md"))
    check("final check passes a no-number row", marked, False)
    # and a number appearing on a no-number row is still caught
    (run / "agent3_results.txt").write_text(line.replace("Handle |", "Handle GS1D58410 |") + "\n")
    report, marked = run_validator(str(run / "agent3_results.txt"), str(run / "agent2_results.md"))
    check("final check catches an invented number", marked, True)


def jev_assets_check():
    """The photo goes to the Decisions API as an asset, and a call without one is unchanged."""
    sent = []

    class Resp:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"answers": {}, "usage": {"cost": 0}}'
    was = jev_client.urllib.request.urlopen
    jev_client.urllib.request.urlopen = lambda req, timeout=0: sent.append(json.loads(req.data)) or Resp(req.data)
    try:
        jev_client.call_decisions("m", {"p": "@x"}, {}, api_key="k", assets={"@x": {"type": "image"}})
        jev_client.call_decisions("m", {"p": 1}, {}, api_key="k")
    finally:
        jev_client.urllib.request.urlopen = was
    check("assets sent", sent[0].get("assets"), {"@x": {"type": "image"}})
    check("no assets: body unchanged", sorted(sent[1]), ["model", "questions", "state"])


if __name__ == "__main__":
    unit_checks()
    pipeline_checks()
    sheet_checks()
    jev_assets_check()
    if FAILS:
        print("\n".join(FAILS))
        sys.exit(f"no-number checks: {len(FAILS)} failed")
    print("no-number checks: all passed")
