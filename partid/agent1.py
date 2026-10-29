#!/usr/bin/env python3
"""#part-id's own Agent 1, a framework for now: reads one part-number photo and prints what the
model sent back, raw.

A separate copy of Agent 1 (bear2/stage1_read.py on 2026-10-29: same model and prompt), kept
apart on purpose while the new pipeline is decided (owner, 2026-10-29). Change this file freely:
/run never uses it, and changes to bear2/stage1_read.py never reach it. Only the plumbing
(OpenRouter call, photo resize, spend ledger) is shared, from bear2/common.py, unchanged.
Left out: Agent 1's second try on broken JSON, and its rotated re-reads (photos are always
head-on shots, owner 2026-10-29).

options() turns the read into up to 3 part numbers, most likely first, for the #part-id buttons.

Prints one JSON object on stdout: {"model", "seconds", "cost", "raw", "options"}. BEAR_SIM set
(dev mode): a made-up read, no call, no credit.

usage: python3 partid/agent1.py <photo> [vehicle]
"""
import json, os, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bear2"))
import common as c  # noqa: E402

MODEL = "google/gemini-3.1-flash-lite"
NO_CAR = "not given"

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

SIM_RAW = json.dumps({"has_any_text": True, "part_description": "(dev mode) made-up read", "item_count": 1,
                      "candidates": [{"text": "97420-3Z000", "role": "primary", "legibility": "clear",
                                      "alt_readings": ["97420-3Z0O0"], "note": "(dev mode)"},
                                     {"text": "39R293-1200", "role": "secondary", "legibility": "partly clear",
                                      "alt_readings": [], "note": "(dev mode)"}]})
ROLE = {"primary": 0, "unclear": 1, "secondary": 2}
LEGIBLE = {"clear": 0, "partly clear": 1, "poor": 2}
HOW_MANY = 3


def options(raw):
    """Up to 3 part numbers from Agent 1's read, most likely first: the candidates ranked by role
    (primary, unclear, secondary) then legibility, each followed by its other readings; the same
    number twice (ignoring spaces and dashes) only once. [] if there is none or the JSON is broken."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        return []
    cands = [x for x in (d.get("candidates") if isinstance(d, dict) else None) or [] if isinstance(x, dict)]
    cands.sort(key=lambda x: (ROLE.get(x.get("role"), 1), LEGIBLE.get(x.get("legibility"), 3)))
    out, seen = [], set()
    for x in cands:
        for text in [x.get("text"), *(x.get("alt_readings") or [])]:
            text = text.strip() if isinstance(text, str) else ""
            if c.norm(text) and c.norm(text) not in seen:
                seen.add(c.norm(text))
                out.append(text)
    return out[:HOW_MANY]


def read(path, vehicle=NO_CAR):
    """One read of the photo: {"model", "seconds", "cost", "raw", "options"}, raw = the model's text as sent."""
    started = time.time()
    if os.environ.get("BEAR_SIM"):
        raw, cost = SIM_RAW, 0
    else:
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(vehicle=vehicle)},
            {"type": "image_url", "image_url": {"url": c.img_data_uri(path, 1600)}}]}]
        raw, d = c.chat(MODEL, msgs, max_tokens=1200, response_format={"type": "json_object"},
                        tag=f"partid:{Path(path).name}")
        cost = (d.get("usage") or {}).get("cost") or 0
    return {"model": MODEL, "seconds": round(time.time() - started, 1), "cost": cost, "raw": raw,
            "options": options(raw)}


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__.split("usage: ")[1])
    print(json.dumps(read(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) == 3 else NO_CAR)))
