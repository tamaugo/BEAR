#!/usr/bin/env python3
"""
eBay Browse API test script for Agent 2 (car part lookup).

Reads credentials from environment variables — set these in your own
terminal before running, never hardcode them here:
  EBAY_APP_ID   - App ID / Client ID
  EBAY_CERT_ID  - Cert ID / Client Secret
(Dev ID is NOT required for this flow — the Browse API's OAuth2
client-credentials grant only uses App ID + Cert ID. Dev ID is only used
by eBay's older Trading/XML APIs, which this script doesn't touch.)

Usage:
  export EBAY_APP_ID="YourApp-PRD-xxxxxxxxxxxx-xxxxxxxx"
  export EBAY_CERT_ID="PRD-xxxxxxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

  python3 ebay_browse_lookup.py "92501-C1000"
      -> looks up one part number

  python3 ebay_browse_lookup.py --file output/agent1_results.md
      -> batch mode: reads Agent 1's filename-tagged output and looks up
         every part number line in it, printing an Agent-2-shaped result
         line for each (or passing through Agent 1 fail lines re-tagged,
         same as agent2-ebay-lookup.md's own rules)

No external packages needed — standard library only (urllib, base64, json).

--- What this script does and does NOT do, and why ---

DOES:
  - Gets a real OAuth2 Application access token via the client-credentials
    grant (https://api.ebay.com/identity/v1/oauth2/token).
  - Searches ACTIVE listings on the real eBay.co.uk marketplace (Browse
    API, item_summary/search), filtered to itemLocationCountry:GB.
  - Approximates "exact part number match" by post-filtering results to
    those that actually contain the exact part number string — Browse
    API's `q` parameter is a relevance-ranked keyword search, not a
    literal exact-match query, so this is the closest a public search API
    can get to Agent 2's "no fuzzy matching" rule.
  - Searches the full 200-result page (the Browse API per-page maximum)
    rather than just the top 20, because the post-filter runs AFTER the
    fetch. See "Fix 1" below.
  - Matches against the listing's structured fields as well as its title
    (MPN / item specifics), not the title alone. See "Fix 2" below.
  - Surfaces every matching candidate with title/price/condition/seller/
    URL/thumbnail so you (or the real Agent 2 prompt) can apply the
    clearest-title / most-common-price tie-break rule — this script
    deliberately does NOT try to automate that judgment call itself.

DOES NOT:
  - Search sold/completed listings. That requires the Marketplace Insights
    API, which eBay's own live docs (checked 2026-09-02) explicitly list
    as "restricted and not open to new users at this time." So right now,
    Agent 2's sold-then-active fallback logic can only be tested against
    its active-listings half — there is no way to get real sold-price data
    without that separate, gated approval.
  - Filter by "UK seller" in the strict sense — itemLocationCountry:GB
    filters by where the ITEM is located, which is the closest available
    proxy but isn't guaranteed identical to the seller's registered
    business country. There's no separate "seller country" filter in the
    Browse API.
  - Check eBay API rate limits (Agent 2's Step 0). eBay does have a real
    Analytics API for this (getUserRateLimits), but I haven't verified its
    exact request shape closely enough to bolt it on here without risking
    a silently-wrong implementation — flagging this as a known gap rather
    than guessing. At your current test volume (a handful of parts) it
    won't matter; wire it up before running large real jobs.

--- Fixes applied after the "No eBay Listing Found" false negatives ---

A real run had Agent 2 report "No eBay Listing Found" for GS8T 66 EM0 and
C235 51 310, both of which demonstrably have live UK listings (3 and ~7).
Three separate causes, all fixed here:

  Fix 1 — only the first 20 results were ever examined.
    search_active_listings() defaulted to limit=20. Because the exact-match
    check is a POST-filter, anything eBay ranked below position 20 was
    invisible. For a number like "C235 51 310" the tokens "51" and "310"
    are generic enough that relevance ranking buries the genuine listings
    at position ~25-60. The default is now 200, the Browse API per-page
    maximum. This costs nothing extra: eBay's free tier bills per CALL
    (5,000/day), not per result, so one 200-result call is the same spend
    as one 20-result call.

  Fix 2 — the exact-match check only read the listing title.
    filter_exact_match() built its haystack from item["title"] alone. Many
    sellers write a human-readable title with no part number in it and put
    the number in the structured MPN / item-specifics fields instead —
    those listings could never match. The search now requests
    fieldgroups=EXTENDED and the haystack is built from the title PLUS
    whatever extra text fields come back (see extract_match_text(), which
    reads them defensively — EXTENDED's exact payload varies by listing and
    every field may legitimately be absent). The existing normalisation
    (strip spaces and hyphens, uppercase) is still applied to both sides.
    Deliberately NOT done: a per-item GET /item/{id} call to fetch full
    item specifics. That would turn one API call per part into N+1 and is
    rejected on quota grounds.

  Fix 3 — useful fields were fetched and then thrown away.
    summarize_candidates() now carries the listing URL (itemWebUrl) and a
    thumbnail image URL (image.imageUrl, falling back to
    thumbnailImages[0].imageUrl) through to the output, alongside the
    existing condition and seller. The downstream pipeline needs the URL in
    its final spreadsheet, and the thumbnail makes eyeballing a match easy.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
MARKETPLACE_ID = "EBAY_GB"
SCOPE = "https://api.ebay.com/oauth/api_scope"


def get_access_token(app_id: str, cert_id: str) -> str:
    """OAuth2 client-credentials grant. Returns a short-lived Application access token."""
    credentials = f"{app_id}:{cert_id}"
    basic_auth = base64.b64encode(credentials.encode()).decode()

    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "scope": SCOPE,
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Authorization", f"Basic {basic_auth}")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise SystemExit(
            f"OAuth token request failed ({e.code}): {error_body}\n\n"
            "Most likely causes:\n"
            "  - EBAY_APP_ID / EBAY_CERT_ID not set correctly (check for typos, "
            "extra whitespace, or a stray newline from copy-paste)\n"
            "  - The keyset still shows 'disabled' on the Application Keys page "
            "(the account-deletion exemption needs to be submitted and applied "
            "before ANY production call will succeed, including this one)"
        )

    return data["access_token"]


def search_active_listings(token: str, part_number: str, limit: int = 200) -> list:
    """
    Search Browse API active listings, UK-located items only.

    limit defaults to 200 — the Browse API per-page maximum — not 20.
    filter_exact_match() runs AFTER this fetch, so anything not returned
    here can never match, and genuine listings for a part number made of
    generic-looking tokens routinely rank below position 20. eBay's free
    tier counts calls, not results, so the wider page is free.

    fieldgroups=EXTENDED asks eBay for the additional per-item fields
    (short description / item specifics) that extract_match_text() needs in
    order to match a listing whose part number lives in its MPN field
    rather than its title.
    """
    params = {
        "q": part_number,
        "filter": "itemLocationCountry:GB",
        "limit": str(limit),
        "fieldgroups": "EXTENDED",
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-EBAY-C-MARKETPLACE-ID", MARKETPLACE_ID)

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise SystemExit(f"Browse API search failed ({e.code}): {error_body}")

    return data.get("itemSummaries", [])


def normalize(text: str) -> str:
    """Strip spaces and hyphens, uppercase. Applied to BOTH sides of every
    comparison so a formatting difference alone can't cause a false
    non-match — eBay listings format part numbers inconsistently, e.g.
    "925 01-C1000" vs "92501-C1000"."""
    return text.replace(" ", "").replace("-", "").upper()


def extract_match_text(item: dict) -> list:
    """
    Collect every string on a search result that could plausibly carry the
    part number: the title, plus whatever fieldgroups=EXTENDED gave us.

    Written defensively on purpose. EXTENDED's payload is not uniform —
    which extra fields eBay attaches varies by listing and by category, and
    any of them may simply be absent — so this reads what is there and
    ignores what isn't, rather than assuming a fixed shape. Anything
    unexpected is skipped instead of raising.

    Fields harvested when present:
      title              - always there
      shortDescription   - EXTENDED's main addition
      mpn                - Manufacturer Part Number, when eBay surfaces it
                           at the summary level
      localizedAspects   - the structured "item specifics" name/value
                           pairs; the MPN a seller filled in usually lives
                           here even when the title has no number in it
      itemGroupType /
      additional aspect
      containers         - handled generically by the dict/list walk below
    """
    chunks = []

    for key in ("title", "shortDescription", "mpn", "subtitle"):
        value = item.get(key)
        if isinstance(value, str) and value:
            chunks.append(value)

    # Item specifics come back as a list of {"type","name","value"} dicts.
    # Take every value string — restricting to name == "MPN" would miss the
    # sellers who label the same field "Manufacturer Part Number", "OE/OEM
    # Part Number", "Reference OE/OEM Number", etc.
    aspects = item.get("localizedAspects")
    if isinstance(aspects, list):
        for aspect in aspects:
            if not isinstance(aspect, dict):
                continue
            for key in ("name", "value"):
                value = aspect.get(key)
                if isinstance(value, str) and value:
                    chunks.append(value)

    return chunks


def filter_exact_match(items: list, part_number: str) -> list:
    """
    Keep only results that contain the exact part number, ignoring
    spaces/hyphens.

    The haystack is the title PLUS the structured fields returned by
    fieldgroups=EXTENDED (see extract_match_text). Matching on the title
    alone was silently discarding every listing whose seller wrote a
    human-friendly title and put the number in the MPN / item-specifics
    field instead — a large fraction of genuine car-part listings.
    """
    needle = normalize(part_number)
    matches = []
    for item in items:
        haystack = normalize(" ".join(extract_match_text(item)))
        if needle in haystack:
            matches.append(item)
    return matches


def extract_image_url(item: dict):
    """Best available thumbnail URL, or None. Checks image.imageUrl first,
    then the first entry of thumbnailImages — either may be missing."""
    image = item.get("image")
    if isinstance(image, dict) and isinstance(image.get("imageUrl"), str):
        return image["imageUrl"]

    thumbs = item.get("thumbnailImages")
    if isinstance(thumbs, list):
        for thumb in thumbs:
            if isinstance(thumb, dict) and isinstance(thumb.get("imageUrl"), str):
                return thumb["imageUrl"]

    return None


def summarize_candidates(items: list) -> list:
    """One flat dict per candidate. url and image are carried through to
    the pipeline's final output, so they must not be dropped here."""
    return [
        {
            "title": i.get("title"),
            "price": (i.get("price") or {}).get("value"),
            "currency": (i.get("price") or {}).get("currency"),
            "condition": i.get("condition"),
            "seller": (i.get("seller") or {}).get("username"),
            "url": i.get("itemWebUrl"),
            "image": extract_image_url(i),
        }
        for i in items
    ]


