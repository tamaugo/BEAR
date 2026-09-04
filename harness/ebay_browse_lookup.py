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
    those whose title actually contains the exact part number string —
    Browse API's `q` parameter is a relevance-ranked keyword search, not a
    literal exact-match query, so this is the closest a public search API
    can get to Agent 2's "no fuzzy matching" rule.
  - Surfaces every matching candidate with title/price/seller so you (or
    the real Agent 2 prompt) can apply the clearest-title / most-common-
    price tie-break rule — this script deliberately does NOT try to
    automate that judgment call itself.

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


def search_active_listings(token: str, part_number: str, limit: int = 20) -> list:
    """Search Browse API active listings, UK-located items only."""
    params = {
        "q": part_number,
        "filter": "itemLocationCountry:GB",
        "limit": str(limit),
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


def filter_exact_match(items: list, part_number: str) -> list:
    """
    Keep only results whose title contains the exact part number, ignoring
    spaces/hyphens (eBay listing titles format part numbers inconsistently,
    e.g. "925 01-C1000" vs "92501-C1000" — this normalizes both sides
    before comparing so a formatting difference alone doesn't cause a
    false non-match).
    """
    needle = part_number.replace(" ", "").replace("-", "").upper()
    matches = []
    for item in items:
        title = item.get("title", "")
        haystack = title.replace(" ", "").replace("-", "").upper()
        if needle in haystack:
            matches.append(item)
    return matches


def summarize_candidates(items: list) -> list:
    return [
        {
            "title": i.get("title"),
            "price": i.get("price", {}).get("value"),
            "currency": i.get("price", {}).get("currency"),
            "condition": i.get("condition"),
            "seller": i.get("seller", {}).get("username"),
            "url": i.get("itemWebUrl"),
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
                  f"number in the title — not used, per exact-match-only rule)")
        return

    candidates = summarize_candidates(exact)
    print(f"  {len(candidates)} exact-match ACTIVE UK listing(s) found "
          f"(no sold-price data available — see script header):")
    for c in candidates:
        print(f"    - \"{c['title']}\" | {c['price']} {c['currency']} | "
              f"{c['condition']} | seller: {c['seller']} | {c['url']}")
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
