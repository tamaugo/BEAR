#!/usr/bin/env python3
"""Offline checks for part-name tidying and the finished line layout (no network, no cost).

The layout is the owner-approved Q269 sheet (2026-10-05, listed on eBay):
  HYUNDAI 140 MK1 SEDAN 2015 1.7 DIESEL - Front Fog Light 922023Z010 | 24.99 | <url> | IMG_4969-OSF.JPEG
with the eBay category ID added after the price (2026-11-08):
  ... 922023Z010 | 24.99 | 33709 | <url> | IMG_4969-OSF.JPEG

The NSF/NSR/OSF/OSR location words were removed from the server code (the bot names photos
001.jpg ...), so the finished line carries the tidied name as-is and the filename is passed
through untouched, even when it contains a location word.

Also bear2/run.py's handling of photos that can't be read: one bad photo becomes a FAILED row and
the rest of the folder carries on (pipeline_checks, all faked: no network).

usage: python3 tests/test_names_offline.py
"""
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="bear-names-test-"))
os.environ["BEAR_SPEND_LEDGER"] = str(TMP / "spend.jsonl")   # never the real ledger
sys.path.insert(0, str(ROOT / "bear2"))
sys.path.insert(0, str(ROOT / "tools"))
import assemble as a  # noqa: E402
import run as R  # noqa: E402
from agent3_validator import run_validator  # noqa: E402

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
    bad += pipeline_checks()
    bad += batch_checks()
    bad += spend_checks()
    print("all passed" if not bad else f"{bad} failed")
    return 1 if bad else 0


