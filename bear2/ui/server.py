"""BEAR 0.2 local web UI. `bear ui` starts this on 127.0.0.1 and opens the browser.

The browser uploads the chosen photo folder (one PUT per photo) into a job folder under
~/Documents/BEAR (override with BEAR_UI_JOBS_DIR), then GO runs the same pipeline as the
`bear` command (bear2/run.py) as a subprocess. Its output drives the progress steps and
the log; results.xlsx lands in <job folder>/bear-results-YYYYmmdd-HHMMSS/ as usual.

Credentials come from the environment `bin/bear` sets up (Keychain / .env) and are passed
straight through to the pipeline. Nothing here prints or returns them.

usage: python3 bear2/ui/server.py [--port N] [--no-browser]
"""
import json, os, re, shutil, subprocess, sys, threading, time, urllib.parse, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
RUN_PY = HERE.parent / "run.py"
REPO = HERE.parent.parent
JOBS = Path(os.environ.get("BEAR_UI_JOBS_DIR") or Path.home() / "Documents" / "BEAR")
PHOTO_EXT = (".jpg", ".jpeg", ".png")
MAX_PHOTO_BYTES = 50 * 1024 * 1024
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".webp": "image/webp",
         ".woff2": "font/woff2", ".png": "image/png"}

# Progress steps shown in the page, and the run.py output line that starts each one.
STEPS = ["Starting up", "Scanning photos", "Looking up on eBay", "Formatting text", "Creating your xlsx file"]
STEP_MARKERS = [(1, "photos to price"), (1, "Reading part numbers"), (2, "Pricing on eBay"),
                (3, "Cleaning part names"), (4, "Writing results.xlsx")]
COUNTER = re.compile(r"^(Reading part numbers|Pricing on eBay) (\d+)/(\d+)$")


# Models each agent uses, read from the pipeline source so the page always matches the code.
# (file, constant): Agent 1 reads part numbers, Agent 2 decides the eBay match (Jev),
# Agent 3 cleans eBay titles into part names.
AGENT_MODELS = [("stage1_read.py", "MODEL"), ("common.py", "JEV_MODEL"), ("assemble.py", "MODEL")]


def agent_models():
    out = []
    for fname, const in AGENT_MODELS:
        try:
            m = re.search(rf'^{const} = "([^"]+)"', (HERE.parent / fname).read_text(), re.M)
            out.append(m.group(1) if m else "unknown")
        except OSError:
            out.append("unknown")
    return out


def version():
    try:
        return (REPO / "VERSION").read_text().strip()
    except OSError:
        return "unknown"


class Job:
    """One photo folder + at most one run at a time. Guarded by LOCK."""

    def __init__(self):
        self.id = None
        self.folder = None        # job folder holding the uploaded photos
        self.name = ""            # original folder name, for display
        self.state = "idle"       # idle | running | done | failed
        self.step = 0
        self.detail = ""          # e.g. "7/12" for the active step
        self.log = ["Ready. Add a folder of photos to begin."]
        self.out = None
        self.cost = None
        self.proc = None

    def add(self, line):
        self.log.append(line)


LOCK = threading.Lock()
JOB = Job()


def new_job(name):
    name = re.sub(r"[^\w .-]", "_", name).strip(" .") or "photos"
    folder = JOBS / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)
    with LOCK:
        if JOB.state == "running":
            raise RuntimeError("A run is in progress.")
        JOB.__init__()
        JOB.id, JOB.folder, JOB.name = uuid.uuid4().hex, folder, name
        JOB.log = [f"Folder selected: {name}", f"Saving photos to {folder}"]
    return JOB.id


