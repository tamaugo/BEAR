"""The fixed model setup a run uses. A run picks the setup whole; models are never mixed
per agent. Only the default setup exists on the Discord server: the beta setup (a cheaper
Decisions photo gate) and the experimental setup (Claude Haiku 5.5 reader with its own
prompt file) were removed here with their code, because the server never ran them.

  read        Agent 1 vision model (stage1_read.py)
  read_prompt None = the built-in PROMPT in stage1_read.py (no other prompt exists now)
  check       photo double-check (stage2b_rescue.visual_gate): None = gemini-3.5-flash
              YES/NO only
"""
import os

CONFIGS = {
    "default": {
        "label": "Current setup", "tag": "Default",
        "about": "The current setup. 18/18 part numbers on the i40 test.",
        "read": "google/gemini-3.1-flash-lite", "read_prompt": None, "check": None,
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