def pipeline_checks():
    """run.py: a photo that can't be read is its own FAILED row; outages still stop the run."""
    from PIL import Image
    fails = []

    def check(what, got, want):
        if got != want:
            fails.append(what)
            print(f"FAIL {what}: got {got!r}, want {want!r}")

    photos = TMP / "photos"
    photos.mkdir()
    for n, colour in (("001.jpg", "white"), ("002.jpg", "red"), ("004.jpg", "blue")):   # different photos:
        Image.new("RGB", (32, 32), colour).save(photos / n, "JPEG")   # identical ones would share a saved read
    (photos / "003.jpg").write_bytes(b"not a photo at all")   # corrupt upload
    ps = sorted(photos.iterdir())

    def read(p):
        if p.name == "002.jpg":
            raise RuntimeError("OpenRouter HTTP 503: upstream down")   # failed after its retries, twice
        if p.name == "003.jpg":
            Image.open(p)   # what the real read does first: raises on a corrupt file
        return {"candidates": [{"text": f"PN{p.stem}", "role": "primary"}]}
    reads, unread = R.read_all(ps, read)
    check("good photos read", sorted(k for k, v in reads.items() if v), ["001.jpg", "004.jpg"])
    check("model failure row", unread["002.jpg"][0], R.FAIL_READ)
    check("corrupt photo row", unread["003.jpg"][0], R.FAIL_PHOTO)
    check("reason kept", "HTTP 503" in unread["002.jpg"][1], True)
    check("failed reads left out of stage1", sorted(reads), ["001.jpg", "004.jpg"])

    # A busy spell: the photo's first read fails, the retry at the end works.
    tries = []

    def busy(p):
        tries.append(p.name)
        if p.name == "001.jpg" and tries.count("001.jpg") == 1:
            raise RuntimeError("OpenRouter HTTP 429: busy")
        return {"candidates": [{"text": "X1234567", "role": "primary"}]}
    reads, unread = R.read_all([ps[0], ps[3]], busy)
    check("busy photo read on its second try", (sorted(reads), unread, tries.count("001.jpg")), (["001.jpg", "004.jpg"], {}, 2))

    # A folder of one corrupt photo is a FAILED row, not a stopped run.
    reads, unread = R.read_all([ps[2]], read)
    check("one corrupt photo alone", unread["003.jpg"][0], R.FAIL_PHOTO)

    for msg in ("spend cap reached: $1.0000 this run (cap $1.00)", "OpenRouter HTTP 402: no credit",
                "OpenRouter HTTP 401: bad key"):
        def stop(p, msg=msg):
            if p.name == "004.jpg":
                raise RuntimeError(msg)
            return {"candidates": []}
        try:
            R.read_all(ps, stop)
            check(f"stops the run: {msg[:25]}", "carried on", "raised")
        except RuntimeError as e:
            check(f"stops the run: {msg[:25]}", str(e), msg)   # same text the bot's K01/K02 look for
    try:
        R.read_all(ps, lambda p: (_ for _ in ()).throw(TimeoutError("timed out")))
        check("every photo failing stops the run", "carried on", "raised")
    except TimeoutError:
        pass

    # The whole of run.py main(): the folder finishes with every row, bad photos as FAILED rows.
    out = TMP / "results"
    saved = R.s1m.read_photo_robust, R.process, R.finish, sys.argv, R.s1m.READS
    R.s1m.READS = TMP / "reads"   # never the real saved reads
    R.s1m.read_photo_robust = lambda p, vehicle, model=None: read(p)
    R.process = lambda name, s1, *rest: (f"{name} | {s1['candidates'][0]['text']} | Title | 1 | 19.99 | https://e/x", {})
    R.finish = lambda *args, **kw: None
    sys.argv = ["run.py", str(photos), V, str(out)]
    try:
        R.main()
    finally:
        R.s1m.read_photo_robust, R.process, R.finish, sys.argv, R.s1m.READS = saved
    rows = (out / "agent2_results.md").read_text().splitlines()
    check("every photo has a row, in order", [r.split(" | ")[0] for r in rows], ["001.jpg", "002.jpg", "003.jpg", "004.jpg"])
    check("rows", rows[1:3], ["002.jpg | " + R.FAIL_READ, "003.jpg | " + R.FAIL_PHOTO])
    check("trace says why", "HTTP 503" in json.loads((out / "trace.json").read_text())["002.jpg"]["error"], True)

    # The validator accepts the new FAILED rows as they come out of assemble.py
    a3, a2 = TMP / "a3.txt", TMP / "a2.md"
    a3.write_text("FAILED - Agent 1 - Photo Read Unavailable | | | | 002.jpg\n"
                  "FAILED - Agent 1 - Photo Could Not Be Opened | | | | 003.jpg\n")
    a2.write_text("002.jpg | " + R.FAIL_READ + "\n003.jpg | " + R.FAIL_PHOTO + "\n")
    report, marked = run_validator(str(a3), str(a2))
    check("validator: new FAILED rows are fine", marked, False)
    return len(fails)


def batch_checks():
    """clean_names sends NAME_BATCH rows per call, so a big folder can't be cut off at max_tokens."""
    import json, re
    calls, bad = [], 0
    real = a.c.chat

    def fake_chat(model, messages, **kw):
        items = json.loads(re.search(r"Items:\n(\{.*\})", messages[1]["content"], re.S).group(1))
        calls.append(len(items))
        if kw.get("tag") == "clean_names" and "i55" in items:
            names = {k: "Relay" for k in items if k != "i55"}   # one name missing in the last batch
            return json.dumps({"names": names}), {}
        return json.dumps({"names": {k: "Fog Light" for k in items}}), {}
    a.c.chat = fake_chat
    try:
        rows = {f"i{k}": FOG_OSF for k in range(55)}
        got = a.clean_names(rows)
        for what, ok in [("55 rows -> 3 calls of 25, 25, 5", calls == [25, 25, 5]),
                         ("every row named", got == {k: "Fog Light" for k in rows})]:
            if not ok:
                bad += 1
                print(f"FAIL batch: {what} (calls {calls})")
        try:
            a.clean_names({**rows, "i55": FOG_OSF})
            bad += 1
            print("FAIL batch: a name missing from one batch must stop the run")
        except a.NamesFailed:
            pass
    finally:
        a.c.chat = real
    return bad


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