def run_pipeline(vehicle):
    with LOCK:
        out = JOB.folder / f"bear-results-{time.strftime('%Y%m%d-%H%M%S')}"
        JOB.state, JOB.step, JOB.detail, JOB.out, JOB.cost = "running", 0, "", out, None
        JOB.add(f"Started: {vehicle}")
        JOB.proc = subprocess.Popen(
            [sys.executable, "-u", str(RUN_PY), str(JOB.folder), vehicle, str(out)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(REPO))
        proc = JOB.proc
    threading.Thread(target=watch, args=(proc, out), daemon=True).start()


def watch(proc, out):
    """Turn run.py's output into steps + log lines. Counters ("Pricing on eBay 3/12") are
    written with \\r, so split on both line endings and only log a counter when it finishes."""
    buf = b""
    while True:
        chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for raw in parts:
            handle_line(raw.decode("utf-8", "replace").strip())
    handle_line(buf.decode("utf-8", "replace").strip())
    rc = proc.wait()
    with LOCK:
        if rc == 0 and (out / "results.xlsx").exists():
            JOB.state, JOB.step, JOB.detail = "done", len(STEPS), ""
            JOB.add("xlsx file created")
        else:
            JOB.state = "failed"
            JOB.add(f"BEAR run failed (exit code {rc}). See the messages above.")


def handle_line(line):
    if not line:
        return
    with LOCK:
        for step, marker in STEP_MARKERS:
            if marker in line and step > JOB.step:
                JOB.step, JOB.detail = step, ""
        m = COUNTER.match(line)
        if m:
            JOB.detail = f"{m.group(2)}/{m.group(3)}"
            if m.group(2) != m.group(3):
                return
        cost = re.search(r"run cost \$([\d.]+)", line)
        if cost:
            JOB.cost = float(cost.group(1))
        JOB.add(line)


def summary(out):
    """Counts for the Results section, read from the files run.py writes."""
    def lines(name):
        p = out / name
        return [l for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    rows = lines("agent2_results.md")
    failed = sum(1 for l in rows if " | FAILED | " in l)
    return {"photos": len(rows), "priced": len(rows) - failed, "failed": failed,
            "nulls": len(lines("null_files.txt"))}


def status(since):
    with LOCK:
        res = None
        if JOB.state == "done" and JOB.out:
            res = {"path": str(JOB.out / "results.xlsx"), "cost": JOB.cost, **summary(JOB.out)}
        return {"version": version(), "job": JOB.id, "folder": JOB.name, "state": JOB.state,
                "step": JOB.step, "detail": JOB.detail, "steps": STEPS,
                "log": JOB.log[since:], "logLength": len(JOB.log), "results": res,
                "canOpen": bool(shutil.which("open")), "models": agent_models()}


class Handler(BaseHTTPRequestHandler):
    server_version = "BEAR"

    def log_message(self, *a):  # keep the Terminal quiet
        pass

    def host_ok(self):
        # Refuse requests whose Host is not this machine (DNS-rebinding guard).
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")

    def send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def fail(self, code, msg):
        self.send(code, {"error": msg})

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self.host_ok():
            return self.fail(403, "forbidden")
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/api/status":
            return self.send(200, status(int((q.get("since") or ["0"])[0] or 0)))
        if url.path == "/api/log":
            with LOCK:
                text = "\n".join(JOB.log) + "\n"
            return self.send(200, text, "text/plain; charset=utf-8",
                             {"Content-Disposition": 'attachment; filename="bear-log.txt"'})
        if url.path == "/api/results.xlsx":
            with LOCK:
                p = JOB.out / "results.xlsx" if JOB.state == "done" and JOB.out else None
                fname = re.sub(r"[^A-Za-z0-9._-]", "_", JOB.name) + "-results.xlsx"
            if not p or not p.exists():
                return self.fail(404, "No results yet.")
            return self.send(200, p.read_bytes(),
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             {"Content-Disposition": f'attachment; filename="{fname}"'})
        path = "index.html" if url.path == "/" else url.path.lstrip("/")
        f = (STATIC / path).resolve()
        if STATIC not in f.parents or not f.is_file():
            return self.fail(404, "not found")
        return self.send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

    def do_PUT(self):
        # /api/upload/<job id>/<photo file name>, raw image bytes as the body
        if not self.host_ok():
            return self.fail(403, "forbidden")
        m = re.fullmatch(r"/api/upload/([0-9a-f]{32})/([^/]+)", urllib.parse.urlparse(self.path).path)
        if not m:
            return self.fail(404, "not found")
        name = Path(urllib.parse.unquote(m.group(2))).name
        n = int(self.headers.get("Content-Length") or 0)
        if not name or name.startswith(".") or Path(name).suffix.lower() not in PHOTO_EXT:
            return self.fail(400, "Only .jpg, .jpeg and .png photos.")
        if n > MAX_PHOTO_BYTES:
            return self.fail(413, "Photo too large.")
        with LOCK:
            if m.group(1) != JOB.id or JOB.state == "running":
                return self.fail(409, "That folder is no longer active.")
            folder = JOB.folder
        (folder / name).write_bytes(self.rfile.read(n))
        return self.send(200, {"ok": True})

    def do_POST(self):
        if not self.host_ok():
            return self.fail(403, "forbidden")
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self.body_json()
        except ValueError:
            return self.fail(400, "bad json")
        if path == "/api/folder":
            try:
                return self.send(200, {"job": new_job(str(data.get("name") or ""))})
            except RuntimeError as e:
                return self.fail(409, str(e))
        if path == "/api/uploaded":
            with LOCK:
                if data.get("job") == JOB.id:
                    count = sum(1 for p in JOB.folder.iterdir() if p.suffix.lower() in PHOTO_EXT)
                    JOB.add(f"Upload complete: {count} photos")
            return self.send(200, {"ok": True})
        if path == "/api/run":
            vehicle = " ".join(str(data.get("vehicle") or "").split())
            with LOCK:
                if data.get("job") != JOB.id or not JOB.folder:
                    return self.fail(409, "Add a folder of photos first.")
                if JOB.state == "running":
                    return self.fail(409, "A run is already in progress.")
                has_photos = any(p.suffix.lower() in PHOTO_EXT for p in JOB.folder.iterdir())
            if not has_photos:
                return self.fail(400, "No .jpg/.jpeg/.png photos in that folder.")
            if not vehicle:
                return self.fail(400, "Type the car first.")
            run_pipeline(vehicle)
            return self.send(200, {"ok": True})
        if path in ("/api/open", "/api/reveal"):
            with LOCK:
                p = JOB.out / "results.xlsx" if JOB.state == "done" and JOB.out else None
            if not p or not p.exists() or not shutil.which("open"):
                return self.fail(404, "No results to open.")
            subprocess.Popen(["open", str(p)] if path == "/api/open" else ["open", "-R", str(p)])
            return self.send(200, {"ok": True})
        return self.fail(404, "not found")


def main():
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8642
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)  # port busy: take any free one
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"BEAR {version()} UI running at {url}", flush=True)
    print("Keep this window open while you use it. Press Ctrl+C to stop.", flush=True)
    if "--no-browser" not in args:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping BEAR UI.")
        with LOCK:
            if JOB.proc and JOB.proc.poll() is None:
                JOB.proc.terminate()
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