def lookup_one(token: str, filename: str, part_number: str) -> None:
    print(f"\n--- {filename} | {part_number} ---")

    all_items = search_active_listings(token, part_number)
    exact = filter_exact_match(all_items, part_number)

    if not exact:
        print(f"{filename} | FAILED | Agent 2 | No eBay Listing Found")
        if all_items:
            print(f"  (note: {len(all_items)} loosely-matching result(s) came back "
                  f"from the keyword search, but none contained the exact part "
                  f"number in the title or item specifics — not used, per "
                  f"exact-match-only rule)")
        return

    candidates = summarize_candidates(exact)
    print(f"  {len(candidates)} exact-match ACTIVE UK listing(s) found "
          f"(no sold-price data available — see script header):")
    for c in candidates:
        print(f"    - \"{c['title']}\" | {c['price']} {c['currency']} | "
              f"{c['condition']} | seller: {c['seller']} | {c['url']} | "
              f"img: {c['image']}")
    print("  -> apply Agent 2's tie-break rule (clearest title, else most-common "
          "price, else median) to pick one from the candidates above.")


def read_agent1_file(path: str):
    """Parses agent1_results.md-style lines: 'filename | part_number' or
    'filename | FAILED | Could Not Produce Clear Part Number'."""
    pairs = []
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            filename = parts[0]
            if parts[1].upper() == "FAILED":
                print(f"{filename} | FAILED | Agent 1 | Could Not Produce Clear Part Number")
                continue
            # ignore any space-separated OEM bonus number, primary only
            part_number = parts[1].split(" ")[0]
            pairs.append((filename, part_number))
    return pairs


def main() -> None:
    app_id = os.environ.get("EBAY_APP_ID")
    cert_id = os.environ.get("EBAY_CERT_ID")

    if not app_id or not cert_id:
        raise SystemExit(
            "Set EBAY_APP_ID and EBAY_CERT_ID as environment variables first, e.g.:\n"
            '  export EBAY_APP_ID="YourApp-PRD-..."\n'
            '  export EBAY_CERT_ID="PRD-..."\n'
            "(Dev ID is not needed for this script — don't set or paste it anywhere.)"
        )

    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage:\n"
            '  python3 ebay_browse_lookup.py "<part_number>"\n'
            "  python3 ebay_browse_lookup.py --file <agent1_results.md>"
        )

    token = get_access_token(app_id, cert_id)

    if sys.argv[1] == "--file":
        if len(sys.argv) < 3:
            raise SystemExit("Provide a file path after --file")
        for filename, part_number in read_agent1_file(sys.argv[2]):
            lookup_one(token, filename, part_number)
    else:
        lookup_one(token, "manual-test", sys.argv[1])


if __name__ == "__main__":
    main()
