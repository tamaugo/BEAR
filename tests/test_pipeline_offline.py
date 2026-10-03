#!/usr/bin/env python3
"""Offline end-to-end run of the BEAR 0.2 pipeline (bear2/run.py) with eBay, OpenRouter and
Jev faked, so it is free and needs no keys. The fake listings use characters Windows' default
cp1252 text encoding cannot write (Š ✅ ↳), which is what broke runs on Windows before the
launcher started running the pipeline in UTF-8 mode.

The validator and make_xlsx.py run for real (as subprocesses, like a normal run).

usage: python tests/test_pipeline_offline.py      (bear.cmd sets PYTHONUTF8=1; on Windows set it too)
"""
import json, os, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bear2"))
import common as c  # noqa: E402
import image_hints, run  # noqa: E402

FAILURES = []
PN = "84260-3Z000"
TITLE = "Škoda Octavia ✅ Interior Light – " + PN + " Genuine"


def check(name, cond, detail=""):
    print(("PASS: " if cond else "FAIL: ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILURES.append(name)


def listing(i, price, title=TITLE):
    return {"itemId": f"v1|{1000 + i}|0", "legacyItemId": str(1000 + i), "title": title,
            "price": {"value": f"{price:.2f}", "currency": "GBP"}, "condition": "Used",
            "seller": {"username": f"seller{i}"}, "itemWebUrl": f"https://www.ebay.co.uk/itm/{1000 + i}?x=1",
            "image": {"imageUrl": f"https://i.ebayimg.com/{i}.jpg"}}


def fake_chat(model, messages, tag="", **kw):
    if tag.startswith("s1:"):
        if "IMG_0002" in tag:  # a photo with no readable number
            d = {"has_any_text": False, "part_description": "plastic trim", "item_count": 1, "candidates": []}
        else:
            d = {"has_any_text": True, "part_description": "interior light", "item_count": 1,
                 "candidates": [{"text": PN, "role": "primary", "legibility": "clear", "alt_readings": []}]}
        return json.dumps(d), {"usage": {"cost": 0}}
    if tag == "clean_names":
        return json.dumps({"names": {"i0": "Interior Light"}}), {"usage": {"cost": 0}}
    return "YES", {"usage": {"cost": 0}}


def fake_jev(state, questions, tag=""):
    answers = {}
    for k, q in questions.items():
        if q["type"] == "noul":
            answers[k] = {"type": "noul", "noul": 0.9}
        else:
            first = next(iter(q["criteria"]))
            answers[k] = {"type": "choice", "choice": first, "confidence": 0.9, "probabilities": {first: 0.9}}
    return {"answers": answers, "usage": {"cost": 0}}


def main():
    c.chat = fake_chat
    c.jev = fake_jev
    c.ebay_search_raw = lambda q, *a, **k: [listing(i, p) for i, p in enumerate((24.50, 24.99, 30.00, 24.95))]
    image_hints.search_by_image = lambda path, limit=50: [
        listing(50, 12.00, "Škoda dash trim ✅ panel"), listing(51, 15.50, "VW trim – panel")]
    with tempfile.TemporaryDirectory() as d:
        c.LEDGER = Path(d) / "spend.jsonl"
        photos = Path(d) / "Zoë's job photos"
        photos.mkdir()
        from PIL import Image
        for name in ("IMG_0001 OSF.jpg", "IMG_0002.jpg", "IMG_0003 NULL.jpg"):
            Image.new("RGB", (64, 48), (120, 120, 120)).save(photos / name)
        out = photos / "bear-results-test"
        sys.argv = ["run.py", str(photos), "SKODA OCTAVIA MK3 2015 1.6 TDI", str(out)]
        run.main()

        xlsx = out / "results.xlsx"
        check("results.xlsx built", xlsx.exists())
        a2 = (out / "agent2_results.md").read_text(encoding="utf-8")
        check("eBay title with Š ✅ – written intact", TITLE in a2, a2)
        sheet = out / "results_sheet.txt"
        check("possible-match rows (↳ £) added for the unpriced photo",
              sheet.exists() and "↳ POSSIBLE MATCH 1" in sheet.read_text(encoding="utf-8"))
        a3 = (out / "agent3_results.txt").read_text(encoding="utf-8")
        check("priced row has part number, x.99 price and clean URL",
              "Interior Light 842603Z000 | 24.99 | https://www.ebay.co.uk/itm/" in a3, a3)
        check("NULL photo listed", "NO PART NUMBER" in a3 and "IMG_0003 NULL.jpg" in a3, a3)
        if xlsx.exists():
            with zipfile.ZipFile(xlsx) as z:
                xml = " ".join(z.read(n).decode("utf-8") for n in z.namelist() if n.endswith(".xml"))
            check("spreadsheet holds the Š ✅ hint title and £ price", "Škoda dash trim ✅ panel" in xml and "listed £12.00" in xml)
    print(f"\n{len(FAILURES)} failed" if FAILURES else "\nall passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
