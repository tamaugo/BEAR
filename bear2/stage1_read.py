"""Stage 1 — vision read. One call per photo. Generous extraction: every plausible
reading of every candidate number (incl. rotated/upside-down text and confusable
characters), plus a plain description of the physical part so later stages can
match listings against what is actually in the photo.

Output per photo (JSON): {has_any_text, part_description, item_count, candidates:[
  {text, role, legibility, alt_readings:[...], note}]}
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

MODEL = "google/gemini-3.1-flash-lite"

PROMPT = """You are reading a photo of ONE used car part taken at a breaker's yard. Car: {vehicle}.

Your job is PERCEPTION ONLY. Report what is physically printed/moulded/stamped on the part, and what the part is. A later stage verifies numbers against live eBay listings, so:
- Report EVERY candidate string that could be the manufacturer's part number (OEM number, supplier number like 39R293-1200, lamp codes like LP 1061 KFA04). Include numbers on labels, stickers, moulded plastic, stamped metal.
- Text may be rotated 90°, upside-down (180°) or mirrored. Mentally rotate the image and read it in every orientation. If a string reads plausibly in more than one orientation, report each reading.
- Read character by character. Where a character is uncertain between look-alikes (0/O/D/Q, 1/I/7/L, 2/Z, 5/S/6, 8/B/3, 6/G/C, U/V/0), give your best reading as `text` and list the other plausible full readings in `alt_readings`.
- Do NOT invent characters you cannot see. If part of a number is hidden or cut off, still report the visible part and say so in `note`.
- IGNORE: dates, date wheels, barcodes digits, voltages/ratings, E-marks/DOT/regulatory codes, recycling/material codes (>PP<, PA66), country of origin, brand names.
- `role`: "primary" = most likely the part's own OEM number; "secondary" = another number on the part (sub-component, supplier, revision); "unclear".
- OEM numbering differs by make, e.g. Hyundai/Kia 97420-3Z000 (5+5, may carry a 2-char suffix like RY), Peugeot/Citroen 96 386 698 80 (10 digits ending 80), Ford 3M51-9K546-AB (prefix-base-suffix), VW 3C0 015 404, BMW 63 21 7 160 779. Report the number exactly as printed, suffix included; do not remove anything.
- Stamped/etched/cast metal: read slowly, report every plausible reading of each unclear character in alt_readings.

Also describe the part itself as a UK car-breaker eBay seller would name it (e.g. "rear interior courtesy roof dome light", "accelerator throttle pedal", "airbag crash impact sensor"). Say how many separate items are in the photo (e.g. 2 sensors = item_count 2).

Return ONLY this JSON, no prose:
{{"has_any_text": true/false,
 "part_description": "...",
 "item_count": 1,
 "visual_features": "short: shape, colour, connectors, anything distinctive",
 "candidates": [{{"text": "...", "role": "primary|secondary|unclear", "legibility": "clear|partly clear|poor", "alt_readings": ["..."], "note": "orientation / where on part / anything cut off"}}]}}
If there is no number at all, candidates = [].
"""


def parse_json(s):
    s = s.strip()
    m = re.search(r"\{.*\}", s, re.S)
    return json.loads(m.group(0)) if m else None


def read_photo(path, vehicle, model=MODEL, max_side=1600, rotate=0):
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT.format(vehicle=vehicle)},
        {"type": "image_url", "image_url": {"url": c.img_data_uri(path, max_side, rotate)}}]}]
    cost = 0
    for attempt in range(2):
        out, raw = c.chat(model, msgs, max_tokens=1200, response_format={"type": "json_object"},
                          temperature=0 if attempt == 0 else 0.3, tag=f"s1:{Path(path).name}")
        cost += (raw.get("usage") or {}).get("cost") or 0
        try:
            d = parse_json(out) or {}
            break
        except Exception:
            # Measured r9: flash-lite sometimes repeats its candidate list until max_tokens,
            # truncating the JSON. The readings are still there - salvage them, then retry.
            d = salvage(out)
    d["candidates"] = dedupe(d.get("candidates") or [])
    d["_cost"] = cost
    return d


def dedupe(cands):
    seen, out = set(), []
    for x in cands:
        k = c.norm(x.get("text") or "")
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def salvage(text):
    """Recover candidate objects from truncated JSON output."""
    cands = []
    for m in re.finditer(r'"text"\s*:\s*"([^"]+)"\s*,\s*"role"\s*:\s*"(\w+)"', text):
        cands.append({"text": m.group(1), "role": m.group(2), "legibility": "unknown",
                      "alt_readings": [], "note": "salvaged from truncated output"})
    desc = re.search(r'"part_description"\s*:\s*"([^"]*)"', text)
    cnt = re.search(r'"item_count"\s*:\s*(\d+)', text)
    return {"candidates": cands, "part_description": desc.group(1) if desc else None,
            "item_count": int(cnt.group(1)) if cnt else 1, "_salvaged": True}


def read_photo_robust(path, vehicle, model=MODEL):
    """First pass upright. If it finds no candidate number, re-read the photo rotated
    90/180/270 degrees and merge. Measured: flash-lite returned [] for a 90-degree-rotated
    wiring-loom label (r4rot, IMG_4866) that it reads fine upright. A no-number part
    (fuel cap) costs 3 extra cheap calls, ~$0.002."""
    d = read_photo(path, vehicle, model)
    if d.get("candidates"):
        return d
    extra, cost = [], d.get("_cost") or 0
    for rot in (90, 180, 270):
        r = read_photo(path, vehicle, model, rotate=rot)
        cost += r.get("_cost") or 0
        for cand in r.get("candidates") or []:
            cand["note"] = f"(read after rotating {rot}deg) " + (cand.get("note") or "")
            extra.append(cand)
        if not d.get("part_description") and r.get("part_description"):
            d["part_description"] = r["part_description"]
    d["candidates"], d["_cost"], d["_rotation_retry"] = extra, cost, True
    return d


if __name__ == "__main__":
    import concurrent.futures as cf
    folder, vehicle = Path(sys.argv[1]), sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else MODEL
    out = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("stage1.json")
    photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    with cf.ThreadPoolExecutor(6) as ex:
        res = dict(zip([p.name for p in photos], ex.map(lambda p: read_photo(p, vehicle, model), photos)))
    out.write_text(json.dumps(res, indent=1))
    print("wrote", out, "spend so far $%.4f" % c.total_spend())
