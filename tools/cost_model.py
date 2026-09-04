#!/usr/bin/env python3
"""Agent 2 cost model across batch sizes. Assumptions stated inline and adjustable."""

CHARS_PER_TOKEN = 3.5   # eBay titles are part-number/URL heavy -> tokenize worse than prose

# --- measured / derived inputs -------------------------------------------------
AGENT2_PROMPT_CHARS = 6566          # measured: body of agent2-ebay-lookup.md
BASE_PI_PROMPT_TOK  = 3000          # pi's own default system prompt (--append-system-prompt ADDS to it)
SYS_TOK = int(AGENT2_PROMPT_CHARS / CHARS_PER_TOKEN) + BASE_PI_PROMPT_TOK

# One realistic ebay_search result, formatted exactly as ebay-search.ts emits it.
LISTING_LINE_CHARS = 195            # '- "title" | price GBP | Used | seller: x | https://ebay.co.uk/itm/...'
AVG_LISTINGS = 12                   # prior script testing: several searches returned 18-20, others few
TOOL_RESULT_TOK = int((85 + AVG_LISTINGS * LISTING_LINE_CHARS) / CHARS_PER_TOKEN)

TOOL_CALL_TOK  = 25                 # assistant's tool invocation
INPUT_LINE_TOK = 12                 # one line of Agent 1 output
ANSWER_TOK     = 35                 # one pipe-delimited result line

REASONING_TOK = {                   # billed as output tokens
    "anthropic/claude-haiku-4.5":     0,    # non-reasoning by default
    "meta/muse-spark-1.2":            120,  # reasoning model at :minimal, cannot be disabled
    "meta/muse-spark-1.2-contributor":120,
}

PRICES = {  # $ per million, from ~/.pi/agent/models-store.json
    "anthropic/claude-haiku-4.5":      dict(inp=1.00, out=5.00, cread=0.10),
    "meta/muse-spark-1.2":             dict(inp=1.25, out=4.25, cread=0.15),
    "meta/muse-spark-1.2-contributor": dict(inp=0.10, out=0.20, cread=0.002),
}

def simulate(n_parts, model):
    """Sequential single conversation: every turn re-sends the whole transcript."""
    reason = REASONING_TOK[model]
    ctx = SYS_TOK + n_parts * INPUT_LINE_TOK      # context at start
    fresh_in = ctx                                 # never-before-seen tokens
    cached_in = 0                                  # re-sent prefix
    out = 0
    for _ in range(n_parts):
        # turn A: model emits a tool call
        cached_in += ctx
        out += TOOL_CALL_TOK + reason
        ctx += TOOL_CALL_TOK
        # tool result enters context
        fresh_in += TOOL_RESULT_TOK
        ctx += TOOL_RESULT_TOK
        # turn B: model emits the result line
        cached_in += ctx
        out += ANSWER_TOK + reason
        ctx += ANSWER_TOK
    return fresh_in, cached_in, out

def cost(n, model):
    fresh, cached, out = simulate(n, model)
    p = PRICES[model]
    no_cache = ((fresh + cached) * p["inp"] + out * p["out"]) / 1e6
    with_cache = (fresh * p["inp"] + cached * p["cread"] + out * p["out"]) / 1e6
    return no_cache, with_cache, fresh + cached, out

MODELS = ["anthropic/claude-haiku-4.5", "meta/muse-spark-1.2", "meta/muse-spark-1.2-contributor"]
LABEL = {"anthropic/claude-haiku-4.5":"Haiku 4.5",
         "meta/muse-spark-1.2":"Muse 1.2 standard",
         "meta/muse-spark-1.2-contributor":"Muse 1.2 Contributor"}

print(f"Assumptions: {CHARS_PER_TOKEN} chars/token | system prompt {SYS_TOK:,} tok | "
      f"tool result {TOOL_RESULT_TOK:,} tok ({AVG_LISTINGS} listings avg) | "
      f"reasoning {REASONING_TOK['meta/muse-spark-1.2']} tok/turn on Muse\n")

for n in (10, 35, 60, 80):
    print(f"===== {n} parts =====")
    print(f"{'model':22} {'total in tok':>13} {'out tok':>9} {'NO cache':>11} {'CACHED':>10}  {'£ cached':>9}")
    for m in MODELS:
        nc, wc, tin, tout = cost(n, m)
        print(f"{LABEL[m]:22} {tin:>13,} {tout:>9,} {'$'+format(nc,'.4f'):>11} {'$'+format(wc,'.4f'):>10}  {'£'+format(wc*0.79,'.4f'):>9}")
    print()

print("Per-part cost, CACHED (the realistic case):")
print(f"{'model':22}" + "".join(f"{str(n)+' parts':>12}" for n in (10,35,60,80)))
for m in MODELS:
    row = "".join(f"{'£'+format(cost(n,m)[1]*0.79/n,'.4f'):>12}" for n in (10,35,60,80))
    print(f"{LABEL[m]:22}{row}")
