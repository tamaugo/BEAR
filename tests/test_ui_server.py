#!/usr/bin/env python3
"""Starts the `bear ui` server (bear2/ui/server.py, no browser) and checks it answers, takes a
photo upload and, when a second copy starts on the same port, moves to another port instead of
sharing it. On Windows also checks the Windows-only bits (Show in Explorer, refused file names).
No keys or network needed; nothing is run through the pipeline.

usage: python tests/test_ui_server.py
"""
import json, os, re, subprocess, sys, tempfile, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "bear2" / "ui" / "server.py"
WINDOWS = sys.platform == "win32"
PORT = 8765
FAILURES = []


def check(name, cond, detail=""):
    print(("PASS: " if cond else "FAIL: ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILURES.append(name)


def start(env):
    p = subprocess.Popen([sys.executable, "-u", str(SERVER), "--port", str(PORT), "--no-browser"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True)
    line = p.stdout.readline()
    m = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
    return p, (int(m.group(1)) if m else None), line


def call(port, method, path, body=None, ctype="application/json"):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main():
    procs = []
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "BEAR_UI_JOBS_DIR": d, "PYTHONUTF8": "1"}
        try:
            p1, port1, line = start(env)
            procs.append(p1)
            check("server starts on the asked port", port1 == PORT, line)
            code, body = call(port1, "GET", "/api/status")
            st = json.loads(body) if code == 200 else {}
            check("status answers", code == 200 and st.get("state") == "idle", body[:200])
            if WINDOWS:
                check("Show in Explorer button available", st.get("canOpen") is True)
            code, page = call(port1, "GET", "/")
            label = b"Show in Explorer" if WINDOWS else b"Show in Finder"
            check(f"page says {label.decode()}", code == 200 and label in page)

            code, body = call(port1, "POST", "/api/folder", {"name": "Zoë's Škoda photos"})
            job = json.loads(body).get("job") if code == 200 else None
            check("folder created", bool(job), body[:200])
            code, _ = call(port1, "PUT", f"/api/upload/{job}/IMG%201%20OSF.jpg", b"\xff\xd8\xff\xd9", "image/jpeg")
            check("photo uploaded", code == 200)
            saved = list(Path(d).glob("*/IMG 1 OSF.jpg"))
            check("photo saved in the jobs folder", len(saved) == 1, str(list(Path(d).rglob("*"))))
            if WINDOWS:
                for bad in ("CON.jpg", "a%3Ab.jpg"):
                    code, body = call(port1, "PUT", f"/api/upload/{job}/{bad}", b"x", "image/jpeg")
                    check(f"Windows-illegal name {bad} refused clearly", code == 400, body[:200])
            code, _ = call(port1, "GET", "/../../VERSION")
            check("files outside the page are not served", code == 404)

            p2, port2, line = start(env)
            procs.append(p2)
            check("second copy takes another port instead of sharing", port2 not in (None, PORT), line)
        finally:
            for p in procs:
                p.kill()
                p.wait()
                p.stdout.close()
    print(f"\n{len(FAILURES)} failed" if FAILURES else "\nall passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
