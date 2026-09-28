#!/usr/bin/env python3
"""
Live end-to-end experiment for QUESTION_SET_AGENT2.

Sends one real Decisions API call with a synthetic-but-realistic set of eBay
candidates for a Mazda relay block, and checks that Jev's picks look sane:
it should recognize a genuine match exists, and should prefer a used-condition
listing over the much pricier new/main-dealer one. A failed assertion here is
an experimental finding about Jev's behavior, not a bug in this script.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from jev_client import JevAuthError, JevPaymentError, call_decisions, get_cost  # noqa: E402
from jev_questions import QUESTION_SET_AGENT2  # noqa: E402

PART_NUMBER = "GS1D-66-750A"
MODEL = "typesafe/jev-1.13"

CANDIDATES = {
    "L1": '- "Fuse Box Relay ECU Module" | 12.95 GBP | Used | seller: breaker_parts_uk',
    "L2": (
        '- "Genuine Mazda Block Relay - Part No. GS1D-66-750A" | 181.49 GBP | New '
        "| seller: mazda_main_dealer"
    ),
    "L3": '- "Mazda 6 relay block GS1D66750A used" | 12.95 GBP | Used | seller: strip_car_parts',
    "L4": (
        '- "MAZDA 6 2008-2013 RELAY FUSE BOX GS1D-66-750A" | 14.99 GBP | Used\' '
        "| seller: used_car_spares"
    ),
    "L5": (
        '- "Relay Unit Mazda GS1D-66-750A" | 9.95 GBP | For parts or not working '
        "| seller: breaker_yard"
    ),
    "L6": (
        '- "GS1D-66-750A Genuine Mazda Relay NEW" | 89.99 GBP | New other '
        "| seller: oem_parts_direct"
    ),
}

USED_CONDITION_KEYS = {"L1", "L3", "L4", "L5"}


def main() -> int:
    state = {
        "part_number": PART_NUMBER,
        "make": "Mazda",
        "candidates": CANDIDATES,
    }
    questions = QUESTION_SET_AGENT2(CANDIDATES, part_number=PART_NUMBER)

    try:
        response = call_decisions(MODEL, state, questions)
    except (JevAuthError, JevPaymentError) as e:
        print(str(e))
        return 1

    answers = response.get("answers", {})
    for key, answer in answers.items():
        print(f"answer[{key}]: {answer}")
    print(f"usage.cost: {get_cost(response)}")

    genuine_match = answers.get("has_genuine_match", {}).get("noul")
    best_choice = answers.get("best_listing", {}).get("choice")

    used_ok = best_choice in USED_CONDITION_KEYS
    print(f"{'PASS' if used_ok else 'FAIL'}: best_listing chose a used-condition "
          f"candidate (got {best_choice!r})")

    genuine_ok = genuine_match is not None and genuine_match >= 0.60
    print(f"{'PASS' if genuine_ok else 'FAIL'}: has_genuine_match.noul >= 0.60 "
          f"(got {genuine_match!r})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
