"""Stage 2 — turn vision candidates into eBay-verified part numbers.

For every candidate reading (text + alt readings + joined split codes) search eBay
UK with several punctuation variants and keep the exact-match listings. A reading
that no UK seller lists is not a sellable part number. Jev only arbitrates when
more than one reading survives.
"""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

JUNK = re.compile(r"^(\d{1,4}|[A-Z]{1,4})$")


def query_variants(text):
    n = c.norm(text)
    v = [text.strip(), n]
    if re.fullmatch(r"\d{5}[A-Z0-9]{4,6}", n):          # Hyundai/Kia 5-5 style
        v.append(n[:5] + "-" + n[5:])
    m = re.fullmatch(r"([A-Z]+)(\d+)([A-Z]+\d+)", n)    # LP1061KFA04 style
    if m:
        v.append(" ".join(m.groups()))
    return [x for x in dict.fromkeys(v) if x]


HY_SUFFIX = re.compile(r"^(\d{5}[A-Z0-9]{5})([A-Z0-9]{1,3})$")


def expand_candidates(s1):
    """All readings worth checking, normalised-deduped, in vision's priority order."""
    out = []
    cands = s1.get("candidates") or []
    for cand in cands:
        for t in [cand.get("text")] + list(cand.get("alt_readings") or []):
            if not t or len(c.norm(t)) < 5 or JUNK.match(c.norm(t)):
                continue
            out.append((t, cand))
            m = HY_SUFFIX.match(c.norm(t))       # Hyundai revision/colour suffix
            if m:
                out.append((m.group(1), cand))
    # split codes printed on two lines: join adjacent short candidates
    texts = [x.get("text") for x in cands if x.get("text")]
    for a, b in zip(texts, texts[1:]):
        ja = c.norm(a) + c.norm(b)
        if 7 <= len(ja) <= 14:
            out.append((a + " " + b, {"role": "joined", "legibility": "joined", "note": "joined adjacent codes"}))
    seen, res = set(), []
    for t, cand in out:
        k = c.norm(t)
        if k not in seen:
            seen.add(k)
            res.append((t, cand))
    return res


def ebay_for(text, quick=False):
    seen, out = {}, []
    needle = c.norm(text)
    for q in (query_variants(text)[:1] if quick else query_variants(text)):
        try:
            items = c.ebay_search_raw(q)
        except Exception as e:
            return None, f"{type(e).__name__}"
        for it in items:
            iid = it.get("legacyItemId") or it.get("itemId")
            if iid in seen:
                continue
            seen[iid] = 1
            if needle in c.norm(c.match_text(it)):
                out.append(it)
    return out, None


def verify(s1, make="HYUNDAI"):
    """Returns list of dicts {text, cand, listings, make_hits} for every reading."""
    res = []
    for text, cand in expand_candidates(s1):
        items, err = ebay_for(text)
        if err:
            res.append({"text": text, "cand": cand, "listings": [], "error": err, "make_hits": 0})
            continue
        mh = sum(1 for it in items if make.upper() in (it.get("title") or "").upper())
        res.append({"text": text, "cand": cand, "listings": items, "make_hits": mh})
    return res
