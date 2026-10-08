"""LEGACY - not used by BEAR. Kept for reference only.

The mechanical part-name cleaner from bear2/assemble.py (safe_name), removed in 0.4.
When the name model was rate-limited (issue 19) or returned a name it didn't like, BEAR
fell back to this. It was written for the Hyundai i40 test, so on any other car it left
make/model words and stray punctuation in the name, e.g.
"Mitsubishi Shogun Pajero . Relay Omron" instead of "Relay".

BEAR now stops and asks instead (bear2/assemble.py: clean_names, tidy_name, verify).
"""
import re


def norm(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def safe_name(name, title, pn):
    """Guard rails on the model's one job. Falls back to a mechanical clean if violated."""
    bad = (not name or "|" in name or len(name) > 90 or norm(pn) in norm(name)
           or re.search(r"\d{4,}", name))
    if not bad:
        return " ".join(w[:1].upper() + w[1:].lower() for w in name.split())
    t = re.sub(r"\b[\w-]*\d[\w-]*\b", " ", title)            # drop anything with a digit
    t = re.sub(r"(?i)\b(hyundai|i40|genuine|oem|mk\d|crdi|diesel|petrol)\b", " ", t)
    return " ".join(w[:1].upper() + w[1:].lower() for w in t.replace("|", " ").split())
