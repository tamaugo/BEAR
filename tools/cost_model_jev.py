#!/usr/bin/env python3
"""Agent 2 + full-pipeline cost model for the Jev fork, across batch sizes.

Companion to cost_model.py (which models the ORIGINAL stack). Same sequential
single-conversation assumptions, same chars-per-token basis; the model lineup
and per-line flow are updated for the Jev fork:

  Agent 1  google/gemini-3.1-flash-lite   vision extraction (single batch call)
  Agent 2  mistralai/mistral-nemo         tool calls + applies Jev's answer
  Jev      typesafe/jev-1.13              decision calls (input tokens only)
  Agent 3  qwen/qwen3.8-flash             compiler (single call, tuned prompt)

Prices verified live from OpenRouter's /api/v1/models on 2026-09-28; Jev price
from the Jev docs ($0.042/MTok input, output free) and cross-checked against
measured usage.cost (~$0.00002/call at ~475 input tokens).

Assumptions stated inline and adjustable. All arithmetic is printed so the
numbers in docs/pipeline-spec-jev.md can be traced back to this file.
"""

CHARS_PER_TOKEN = 3.5   # eBay titles are part-number/URL heavy -> tokenize worse than prose

# --- live prices ($ per million tokens, 2026-09-28) ---------------------------
PRICES = {
    "google/gemini-3.1-flash-lite": dict(inp=0.25, out=1.50, cread=0.025),
    "mistralai/mistral-nemo":       dict(inp=0.019, out=0.030, cread=0.000),
    "qwen/qwen3.8-flash":           dict(inp=0.15, out=0.47, cread=0.016),
    "meta/muse-spark-1.3":          dict(inp=1.25, out=4.25, cread=0.15),  # old Agent 2+3
}
JEV_INPUT_PER_MTOK = 0.042   # output tokens are free

# --- Agent 1 (vision, one batch call per job) ---------------------------------
IMG_TOKENS = 1500            # medium-resolution car part photo, approx
A1_PROMPT_TOK = 1600         # v9-jev instructions, approx
A1_OUT_PER_IMG = 15          # 'filename | part_number' line

# --- Agent 2 (sequential conversation, same shape as cost_model.py) -----------
AGENT2_PROMPT_CHARS = 6566   # measured: body of agent2-ebay-lookup.md (v7 similar)
BASE_PI_PROMPT_TOK = 3000
A2_SYS_TOK = int(AGENT2_PROMPT_CHARS / CHARS_PER_TOKEN) + BASE_PI_PROMPT_TOK

LISTING_LINE_CHARS = 195
AVG_LISTINGS = 12
TOOL_RESULT_TOK = int((85 + AVG_LISTINGS * LISTING_LINE_CHARS) / CHARS_PER_TOKEN)

TOOL_CALL_TOK = 25
INPUT_LINE_TOK = 12
ANSWER_TOK = 35
# nemo is not a reasoning model: the muse stack billed 120 reasoning tokens per
# turn; that entire cost line disappears.
REASONING_TOK = 0

# jev_decide per part-number line: Agent 2 composes state+questions as tool
# params (billed as Agent 2 output), the typed answers come back as a tool
# result (billed as Agent 2 input). Candidate list ~6 lines x 195 chars.
JEV_TOOLCALL_TOK = int((500 + 6 * 195) / CHARS_PER_TOKEN)   # composed request
JEV_RESULT_TOK = 160                                        # answers JSON

# --- Agent 3 (single call per job, tuned prompt) ------------------------------
A3_PROMPT_CHARS = 32282
A3_SYS_TOK = int(A3_PROMPT_CHARS / CHARS_PER_TOKEN)
A3_OUT_PER_LINE = 30


def agent1_cost(n):
    """One call: N images + prompt in, N result lines out."""
    inp = A1_PROMPT_TOK + n * IMG_TOKENS
    out = n * A1_OUT_PER_IMG
    p = PRICES["google/gemini-3.1-flash-lite"]
    # no caching on a one-shot call
    return (inp * p["inp"] + out * p["out"]) / 1e6, inp, out


def agent2_cost(n):
    """Sequential single conversation, from cost_model.simulate(), plus the
    per-line jev_decide tool round-trip. Cached case = the realistic one."""
    fresh = A2_SYS_TOK + n * INPUT_LINE_TOK
    cached = 0
    out = 0
    ctx = A2_SYS_TOK + n * INPUT_LINE_TOK
    for _ in range(n):
        # turn A: ebay_search tool call
        cached += ctx
        out += TOOL_CALL_TOK + REASONING_TOK
        ctx += TOOL_CALL_TOK
        fresh += TOOL_RESULT_TOK
        ctx += TOOL_RESULT_TOK
        # turn B: jev_decide tool call (compose request)
        cached += ctx
        out += JEV_TOOLCALL_TOK + REASONING_TOK
        ctx += JEV_TOOLCALL_TOK
        fresh += JEV_RESULT_TOK
        ctx += JEV_RESULT_TOK
        # turn C: emit the result line
        cached += ctx
        out += ANSWER_TOK + REASONING_TOK
        ctx += ANSWER_TOK
    p = PRICES["mistralai/mistral-nemo"]
    cost = (fresh * p["inp"] + cached * p["cread"] + out * p["out"]) / 1e6
    return cost, fresh + cached, out


