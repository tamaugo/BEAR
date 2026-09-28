#!/usr/bin/env python3
"""
Stdlib-only HTTP client for OpenRouter's Decisions API ("Jev").

Jev is a decision model, not a chat model: instead of free text you send a `state`
(the thing to evaluate) plus one or more typed `questions` (noul/choice/score), and
get back structured `answers` with a probability-backed value for each -- no JSON
parsing of a model's prose required. Schema confirmed against OpenRouter's published
OpenAPI spec (GET https://openrouter.ai/openapi.json, path /api/alpha/decisions),
since the docs page at openrouter.ai/docs/api/api-reference/ur22l renders its body
client-side and isn't scrapable as static HTML.

This module is intentionally dependency-free (urllib, not requests) to match the
rest of tools/, which runs on whatever Python ships with macOS/pi with no venv setup.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

# 429/5xx are treated as transient; retry with exponential backoff (1s, 2s, 4s).
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


class JevAPIError(RuntimeError):
    """The Decisions API returned an error we can't recover from by retrying."""


class JevAuthError(JevAPIError):
    """401 -- the API key is missing, wrong, or revoked. Retrying won't help."""


class JevPaymentError(JevAPIError):
    """402 -- the OpenRouter account is out of credits. Retrying won't help."""


def _parse_dotenv(path: Path) -> dict:
    """Minimal KEY=VALUE parser -- no python-dotenv dependency per project constraints.

    Deliberately dumb: one assignment per line, '#' starts a comment, surrounding
    quotes are stripped. Good enough for the handful of vars in .env.example.
    """
    values = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def resolve_api_key() -> str:
    """Real shell env wins; .env is just a fallback for local runs -- never mutate
    os.environ with it, so the key's origin stays visible to anyone inspecting env."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    key = _parse_dotenv(ENV_FILE).get("OPENROUTER_API_KEY")
    if key:
        return key
    raise RuntimeError(
        "OPENROUTER_API_KEY not found in the environment or in .env at "
        f"{ENV_FILE}. Copy .env.example to .env and fill it in, or export the "
        "variable in your shell."
    )


def _error_message(body: bytes, code: int) -> str:
    """Decisions error bodies are {"error": {"code": int, "message": str}}; fall
    back to raw text if the provider ever returns something else on a 5xx."""
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
        message = payload.get("error", {}).get("message")
        if message:
            return message
    except (json.JSONDecodeError, AttributeError):
        pass
    return body.decode("utf-8", errors="replace")[:500] or f"HTTP {code}"


def call_decisions(model: str, state, questions: dict, *, api_key: str = None,
                    timeout: float = 60.0, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """POST one Decisions request and return the parsed JSON response.

    `state` is the content being evaluated (string, dict, or list); `questions` is
    a dict of question-key -> question spec (see jev_questions.py for builders).
    """
    api_key = api_key or resolve_api_key()
    body = json.dumps({"model": model, "state": state, "questions": questions}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(DECISIONS_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            message = _error_message(e.read(), e.code)
            if e.code == 401:
                raise JevAuthError(f"Decisions API rejected the API key (401): {message}") from None
            if e.code == 402:
                raise JevPaymentError(
                    f"OpenRouter account is out of credits (402): {message}") from None
            if e.code == 429 or e.code >= 500:
                last_error = JevAPIError(f"Decisions API returned {e.code}: {message}")
                if attempt < max_attempts:
                    time.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                    continue
                raise last_error
            # Other 4xx codes (400/403/404/413) mean the request itself is wrong --
            # retrying an unchanged request would just fail the same way again.
            raise JevAPIError(f"Decisions API returned {e.code}: {message}") from None
        except urllib.error.URLError as e:
            last_error = JevAPIError(f"Network error contacting Decisions API: {e.reason}")
            if attempt < max_attempts:
                time.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
                continue
            raise last_error

    raise last_error  # unreachable: loop above always returns or raises


# --- response helpers -----------------------------------------------------------
# Answer shape depends on the question's `type`: noul -> {"noul": float}, choice ->
# {"choice": str, "confidence": float, "probabilities": {...}}, score ->
# {"score": float, "confidence": float, "legend": {...}, "probabilities": {...}}.

def get_answer(response: dict, key: str) -> dict:
    try:
        return response["answers"][key]
    except KeyError:
        known = list(response.get("answers", {}))
        raise KeyError(f"No answer for question '{key}'. Known keys: {known}") from None


def get_value(response: dict, key: str):
    """The single decided value for a question: noul float, choice string, or
    score float -- whichever field is present depends on the answer's 'type'."""
    answer = get_answer(response, key)
    answer_type = answer.get("type")
    if answer_type == "noul":
        return answer["noul"]
    if answer_type == "choice":
        return answer["choice"]
    if answer_type == "score":
        return answer["score"]
    raise ValueError(f"Unknown answer type '{answer_type}' for question '{key}'")


def get_confidence(response: dict, key: str):
    """Present on choice/score answers; absent (None) on noul answers."""
    return get_answer(response, key).get("confidence")


def get_probabilities(response: dict, key: str):
    """Present on choice/score answers; maps each option/scale-index to a probability."""
    return get_answer(response, key).get("probabilities")


def get_legend(response: dict, key: str):
    """Score answers only: maps each scale index (as a string, e.g. "0") back to
    the criteria text it represents, so a raw score float can be made human-readable."""
    return get_answer(response, key).get("legend")


def get_cost(response: dict) -> float:
    return response["usage"]["cost"]


def get_usage(response: dict) -> dict:
    return response["usage"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Smoke test: send one real request to the Decisions API and print the result.")
    parser.add_argument(
        "--state", default=None,
        help="JSON string for the 'state' field. Defaults to a placeholder object if omitted.")
    parser.add_argument(
        "--model", default="typesafe/jev-1.13",
        help="Decisions model to call (default: typesafe/jev-1.13).")
    args = parser.parse_args()

    if args.state is not None:
        try:
            smoke_state = json.loads(args.state)
        except json.JSONDecodeError as e:
            sys.exit(f"--state is not valid JSON: {e}")
    else:
        smoke_state = {"note": "jev_client.py smoke test -- not real pipeline data."}

    # A single cheap noul question is enough to prove auth + connectivity + parsing
    # all work, without needing any of the pipeline-specific question sets.
    smoke_questions = {
        "state_is_nonempty": {
            "type": "noul",
            "instructions": "Does the state object contain any content at all?",
            "criteria": {
                "true": "The state has at least one field or a non-empty string.",
                "false": "The state is empty, null, or otherwise contains nothing usable.",
            },
        }
    }

    try:
        key = resolve_api_key()
    except RuntimeError as e:
        sys.exit(str(e))

    try:
        result = call_decisions(args.model, smoke_state, smoke_questions, api_key=key)
    except (JevAuthError, JevPaymentError) as e:
        sys.exit(f"Smoke test failed: {e}")
    except JevAPIError as e:
        sys.exit(f"Smoke test failed after {MAX_ATTEMPTS} attempts: {e}")

    print(f"model:      {result.get('model')}")
    print(f"request id: {result.get('id')}")
    for q_key, q_answer in result.get("answers", {}).items():
        print(f"answer[{q_key}]: {q_answer}")
    print(f"usage.cost: ${get_cost(result):.6f}")
