"""#part-id's scoring: Jev (typesafe/jev-1.13, OpenRouter's Decisions API) scores every reading Agent 1
gave, most to least likely to be the part's own part number. The owner's rule (2026-10-29): Jev does the
scoring, never Gemini. So Agent 1 only lists readings, and the order of the options is Jev's alone. If
Jev fails, the read fails: there is no fall back to Agent 1's order.

One Decisions "choice" call over all the readings: its probabilities are the scores. Jev sees text only
(what Agent 1 said about each reading and the part), not the photo, and no eBay listings.
"""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bear2"))
sys.path.insert(0, str(ROOT / "tools"))
import common as c  # noqa: E402
import jev_client as j  # noqa: E402

MODEL = c.JEV_MODEL

INSTRUCTIONS = (
    "A vision model read every possible part number off ONE photo of a used car part, taken head-on, "
    "including alternative readings where a character was uncertain (0/O/D/Q, 1/I/7/L, 2/Z, 5/S/6, 8/B/3, "
    "6/G/C, U/V/0). Which reading is the exact manufacturer (OEM) part number of the part in the photo, "
    "exactly as printed? Weigh how the vision model judged each reading (primary or secondary number, "
    "legibility, its notes), whether the reading fits real OEM numbering formats (e.g. Hyundai/Kia "
    "97420-3Z000, Peugeot/Citroen 96 386 698 80, Ford 3M51-9K546-AB, VW 3C0 015 404, BMW 63 21 7 160 779), "
    "and which of the look-alike characters is the more plausible in that format. Dates, supplier codes, "
    "sub-component numbers, ratings and fragments of a longer number are wrong.")


def state(read, readings):
    return {"car": read.get("car") or "not given",
            "part_in_photo": read.get("part_description"), "visual_features": read.get("visual_features"),
            "readings": {f"R{i}": {"reading": r["text"], "is_alternative_reading_of": r["alt_of"],
                                   "vision_role": r["role"], "legibility": r["legibility"], "vision_note": r["note"]}
                         for i, r in enumerate(readings, 1)}}


def score(read, readings):
    """{"model", "scores": [probability per reading, same order], "cost", "method"}. One reading: nothing
    to score, it is the only option (no call). BEAR_SIM: made-up scores, no call."""
    if len(readings) < 2:
        return {"model": MODEL, "scores": [1.0] * len(readings), "cost": 0,
                "method": "only one reading" if readings else "no readings"}
    if os.environ.get("BEAR_SIM"):
        raw = [1 / (i + 2) for i in range(len(readings))][::-1]   # reversed: the order is Jev's, not Agent 1's
        return {"model": MODEL, "scores": [x / sum(raw) for x in raw], "cost": 0, "method": "jev (dev mode)"}
    q = {"number": {"type": "choice", "instructions": INSTRUCTIONS,
                    "criteria": {f"R{i}": f"reading '{r['text']}'" for i, r in enumerate(readings, 1)}}}
    r = c.jev(state(read, readings), q, tag="partid:score")
    probs = j.get_probabilities(r, "number") or {}
    if not probs:
        raise RuntimeError(f"Jev gave no scores: {j.get_answer(r, 'number')}")
    return {"model": MODEL, "scores": [float(probs.get(f"R{i}") or 0) for i in range(1, len(readings) + 1)],
            "cost": j.get_cost(r), "method": "jev", "answer": j.get_answer(r, "number")}
