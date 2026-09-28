#!/usr/bin/env python3
"""
Jev question-set builders for the three BEAR pipeline stages.

Each builder returns a *fresh* dict on every call -- these get merged into a
Decisions request body and callers may still be tweaking the result (e.g. adding
a question) before sending it, so a shared module-level dict that later calls
mutate in place would leak state between unrelated pipeline runs.

Schema notes (see tools/jev_client.py for how these were confirmed against
OpenRouter's OpenAPI spec):
  - 'choice' criteria is a dict: option-key -> guidance string. The key you choose
    IS the value that comes back in the answer's "choice" field.
  - 'score' criteria is an ORDERED LIST of strings, one per scale rung, low to high.
    The API returns a float "score" that is an index into that list (0-based) plus
    a "legend" mapping each index back to its criteria text -- it is not literally
    the 1-10 number a human would write down, so round(score) indexes into the
    10-item scale built here rather than being read as "score out of 10" directly.
  - 'noul' criteria is exactly {"true": ..., "false": ...}.
"""

MAX_CHOICE_OPTIONS = 255  # documented cap on OpenRouter Decisions 'choice' criteria


def _as_criteria_dict(candidates) -> dict:
    """Accept either a list of candidate strings or an already-keyed dict of
    candidate -> guidance text, and normalize to the dict shape 'choice' needs."""
    if isinstance(candidates, dict):
        criteria = dict(candidates)
    else:
        criteria = {str(c): "" for c in candidates}
    if len(criteria) > MAX_CHOICE_OPTIONS:
        raise ValueError(
            f"{len(criteria)} candidates exceeds the Decisions API's "
            f"{MAX_CHOICE_OPTIONS}-option cap for 'choice' questions.")
    return criteria


def _match_quality_scale() -> list:
    """Fresh 10-rung scale, worst to best, for 'how well does X match Y' questions."""
    return [
        "No relation to the part or description at all",
        "Same broad category, wrong part entirely",
        "Same part family, clearly wrong variant/spec",
        "Plausible but missing key identifying details",
        "Partial match: some identifiers align, others conflict",
        "Likely match: most identifiers align, one is ambiguous",
        "Strong match: all stated identifiers align",
        "Very strong match: identifiers align and listing text confirms fit",
        "Near-exact match: only cosmetic wording differs",
        "Exact match: title and description confirm the part number precisely",
    ]


def _confidence_scale() -> list:
    """Fresh 10-rung scale, low to high confidence."""
    return [
        "Not confident at all",
        "Very low confidence",
        "Low confidence",
        "Somewhat low confidence",
        "Moderate confidence, leaning uncertain",
        "Moderate confidence, leaning confident",
        "Fairly confident",
        "Confident",
        "Very confident",
        "Certain",
    ]


def QUESTION_SET_AGENT1(candidates, make: str = "the stated") -> dict:
    """Agent 1: pick the genuine OEM part number out of several OCR/text candidates.

    candidates: list of candidate strings, or dict of candidate -> guidance text.
    make: vehicle make, dropped into the instructions text for context.
    """
    return {
        "genuine_part_number": {
            "type": "choice",
            "instructions": (
                f"Which of these candidate strings is the genuine OEM part number "
                f"for a {make} part?"
            ),
            "criteria": _as_criteria_dict(candidates),
        },
        "is_valid_oem_format": {
            "type": "noul",
            "instructions": (
                "is this candidate string formatted like a real OEM part number "
                "for the stated make?"
            ),
            "criteria": {
                "true": f"The string matches the format {make} OEM part numbers use.",
                "false": (
                    f"The string does not look like a real {make} OEM part number "
                    "(wrong length, wrong character set, looks like a SKU/barcode, etc)."
                ),
            },
        },
    }


def QUESTION_SET_AGENT2(listings, part_number: str = "the target part number") -> dict:
    """Agent 2: pick the best eBay listing for a known part number and score title match.

    listings: list of listing strings, or dict of listing-id -> title/description text.
    part_number: the part number being matched, dropped into the instructions text.
    """
    return {
        "best_listing": {
            "type": "choice",
            "instructions": (
                f"Which listing best matches the exact part number ({part_number}) and "
                "is the most appropriate source (used condition preferred)?"
            ),
            "criteria": _as_criteria_dict(listings),
        },
        "title_match_score": {
            "type": "score",
            "instructions": (
                f"How well does this listing's title match the part number "
                f"({part_number}) and description?"
            ),
            "criteria": _match_quality_scale(),
        },
    }


def QUESTION_SET_AGENT3() -> dict:
    """Agent 3: confidence that a cleaned part name has vehicle/location text stripped."""
    return {
        "cleaned_name_confidence": {
            "type": "score",
            "instructions": (
                "How confident are you that the cleaned part name is vehicle-free "
                "and location-free?"
            ),
            "criteria": _confidence_scale(),
        },
    }
