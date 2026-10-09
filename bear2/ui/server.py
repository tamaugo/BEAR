"""BEAR 0.3 local web UI. `bear ui` starts this on 127.0.0.1 and opens the browser.

The browser uploads the chosen photo folder (one PUT per photo) into a job folder under
~/Documents/BEAR (override with BEAR_UI_JOBS_DIR), then GO runs the same pipeline as the
`bear` command (bear2/run.py) as a subprocess. Its output drives the progress steps and
is echoed to the Terminal running `bear ui`; results.xlsx lands in <job folder>/bear-results-YYYYmmdd-HHMMSS/ as usual.

Questions from the run (the first-line check, a failed name model) arrive as marked lines
(assemble.WEB_MARK) and are shown on the page; the answer goes back on the run's stdin. The
name model that worked is kept in memory until `bear ui` closes, so a restart uses the default.

Credentials come from the environment `bin/bear` sets up (Keychain / .env) and are passed
straight through to the pipeline. Nothing here prints or returns them.

usage: python3 bear2/ui/server.py [--port N] [--no-browser]
"""
import itertools, json, os, re, shutil, subprocess, sys, threading, time, urllib.parse, uuid, webbrowser
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
STEPS = ["Starting up", "Verifying first part", "Scanning photos", "Looking up on eBay",
         "Formatting text", "Creating your xlsx file"]
STEP_MARKERS = [(1, "Checking the first part"), (2, "Reading part numbers"), (3, "Pricing on eBay"),
                (4, "Cleaning part names"), (5, "Writing results.xlsx")]
WAITING = "waiting for you"
COUNTER = re.compile(r"^(Reading part numbers|Pricing on eBay) (\d+)/(\d+)$")


# The fixed model setups (bear2/configs.py). The page offers one drop-down of whole setups;
# models are never chosen per agent.
sys.path.insert(0, str(HERE.parent))
import configs, assemble  # noqa: E402

# Models every setup shares, read from the pipeline source so the page always matches the code.
# Agent 2 decides the eBay match (Jev), Agent 3 cleans eBay titles into part names.
SHARED_MODELS = [("common.py", "JEV_MODEL"), ("stage2b_rescue.py", "GATE_FALLBACK_MODEL")]


def source_model(fname, const):
    try:
        m = re.search(rf'^{const} = "([^"]+)"', (HERE.parent / fname).read_text(), re.M)
        return m.group(1) if m else "unknown"
    except OSError:
        return "unknown"


def config_list():
    jev, gemini = (source_model(f, k) for f, k in SHARED_MODELS)
    out = []
    for key, cfg in configs.CONFIGS.items():
        check = f"{cfg['check']} (backup {gemini})" if cfg["check"] else gemini
        out.append({"id": key, "label": cfg["label"], "tag": cfg["tag"], "about": cfg["about"],
                    "models": [["Agent 1 reads part numbers", cfg["read"]],
                               ["Photo check", check],
                               ["Agent 2 matches on eBay", jev]]})
    return out


def name_models():
    """Agent 3's name models for the page's drop-down, default first."""
    return [[m, lab + (" (Default)" if m == assemble.MODEL else "")] for m, lab in assemble.NAME_MODELS.items()]


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
        self.config = configs.DEFAULT   # setup of the current/last run
        self.vehicle = ""
        self.question = None      # {"id", "ask", "choices", "kind"} while the run waits for an answer
        self.stop = None          # why the run stopped, when it says

    def add(self, line):
        # The page no longer shows the log, so the Terminal running `bear ui` is where it is read.
        self.log.append(line)
        print(line, flush=True)


LOCK = threading.Lock()
JOB = Job()
ASKED = itertools.count(1)    # question ids, so the page never answers one twice
NAME_MODEL = assemble.MODEL   # the name model that last worked; kept until `bear ui` closes


def new_job(name):
    name = re.sub(r"[^\w .-]", "_", name).strip(" .") or "photos"
    folder = JOBS / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir(parents=True, exist_ok=True)
    with LOCK:
        if JOB.state == "running":
            raise RuntimeError("A run is in progress.")
        JOB.__init__()
        JOB.id, JOB.folder, JOB.name = uuid.uuid4().hex, folder, name
        JOB.add(f"Folder selected: {name}")
        JOB.add(f"Saving photos to {folder}")
    return JOB.id