def jev_cost(n):
    """Jev decision calls: one candidate-choice per part-number line (Agent 1's
    gate runs inside Agent 1's stage via the same tool; both bill the Jev key).
    Input tokens only; output is free."""
    input_tok = n * (int((500 + 6 * 195) / CHARS_PER_TOKEN) + 120)
    return input_tok * JEV_INPUT_PER_MTOK / 1e6, input_tok


def agent3_cost(n):
    """Single call: tuned prompt + Agent 2's result lines in, 4-field lines out."""
    inp = A3_SYS_TOK + n * INPUT_LINE_TOK * 3   # success lines are ~3x agent-1 lines
    out = n * A3_OUT_PER_LINE
    p = PRICES["qwen/qwen3.8-flash"]
    return (inp * p["inp"] + out * p["out"]) / 1e6, inp, out


def job_cost(n, label=True):
    a1, a1_in, a1_out = agent1_cost(n)
    a2, a2_in, a2_out = agent2_cost(n)
    jev, jev_in = jev_cost(n)
    a3, a3_in, a3_out = agent3_cost(n)
    total = a1 + a2 + jev + a3
    if label:
        print(f"--- {n}-part job (Jev fork) ---")
        print(f"  Agent 1 gemini-3.1-flash-lite : ${a1:.4f}  ({a1_in:,} in / {a1_out:,} out)")
        print(f"  Agent 2 mistral-nemo          : ${a2:.4f}  ({a2_in:,} in / {a2_out:,} out)")
        print(f"  Jev decisions (input only)    : ${jev:.4f}  ({jev_in:,} in, output free)")
        print(f"  Agent 3 qwen3.8-flash         : ${a3:.4f}  ({a3_in:,} in / {a3_out:,} out)")
        print(f"  TOTAL                         : ${total:.4f}  (~GBP {total * 0.79:.4f})")
    return total


def old_agent2_cost(n):
    """The original stack's Agent 2+3 on muse-spark-1.3 (standard tier), same
    conversation shape minus the jev_decide turn, for the comparison row."""
    fresh = A2_SYS_TOK + n * INPUT_LINE_TOK
    cached = 0
    out = 0
    ctx = A2_SYS_TOK + n * INPUT_LINE_TOK
    for _ in range(n):
        cached += ctx
        out += TOOL_CALL_TOK + 120
        ctx += TOOL_CALL_TOK
        fresh += TOOL_RESULT_TOK
        ctx += TOOL_RESULT_TOK
        cached += ctx
        out += ANSWER_TOK + 120
        ctx += ANSWER_TOK
    p = PRICES["meta/muse-spark-1.3"]
    a2 = (fresh * p["inp"] + cached * p["cread"] + out * p["out"]) / 1e6
    # old Agent 3: same prompt size on muse
    a3_in = A3_SYS_TOK + n * INPUT_LINE_TOK * 3
    a3_out = n * A3_OUT_PER_LINE
    a3 = (a3_in * p["inp"] + a3_out * p["out"]) / 1e6
    return a2 + a3


if __name__ == "__main__":
    print(f"Assumptions: {CHARS_PER_TOKEN} chars/token | Agent 2 sys {A2_SYS_TOK:,} tok | "
          f"tool result {TOOL_RESULT_TOK:,} tok ({AVG_LISTINGS} listings avg) | "
          f"Agent 3 sys {A3_SYS_TOK:,} tok\n")

    for n in (10, 35, 60, 80):
        job_cost(n)
        print()

    print("=== old vs new, Agent 2+3 only (the stages the fork changed) ===")
    for n in (10, 35, 60, 80):
        old = old_agent2_cost(n)
        new_total = job_cost(n, label=False)
        # new Agent 2+3 for an apples-to-apples row:
        a2, _, _ = agent2_cost(n)
        jev, _ = jev_cost(n)
        a3, _, _ = agent3_cost(n)
        new = a2 + jev + a3
        print(f"{n:>3} parts: old muse 2+3 ${old:.4f} (GBP {old * 0.79:.3f}) | "
              f"new 2+3+Jev ${new:.4f} (GBP {new * 0.79:.3f}) | "
              f"saving {old / max(new, 1e-9):.1f}x")
    print()
    print("=== full-pipeline per-part cost (Jev fork, cached) ===")
    for n in (10, 35, 60, 80):
        total = job_cost(n, label=False)
        print(f"{n:>3} parts: ${total / n:.5f}/part  (GBP {total * 0.79 / n:.5f}/part)")
