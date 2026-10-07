"""The fixed model setups a run can use. A run picks one whole setup; models are never
mixed per agent. The `bear` command uses "default"; the web page passes the chosen one
to run.py as BEAR_CONFIG.

  read        Agent 1 vision model (stage1_read.py)
  read_prompt None = the built-in PROMPT in stage1_read.py, else an agents/*.md file
  check       photo double-check (stage2b_rescue.visual_gate): None = gemini-3.5-flash
              YES/NO only; a Decisions model = ask it first, gemini decides when it fails
              or is unsure
"""
import os

CONFIGS = {
    "default": {
        "label": "Current setup", "tag": "Default",
        "about": "The current setup. 18/18 part numbers on the i40 test.",
        "read": "google/gemini-3.1-flash-lite", "read_prompt": None, "check": None,
    },
    "beta": {
        "label": "Luna photo check", "tag": "Beta",
        "about": "Cheaper photo check (OpenAI Luna Decisions, Gemini as backup). "
                 "Same results on the i40 test, about 26% cheaper per job.",
        "read": "google/gemini-3.1-flash-lite", "read_prompt": None,
        "check": "openai/gpt-6-luna-decisions",
    },
    "experimental": {
        "label": "Claude Haiku 5.5", "tag": "Experimental",
        "about": "Claude Haiku 5.5 reads the photos, plus the Beta photo check. "
                 "16-17/18 part numbers on the i40 test, so not for real jobs yet.",
        "read": "anthropic/claude-haiku-5.5", "read_prompt": "agents/agent1_instructions_v10_haiku.md",
        "check": "openai/gpt-6-luna-decisions",
    },
}
DEFAULT = "default"


def active():
    """The setup named by BEAR_CONFIG (unset = default). An unknown name is an error, not
    a silent fall back to another setup."""
    name = os.environ.get("BEAR_CONFIG") or DEFAULT
    if name not in CONFIGS:
        raise SystemExit(f"Unknown BEAR_CONFIG {name!r}. Choose one of: {', '.join(CONFIGS)}")
    return CONFIGS[name]
