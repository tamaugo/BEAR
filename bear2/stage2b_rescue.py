"""Stage 2b — rescue hard reads (etched/cast metal, faded labels) and guard weak matches.

Triggered only when no directly-read number has a strong eBay presence (>= STRONG listings).
1. Confusable-character variants of each directly-read candidate (<= 2 swaps), e.g.
   0165-18 -> D165-1B (Bosch vacuum pump, IMG_3931), 9643895780 -> 9643695780 (IMG_3935).
2. Revision-suffix drop for suffixed formats (Ford 3M51-6030-BA -> 3M51-6030 family).
Any rescued or weak reading must pass a component gate before it can be used: a better
vision model names the part, and Jev decides whether the reading's listings sell that same
kind of component. A number that merely exists on eBay is not enough (a misread 0165-18
matched a gold watch before the category filter).
"""
import itertools, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c, configs
import jev_client as j
import stage2_numbers as s2

STRONG = 3
MAX_VARIANTS = 60
CONF = {"0": "OD8", "O": "0D", "D": "0O", "Q": "0O", "8": "B36", "B": "8", "3": "8",
        "6": "85G", "5": "6S", "S": "5", "G": "6C", "C": "G", "1": "I7L", "I": "1", "7": "1",
        "L": "1", "2": "Z", "Z": "2", "U": "V0", "V": "U"}
DESC_MODEL = "google/gemini-3.5-flash"


def variants(text):
    chars = list(text)
    pos = [i for i, ch in enumerate(chars) if ch.upper() in CONF]
    out = []
    for k in (1, 2):
        for combo in itertools.combinations(pos, k):
            for subs in itertools.product(*[CONF[chars[i].upper()] for i in combo]):
                v = chars[:]
                for i, ch in zip(combo, subs):
                    v[i] = ch
                out.append("".join(v))
    return list(dict.fromkeys(out))


def suffix_base(text):
    m = re.fullmatch(r"([A-Z0-9]{3,5}[- ][A-Z0-9]{3,6})[- ]([A-Z]{1,2})", text.strip().upper())
    return m.group(1) if m else None


def rescue_candidates(s1):
    cands = [x for x in (s1.get("candidates") or []) if x.get("role") in ("primary", "unclear")
             and len(c.norm(x.get("text") or "")) >= 6]
    out = []
    for x in cands:
        for t in [x["text"]] + list(x.get("alt_readings") or []):
            base = suffix_base(t)
            if base:
                out.append((base, {**x, "rescue": "suffix-family", "read_as": t}))
            for v in variants(t)[:MAX_VARIANTS]:
                out.append((v, {**x, "rescue": "confusable", "read_as": t}))
    seen, res = set(), []
    for t, cand in out:
        if c.norm(t) not in seen:
            seen.add(c.norm(t))
            res.append((t, cand))
    return res[:120]   # hard cap on eBay calls per photo (free tier 5,000/day)


def rescue(s1, make):
    found = []
    for t, cand in rescue_candidates(s1):
        items, err = s2.ebay_for(t, quick=True)
        if items:
            found.append({"text": t, "cand": cand, "listings": items,
                          "make_hits": sum(1 for it in items if make.upper() in (it.get("title") or "").upper())})
    return found


GATE_MODEL = configs.active()["check"]   # None (default setup) = gemini gate only; beta: openai/gpt-6-luna-decisions
GATE_FALLBACK_MODEL = "google/gemini-3.5-flash"
GATE_SURE = (0.2, 0.8)   # Luna below/above these is a clear NO/YES; in between asks the fallback


def gate_question(reading):
    titles = [(it.get("title") or "")[:100] for it in reading["listings"][:10]]
    return ("A vision model read a part number off this photo and eBay listings with that number are below. "
            "Look at the PHOTO. Is the part in the photo the same kind of component these listings sell? "
            "Judge by the physical part (shape, connector, ports, mounting), not by the number.",
            "\n".join(titles))


def visual_gate(photo_path, reading):
    """Photo + the reading's eBay titles -> does the photo show that kind of component?
    Replaces a text-only Jev gate: Jev never sees the photo, and a text description of the
    photo was wrong on IMG_3935 (said MAP sensor; the part is a crank sensor).
    Measured 2026-10-07 on 20 photo/listing pairs (10 true, 10 swapped, i40 set): Luna Decisions
    20/20 at ~$0.00009 per call (800px photo), gemini-3.5-flash 20/20 at ~$0.0036. Luna's
    answers were 0.84-1.00 on true pairs and 0.00-0.03 on swapped ones. Anything less clear-cut,
    or any Decisions API error, is decided by the old gemini gate, so the gate is never worse
    than before. Used only for weak/rescued/low-confidence reads."""
    if not GATE_MODEL:
        return visual_gate_chat(photo_path, reading)
    instructions, titles = gate_question(reading)
    try:
        r = c.decide(GATE_MODEL, [
            {"type": "text", "text": "Photo of one used car part. eBay listings for the part number read off it:\n" + titles},
            # chat-style image_url is read as a picture; an OpenAI "input_image" part is billed as text
            {"type": "image_url", "image_url": {"url": c.img_data_uri(photo_path, 800)}}],
            {"same": {"type": "noul", "instructions": instructions,
                      "criteria": {"true": "same kind of component", "false": "a different kind of component"}}},
            tag="visual_gate")
        p = r["answers"]["same"]["noul"]
        if p >= GATE_SURE[1]:
            return True
        if p <= GATE_SURE[0]:
            return False
    except Exception as e:
        print(f"(photo check: {GATE_MODEL} unavailable, using {GATE_FALLBACK_MODEL}: {str(e)[:120]})",
              file=sys.stderr, flush=True)
    return visual_gate_chat(photo_path, reading)


def visual_gate_chat(photo_path, reading):
    """The previous gate (gemini-3.5-flash YES/NO): fallback for errors and unclear Luna answers."""
    instructions, titles = gate_question(reading)
    out, _ = c.chat(GATE_FALLBACK_MODEL, [{"role": "user", "content": [
        {"type": "text", "text": instructions + " Reply with exactly one word: YES or NO.\nListings:\n" + titles},
        {"type": "image_url", "image_url": {"url": c.img_data_uri(photo_path, 1600)}}]}],
        max_tokens=1500, extra={"reasoning": {"effort": "low", "exclude": True}}, tag="visual_gate")
    return out.strip().upper().startswith("YES")
