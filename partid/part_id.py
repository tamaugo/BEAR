#!/usr/bin/env python3
"""#part-id on one photo: Agent 1 (Gemini, partid/agent1.py) reads every possible part number and
reading, Jev (partid/jev.py) scores them most to least likely, and the top 3 by Jev's score are the
options the person picks from. The order is Jev's alone, never Gemini's (owner, 2026-10-29).

Prints one JSON object on stdout:
  {"seconds", "cost", "agent1": {model, seconds, cost, raw}, "readings": [...],
   "jev": {model, scores, cost, method, ...}, "options": [{"text", "score"}] (top 3, best first)}

usage: python3 partid/part_id.py <photo> [vehicle]
"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent1  # noqa: E402
import jev  # noqa: E402

HOW_MANY = 3


def run(path, vehicle=agent1.NO_CAR):
    started = time.time()
    read = agent1.read(path, vehicle)
    found = agent1.readings(read["raw"])
    scored = jev.score({**agent1.parse(read["raw"]), "car": vehicle}, found)
    ranked = sorted(zip(found, scored["scores"]), key=lambda x: -x[1])   # stable: a tie keeps Agent 1's order
    return {"seconds": round(time.time() - started, 1), "cost": read["cost"] + scored["cost"],
            "agent1": read, "readings": found, "jev": scored,
            "options": [{"text": r["text"], "score": round(s, 4)} for r, s in ranked[:HOW_MANY]]}


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__.split("usage: ")[1])
    print(json.dumps(run(Path(sys.argv[1]), *sys.argv[2:])))
