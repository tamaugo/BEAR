#!/usr/bin/env python3
"""Offline end-to-end checks of the web page's run flow (no network, no credits).

Starts the real web server (bear2/ui/server.py) on a free port and plays every dev-mode
simulation (bear2/simulate.py) through its HTTP API, answering the questions the way the
operator would on the page: the first-line check, switching name models, the error banner
(codes BEAR-N01..N04, R01), Stop and Finish names, and the name model kept between runs.

usage: python3 tests/test_web_flow_offline.py
"""
import json, os, sys, threading, time, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["BEAR_SIM_PAUSE"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bear2" / "ui"))
import server  # noqa: E402
server.print = lambda *a, **k: None   # keep the run log out of the test output

QWEN, GEMINI, HAIKU = "qwen/qwen3.8-flash", "google/gemini-3.1-flash-lite", "anthropic/claude-haiku-5.5"
URL = ""

# Each scenario: the steps the operator takes, then what the page should end up showing.
#   ("check", "y"|"n", text the line must contain)   the first-line check above GO
#   ("pick", model)                                   picking the next name model
#   ("error", code, key)                              the error banner, answered try again (r) / switch (m) / stop (q)
#   ("finish", model)                                 Finish names with this name model
SCENARIOS = [
    ("ok", [("check", "y", "Starter Motor 1810A001")],
     {"state": "done", "nameModel": QWEN}),
    ("wrong-line", [("check", "n", "Shogun Starter Motor Bosch"), ("pick", GEMINI), ("check", "y", "- Starter Motor 1810A001")],
     {"state": "done", "nameModel": GEMINI}),
    ("all-wrong", [("check", "n", "Bosch"), ("pick", GEMINI), ("check", "n", "Bosch"), ("pick", HAIKU), ("check", "n", "Bosch")],
     {"state": "failed", "error": "BEAR-N04"}),
    ("check-rate-limit", [("error", "BEAR-N01", "m"), ("pick", HAIKU), ("check", "y", "Starter Motor")],
     {"state": "done", "nameModel": HAIKU}),
    ("rate-limit", [("check", "y", "Starter Motor"), ("error", "BEAR-N01", "q"), ("finish", GEMINI), ("check", "y", "Starter Motor")],
     {"state": "done", "nameModel": GEMINI}),
    ("no-response", [("check", "y", "Starter Motor"), ("error", "BEAR-N02", "r"), ("error", "BEAR-N02", "m"),
                     ("pick", GEMINI), ("check", "y", "Starter Motor")],
     {"state": "done", "nameModel": GEMINI}),
    ("unusable", [("check", "y", "Starter Motor"), ("error", "BEAR-N03", "m"), ("pick", HAIKU), ("check", "y", "Starter Motor")],
     {"state": "done", "nameModel": HAIKU}),
    ("crash", [("check", "y", "Starter Motor")],
     {"state": "failed", "error": "BEAR-R01"}),
]


def api(path, body=None):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "Host": "127.0.0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wait(answered):
    """The next unanswered question, or the finished status."""
    end = time.time() + 60
    while time.time() < end:
        d = api("/api/status")
        q = d["question"]
        if q and q["id"] not in answered or d["state"] != "running":
            return d
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the run")


def play(scenario, steps, want):
    server.NAME_MODEL = QWEN   # like a fresh `bear ui`
    d = api("/api/dev/simulate", {"scenario": scenario, "nameModel": QWEN})
    job, answered = d["job"], set()
    for step in steps:
        if step[0] == "finish":
            d = wait(answered)
            assert d["state"] == "failed" and d["canFinish"] and not d["error"], "Stop should leave Finish names, no banner"
            api("/api/finish", {"job": job, "nameModel": step[1]})
            continue
        d = wait(answered)
        q = d["question"]
        assert q, f"expected {step}, but the run ended ({d['state']}, error {d['error'] and d['error']['code']})"
        answered.add(q["id"])
        if step[0] == "check":
            assert q["kind"] == "check", f"expected the first-line check, got {q['ask']!r}"
            assert step[2] in q["ask"], f"line {q['ask']!r} should contain {step[2]!r}"
            key = step[1]
        elif step[0] == "pick":
            assert q["kind"] == "model", f"expected a model pick, got {q['ask']!r}"
            key = next(k for k, lab in q["choices"] if lab == server.assemble.label(step[1]))
        else:
            err = d["error"]
            assert err and err["code"] == step[1] and err.get("ask") == q["id"], f"expected banner {step[1]}, got {err}"
            assert err["detail"] and err["title"], "the banner needs a message and the full error"
            key = step[2]
        api("/api/answer", {"id": q["id"], "key": key})
    d = wait(answered)
    assert not (d["question"] and d["question"]["id"] not in answered), f"unexpected question {d['question']['ask']!r}"
    assert d["state"] == want["state"], f"state {d['state']}, want {want['state']}"
    if "nameModel" in want:
        assert d["nameModel"] == want["nameModel"], f"kept name model {d['nameModel']}, want {want['nameModel']}"
    code = d["error"] and d["error"]["code"]
    assert code == want.get("error"), f"banner {code}, want {want.get('error')}"
    if d["state"] == "done":
        r = d["results"]
        assert (r["photos"], r["priced"], r["failed"], r["nulls"]) == (7, 6, 1, 1), f"results {r}"
        assert Path(r["path"]).exists(), "results.xlsx missing"


def main():
    global URL
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    URL = f"http://127.0.0.1:{srv.server_address[1]}"
    bad = 0
    for scenario, steps, want in SCENARIOS:
        try:
            play(scenario, steps, want)
            print(f"pass  {scenario}")
        except AssertionError as e:
            bad += 1
            print(f"FAIL  {scenario}: {e}")
            proc = server.JOB.proc   # don't let a stuck run block the next scenario
            if proc and proc.poll() is None:
                proc.kill()
                time.sleep(0.5)
    srv.shutdown()
    print("all passed" if not bad else f"{bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
