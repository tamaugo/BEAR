#!/usr/bin/env python3
"""
A/B fixture test: which cheap chat model can replace meta/muse-spark-1.3:minimal
as Agent 3 (the compiler)?

This harness APPROXIMATES Agent 3. The real Agent 3 runs inside pi with its own
wrapper and writes its own output file; here we send the same system prompt
(the full body of agents/agent3_instructionsv4.md) and the same user input to
each candidate model over OpenRouter's plain chat completions API, and treat
the model's reply text as if it were the file Agent 3 would have written. The
point of the A/B is model capability on identical prompt + input + settings,
not a faithful reproduction of the pi wrapper.

Live network test -- costs a small amount of real OpenRouter credit per run.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from jev_client import resolve_api_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
INSTRUCTIONS_PATH = REPO_ROOT / "agents" / "agent3_instructionsv4.md"
INPUT_PATH = REPO_ROOT / "tests" / "fixtures" / "agent3_v4_dummy_input.md"
EXPECTED_PATH = REPO_ROOT / "tests" / "fixtures" / "agent3_v4_expected_output.md"

CANDIDATES = ["mistralai/mistral-nemo", "openai/gpt-oss-20b", "qwen/qwen3.7-flash"]

MAX_ATTEMPTS = 2
BACKOFF_SECONDS = 2.0
TIMEOUT_SECONDS = 120.0
MAX_TOKENS = 6000


def build_messages() -> list:
    system_prompt = INSTRUCTIONS_PATH.read_text()
    job_input = INPUT_PATH.read_text()
    user_prompt = (
        "Job inputs:\n"
        "Vehicle string: MAZDA 6 MK2 2008 SEDAN 2.5 PETROL\n"
        "NULL photos: (none)\n"
        "Output path: ./output/agent3_results.txt\n\n"
        "Agent 2 results to process:\n" + job_input
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def call_chat(model: str, messages: list, api_key: str) -> dict:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
        # Cap reasoning models' thinking so budget goes to the answer, not the
        # trace (gpt-oss-20b burned 2000 tokens reasoning and returned empty
        # content on the first run). Ignored by non-reasoning models.
        "reasoning": {"effort": "low", "exclude": True},
    }).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(CHAT_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            if (e.code == 429 or e.code >= 500) and attempt < MAX_ATTEMPTS:
                last_error = f"HTTP {e.code}: {error_body[:300]}"
                time.sleep(BACKOFF_SECONDS)
                continue
            raise RuntimeError(f"HTTP {e.code}: {error_body[:500]}") from None
        except urllib.error.URLError as e:
            if attempt < MAX_ATTEMPTS:
                last_error = f"Network error: {e.reason}"
                time.sleep(BACKOFF_SECONDS)
                continue
            raise RuntimeError(f"Network error: {e.reason}") from None
    raise RuntimeError(last_error or "unreachable")


def extract_text(response: dict) -> str:
    return response["choices"][0]["message"]["content"] or ""


def extract_cost(response: dict) -> float:
    usage = response.get("usage") or {}
    prompt_cost = usage.get("prompt_cost")
    completion_cost = usage.get("completion_cost")
    if prompt_cost is not None and completion_cost is not None:
        return float(prompt_cost) + float(completion_cost)
    return float(usage.get("cost", 0.0))


def nonempty_lines(text: str) -> list:
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_fenced_block(markdown_text: str) -> str:
    """Both the ground-truth fixture and (in practice) every model's reply wrap
    the data lines in a fenced ``` block with prose around it. Pull just the
    first fence's contents so scoring compares data against data, not data
    against prose. Falls back to the raw text when no balanced fence exists."""
    lines = markdown_text.splitlines()
    fence_indices = [i for i, line in enumerate(lines) if line.strip().startswith("```")]
    if len(fence_indices) < 2:
        return markdown_text
    start, end = fence_indices[0], fence_indices[1]
    return "\n".join(lines[start + 1:end])


def score_output(actual_text: str, expected_text: str) -> dict:
    actual_text = extract_fenced_block(actual_text)
    expected_text = extract_fenced_block(expected_text)
    exact_match = actual_text.strip() == expected_text.strip()
    actual_lines = nonempty_lines(actual_text)
    expected_lines = nonempty_lines(expected_text)
    total = len(expected_lines)
    matched = 0
    field_mismatch_counts = {}
    for i in range(total):
        expected_line = expected_lines[i]
        actual_line = actual_lines[i] if i < len(actual_lines) else None
        if actual_line == expected_line:
            matched += 1
            continue
        if actual_line is None:
            field_mismatch_counts["missing-line"] = field_mismatch_counts.get("missing-line", 0) + 1
            continue
        expected_fields = expected_line.split(" | ")
        actual_fields = actual_line.split(" | ")
        max_fields = max(len(expected_fields), len(actual_fields))
        for idx in range(max_fields):
            expected_field = expected_fields[idx] if idx < len(expected_fields) else None
            actual_field = actual_fields[idx] if idx < len(actual_fields) else None
            if expected_field != actual_field:
                key = f"field[{idx}]"
                field_mismatch_counts[key] = field_mismatch_counts.get(key, 0) + 1
    return {
        "exact_match": exact_match,
        "matched": matched,
        "total": total,
        "field_mismatch_counts": field_mismatch_counts,
    }


def format_report(model: str, score: dict, cost, error: str = None) -> str:
    lines = [f"MODEL: {model}"]
    if error:
        lines.append(f"  ERROR: {error}")
        lines.append(f"  line match: 0/{score['total']}")
        return "\n".join(lines)
    lines.append(f"  exact match: {score['exact_match']}")
    lines.append(f"  line match: {score['matched']}/{score['total']}")
    if score["field_mismatch_counts"]:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(score["field_mismatch_counts"].items()))
        lines.append(f"  mismatched-line fields: {summary}")
    else:
        lines.append("  mismatched-line fields: none")
    cost_str = f"${cost:.6f}" if cost is not None else "unknown"
    lines.append(f"  cost: {cost_str}")
    return "\n".join(lines)


def main() -> int:
    try:
        api_key = resolve_api_key()
    except RuntimeError as e:
        print(str(e))
        return 1

    messages = build_messages()
    expected_text = EXPECTED_PATH.read_text()

    results = []
    for model in CANDIDATES:
        try:
            response = call_chat(model, messages, api_key)
            actual_text = extract_text(response)
            score = score_output(actual_text, expected_text)
            cost = extract_cost(response)
            print(format_report(model, score, cost))
            results.append((model, score, cost))
        except Exception as e:  # noqa: BLE001 - any model/API failure is a finding, not a crash
            expected_total = len(nonempty_lines(expected_text))
            score = {"exact_match": False, "matched": 0, "total": expected_total,
                      "field_mismatch_counts": {}}
            print(format_report(model, score, None, error=str(e)))
            results.append((model, score, None))
        print()

    def sort_key(entry):
        _, score, cost = entry
        cost_for_sort = cost if cost is not None else float("inf")
        return (-score["matched"], cost_for_sort)

    ranked = sorted(results, key=sort_key)
    best_model, best_score, best_cost = ranked[0]
    cost_str = f"${best_cost:.6f}" if best_cost is not None else "unknown"
    print(
        f"RECOMMENDATION: {best_model} "
        f"(line match {best_score['matched']}/{best_score['total']}, cost {cost_str})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