def run_pipeline(vehicle, config, names_only=False):
    """A full run, or (names_only) finish the names of the last run that stopped."""
    with LOCK:
        out = JOB.out if names_only else JOB.folder / f"bear-results-{time.strftime('%Y%m%d-%H%M%S')}"
        JOB.state, JOB.step, JOB.detail, JOB.out, JOB.cost = "running", 0, "", out, None
        JOB.config, JOB.vehicle, JOB.question, JOB.stop = config, vehicle, None, None
        JOB.add(f"{'Finishing names' if names_only else 'Started'}: {vehicle} "
                f"(models: {configs.CONFIGS[config]['label']}, names: {assemble.label(NAME_MODEL)})")
        JOB.proc = subprocess.Popen(
            [sys.executable, "-u", str(RUN_PY), str(JOB.folder), vehicle, str(out)] + (["--names-only"] if names_only else []),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(REPO),
            env={**os.environ, "BEAR_CONFIG": config, "BEAR_WEB_ASK": "1", "BEAR_NAME_MODEL": NAME_MODEL})
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
        JOB.question = None
        if rc == 0 and (out / "results.xlsx").exists():
            JOB.state, JOB.step, JOB.detail = "done", len(STEPS), ""
            JOB.add("xlsx file created")
        else:
            JOB.state = "failed"
            JOB.add(f"BEAR run failed (exit code {rc}). See the messages above.")


def handle_line(line):
    global NAME_MODEL
    if not line:
        return
    with LOCK:
        if line.startswith(assemble.WEB_MARK.strip()):
            try:
                msg = json.loads(line[len(assemble.WEB_MARK):])
            except ValueError:
                msg = {}
            if msg.get("ask"):
                JOB.question = {"id": next(ASKED), **{k: msg.get(k) for k in ("ask", "choices", "kind")}}
                JOB.detail = WAITING
                JOB.add(f"Question: {msg['ask']}")
            if msg.get("model") in assemble.NAME_MODELS:
                NAME_MODEL = msg["model"]
                JOB.add(f"Name model approved: {assemble.label(NAME_MODEL)}")
            if msg.get("stop"):
                JOB.stop = msg["stop"]
            return
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


def can_finish():
    """A stopped run whose photo reads and eBay results are saved, so only the names are left."""
    return JOB.state == "failed" and bool(JOB.out) and (JOB.out / "agent2_results.md").exists()


def status(since):
    with LOCK:
        res = None
        if JOB.state == "done" and JOB.out:
            res = {"path": str(JOB.out / "results.xlsx"), "cost": JOB.cost, **summary(JOB.out)}
        stop, finish = JOB.stop, can_finish()
        if stop and finish:  # the Results section says the work is saved and offers Finish names
            stop = stop.split("The photo reads and eBay results are saved")[0].strip() or None
        return {"version": version(), "job": JOB.id, "folder": JOB.name, "state": JOB.state,
                "step": JOB.step, "detail": JOB.detail, "steps": STEPS,
                "log": JOB.log[since:], "logLength": len(JOB.log), "results": res,
                "canOpen": bool(shutil.which("open")), "configs": config_list(), "config": JOB.config,
                "nameModels": name_models(), "nameModel": NAME_MODEL,
                "question": JOB.question, "stop": stop, "canFinish": finish}


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
        global NAME_MODEL
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
        if path in ("/api/run", "/api/finish"):
            vehicle = " ".join(str(data.get("vehicle") or "").split())
            config = str(data.get("config") or configs.DEFAULT)
            name_model = str(data.get("nameModel") or NAME_MODEL)
            if config not in configs.CONFIGS:
                return self.fail(400, "Unknown model setup.")
            if name_model not in assemble.NAME_MODELS:
                return self.fail(400, "Unknown name model.")
            if path == "/api/finish":
                with LOCK:
                    if data.get("job") != JOB.id or not can_finish():
                        return self.fail(409, "There are no saved results to finish.")
                    vehicle, config, NAME_MODEL = JOB.vehicle, JOB.config, name_model
                run_pipeline(vehicle, config, names_only=True)
                return self.send(200, {"ok": True})
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
            with LOCK:
                NAME_MODEL = name_model
            run_pipeline(vehicle, config)
            return self.send(200, {"ok": True})
        if path == "/api/answer":
            key = str(data.get("key") or "")
            with LOCK:
                q = JOB.question
                if not q or q["id"] != data.get("id") or key not in [k for k, _ in q["choices"]]:
                    return self.fail(409, "That question has already been answered.")
                JOB.question, JOB.detail = None, ""
                JOB.add(f"Answer: {dict(q['choices'])[key]}")
                try:
                    JOB.proc.stdin.write(f"{key}\n".encode())
                    JOB.proc.stdin.flush()
                except OSError:
                    return self.fail(409, "The run has already stopped.")
            return self.send(200, {"ok": True})
        if path == "/api/reveal":
            with LOCK:
                p = JOB.out / "results.xlsx" if JOB.state == "done" and JOB.out else None
            if not p or not p.exists() or not shutil.which("open"):
                return self.fail(404, "No results to show.")
            subprocess.Popen(["open", "-R", str(p)])
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
