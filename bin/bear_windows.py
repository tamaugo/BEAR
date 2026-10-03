"""bear for Windows: the BEAR 0.2 launcher behind bin/bear.cmd (and the BEAR desktop shortcut).

Does on Windows what bin/bear does on the Mac (the Mac never uses this file):
  bear                       interactive: asks for photo folder + vehicle
  bear <folder> "<vehicle>"  non-interactive run
  bear ui                    open the BEAR page in your browser
  bear keys                  type the three API keys once (saved in the .env file)
  bear check / update / version / help

Keys live in <repo>/.env (gitignored). They are loaded into the pipeline's environment and
never printed. Every Python process it starts runs in UTF-8 mode (PYTHONUTF8=1): Windows
would otherwise write the result files as cp1252 and an eBay title like "Škoda ✅" would
crash the run or stop results.xlsx being built.

Standard library only: it must run on a bare Python before .venv exists.
"""
import getpass, os, re, shutil, subprocess, sys, time, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
VENV = REPO / ".venv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
ENV_FILE = REPO / ".env"
CRED_VARS = ("OPENROUTER_API_KEY", "EBAY_APP_ID", "EBAY_CERT_ID")
CRED_LABELS = {"OPENROUTER_API_KEY": "OpenRouter API key", "EBAY_APP_ID": "eBay App ID",
               "EBAY_CERT_ID": "eBay Cert ID"}
PHOTO_EXT = (".jpg", ".jpeg", ".png")
MIN_PY = (3, 10)
RELEASES_URL = "https://github.com/tamaugo/BEAR/releases"


def version():
    try:
        return (REPO / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def usage():
    return f"""BEAR {version()} for Windows - eBay part pricing

Usage:
  bear                       interactive: asks for photo folder + vehicle
  bear <folder> "<vehicle>"  non-interactive run
  bear ui                    open the BEAR page in your browser
  bear keys                  type the three API keys (saved in the .env file)
  bear check                 check python, Pillow and keys
  bear update                get the latest version and refresh dependencies
  bear version | --version   show version
  bear help | -h | --help    this help

Results are written to <folder>\\bear-results-YYYYmmdd-HHMMSS\\results.xlsx
(photos BEAR could not price get shaded eBay image-search suggestions directly underneath)
Per-run spend cap: BEAR_RUN_CAP_USD (default 1.00; PowerShell: $env:BEAR_RUN_CAP_USD=2)"""


# ---- drag-and-drop paths ----
def clean_path(raw):
    """A folder dragged into a Windows terminal arrives as C:\\x, "C:\\x y", 'C:\\x y' or,
    in PowerShell, & 'C:\\x y'. Backslashes are path separators here, never escapes."""
    p = raw.strip()
    if p.startswith("& "):
        p = p[2:].strip()
    if len(p) >= 2 and p[0] == p[-1] and p[0] in "'\"":
        p = p[1:-1]
    if p.lower().startswith("file:///"):
        p = urllib.parse.unquote(p[8:]).replace("/", "\\")
    if len(p) > 3 and p[-1] in "\\/":
        p = p.rstrip("\\/")
    return p


def has_images(folder):
    try:
        return any(e.is_file() and os.path.splitext(e.name)[1].lower() in PHOTO_EXT
                   for e in os.scandir(folder))
    except OSError:
        return False


# ---- keys (.env) ----
def read_env_file(path=None):
    """KEY=VALUE lines. Tolerates the byte-order mark Notepad adds and UTF-16 files that
    PowerShell's `>` writes."""
    try:
        data = Path(path or ENV_FILE).read_bytes()
    except OSError:
        return {}
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16")
    else:
        text = data.decode("utf-8-sig", errors="replace")
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def is_real(value):
    """Empty values and .env.example placeholders like sk-or-... do not count."""
    return bool(value) and not value.endswith("...")


def write_env_keys(values, path=None):
    """Set KEY=VALUE for each key, keeping every other line of .env as it was."""
    path = Path(path or ENV_FILE)
    lines = []
    if path.exists():
        data = path.read_bytes()
        text = data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
    done = set()
    for i, line in enumerate(lines):
        k = line.partition("=")[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and k in values:
            lines[i] = f"{k}={values[k]}"
            done.add(k)
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_creds(env):
    """Environment wins (like the Mac); otherwise take the key from .env."""
    file_vals = read_env_file()
    for v in CRED_VARS:
        if not is_real(env.get(v, "").strip()) and is_real(file_vals.get(v, "")):
            env[v] = file_vals[v]
    return env


def missing_creds(env):
    return [v for v in CRED_VARS if not is_real(env.get(v, "").strip())]


def do_keys():
    print("Type each key and press Enter. Nothing shows while you type (that is normal).")
    print("Press Enter on its own to keep a key that is already saved.\n")
    have = load_creds({})
    new = {}
    for v in CRED_VARS:
        state = "saved" if v in have else "not saved yet"
        val = getpass.getpass(f"{CRED_LABELS[v]} ({state}): ").strip()
        if val:
            new[v] = val
    if new:
        write_env_keys(new)
        print(f"\nSaved {len(new)} key(s) to {ENV_FILE}")
    miss = missing_creds(load_creds({}))
    if miss:
        print("Still missing: " + ", ".join(CRED_LABELS[v] for v in miss))
        return 1
    print("All three keys are saved.")
    return 0


def require_creds(env):
    load_creds(env)
    miss = missing_creds(env)
    if not miss:
        return env
    print("BEAR is missing keys: " + ", ".join(CRED_LABELS[v] for v in miss), file=sys.stderr)
    if sys.stdin and sys.stdin.isatty():
        ans = input("Type them now? [Y/n] ").strip().lower()
        if ans in ("", "y", "yes"):
            print()
            do_keys()
            load_creds(env)
            if not missing_creds(env):
                print()
                return env
    print("Run:  bear keys   (it saves them in the .env file), then try again.", file=sys.stderr)
    sys.exit(1)


# ---- python env ----
def pillow_ok():
    return VPY.exists() and subprocess.run([str(VPY), "-c", "import PIL"],
                                           capture_output=True).returncode == 0


def pip_install():
    r = subprocess.run([str(VPY), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                        "-r", str(REPO / "requirements.txt")])
    if r.returncode:
        print("Installing BEAR's Python packages failed (see above). Check the internet "
              "connection and run: bear update", file=sys.stderr)
        sys.exit(1)


def ensure_env():
    if pillow_ok():
        return
    print("Setting up BEAR's Python environment (first run only, one minute)...", flush=True)
    if not VPY.exists():
        if sys.version_info < MIN_PY:
            print(f"BEAR needs Python {MIN_PY[0]}.{MIN_PY[1]} or newer.", file=sys.stderr)
            sys.exit(1)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    pip_install()


def documents_dir():
    """The real Documents folder, which Windows often moves into OneDrive."""
    if os.name == "nt":
        try:
            import ctypes, uuid
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                            ("d4", ctypes.c_ubyte * 8)]
            u = uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7")  # FOLDERID_Documents
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                try:
                    return Path(p.value)
                finally:
                    ctypes.windll.ole32.CoTaskMemFree(p)
        except Exception:
            pass
    return Path.home() / "Documents"


def child_env():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("BEAR_UI_JOBS_DIR", str(documents_dir() / "BEAR"))
    return env


def wait(proc):
    """Ctrl+C reaches every program in the window; let the child stop itself."""
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue


def open_file(path):
    try:
        os.startfile(str(path))  # Windows: opens in Excel (or whatever opens .xlsx)
    except (AttributeError, OSError):
        pass


# ---- subcommands ----
def do_check():
    bad = False
    print(f"BEAR {version()} (Windows)")
    print(f"python:  OK ({sys.version.split()[0]})" if sys.version_info >= MIN_PY
          else f"python:  TOO OLD ({sys.version.split()[0]}; install Python 3.12 from python.org)")
    bad |= sys.version_info < MIN_PY
    if VPY.exists():
        print(f"venv:    OK ({VENV})")
    else:
        print("venv:    MISSING (created on first run)"); bad = True
    if pillow_ok():
        print("Pillow:  OK")
    else:
        print("Pillow:  MISSING (installed on first run)"); bad = True
    env = load_creds(dict(os.environ))
    for v in CRED_VARS:
        if v not in missing_creds(env):
            print(f"{v}: present")
        else:
            print(f"{v}: MISSING (run: bear keys)"); bad = True
    print(f"VERSION: {version()}")
    if bad:
        print("Check: problems found.")
        return 1
    print("Check: all good.")
    return 0


def do_update():
    if not (REPO / ".git").exists() or not shutil.which("git"):
        print("This copy of BEAR was not installed with git, so it can't update itself.")
        print(f"Download the latest 'for Windows' zip from {RELEASES_URL}")
        print("and unzip it over this folder (your .env keys file is kept).")
        return 1
    r = subprocess.run(["git", "-C", str(REPO), "pull", "--ff-only"])
    if r.returncode:
        return r.returncode
    if not VPY.exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    pip_install()
    print(f"BEAR is now version {version()}.")
    return 0


def do_run(folder, vehicle):
    if not os.path.isdir(folder):
        print(f"Folder not found: {folder}", file=sys.stderr); return 1
    if not has_images(folder):
        print(f"No .jpg/.jpeg/.png photos found directly inside: {folder}", file=sys.stderr); return 1
    if not vehicle:
        print("Vehicle description is empty.", file=sys.stderr); return 1
    ensure_env()
    env = require_creds(child_env())
    out = Path(folder) / f"bear-results-{time.strftime('%Y%m%d-%H%M%S')}"
    rc = wait(subprocess.Popen([str(VPY), str(REPO / "bear2" / "run.py"), str(folder), vehicle, str(out)], env=env))
    if rc:
        print(f"\nBEAR run failed (exit code {rc}). See the messages above.", file=sys.stderr)
        return rc
    print(f"\nResults: {out / 'results.xlsx'}")
    if (out / "results.xlsx").exists():
        open_file(out / "results.xlsx")
    return 0


def do_ui(args):
    ensure_env()
    env = require_creds(child_env())
    return wait(subprocess.Popen([str(VPY), str(REPO / "bear2" / "ui" / "server.py"), *args], env=env))


def do_interactive():
    print(f"BEAR {re.sub(r'[.]0$', '', version())} - eBay part pricing")
    try:
        folder = clean_path(input("Drag the photo folder here and press Enter: "))
        vehicle = " ".join(input("Vehicle (e.g. HYUNDAI I40 MK1 SEDAN 2015 1.7 DIESEL): ").split())
    except (EOFError, KeyboardInterrupt):
        print()
        return 1
    return do_run(folder, vehicle)


# ---- install (run by install.cmd) ----
def add_bin_to_user_path():
    """Adds bin to the user's PATH (no admin needed). Returns True if it changed."""
    import ctypes, winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            cur, kind = winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            cur, kind = "", winreg.REG_EXPAND_SZ
        parts = [p for p in cur.split(";") if p]
        want = os.path.normcase(str(BIN)).rstrip("\\")
        if any(os.path.normcase(os.path.expandvars(p)).rstrip("\\") == want for p in parts):
            return False
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            kind = winreg.REG_EXPAND_SZ
        winreg.SetValueEx(k, "Path", 0, kind, ";".join(parts + [str(BIN)]))
    # tell Explorer so new windows see the new PATH
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 0x2, 5000,
                                             ctypes.byref(ctypes.c_ulong()))
    return True


def make_shortcut():
    """BEAR on the desktop: opens a window running `bear ui`, which opens the page."""
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"
    icon = REPO / "bin" / "bear.ico"
    ps = ("$d=[Environment]::GetFolderPath('Desktop');"
          "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'BEAR.lnk'));"
          f"$s.TargetPath={q(BIN / 'start-bear.cmd')};$s.WorkingDirectory={q(REPO)};"
          "$s.Description='Open BEAR (eBay part pricing)';"
          + (f"$s.IconLocation={q(icon)};" if icon.exists() else "")
          + "$s.Save();Join-Path $d 'BEAR.lnk'")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def do_install():
    if os.name != "nt":
        print("install is for Windows; on a Mac use ./install.sh", file=sys.stderr)
        return 1
    print(f"Installing BEAR {version()} for Windows into {REPO}\n")
    if sys.version_info < MIN_PY:
        print(f"BEAR needs Python {MIN_PY[0]}.{MIN_PY[1]} or newer.", file=sys.stderr)
        return 1
    ensure_env()
    print("Python packages: OK")
    try:
        changed = add_bin_to_user_path()
        print("Added BEAR to your PATH (open a NEW terminal to use the 'bear' command)." if changed
              else "PATH: OK")
    except Exception as e:
        print(f"Could not add BEAR to PATH ({type(e).__name__}); the desktop shortcut still works.")
    lnk = make_shortcut()
    print(f"Desktop shortcut: {lnk}" if lnk else "Could not create the desktop shortcut.")
    if missing_creds(load_creds(dict(os.environ))) and sys.stdin and sys.stdin.isatty():
        print("\nNow the three API keys (saved in the .env file inside the BEAR folder).")
        do_keys()
    print()
    do_check()
    print("\nDone. Double-click BEAR on your desktop to start.")
    return 0


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "":
        return do_interactive()
    if cmd == "check":
        return do_check()
    if cmd == "ui":
        return do_ui(argv[1:])
    if cmd == "keys":
        return do_keys()
    if cmd == "update":
        return do_update()
    if cmd == "install":
        return do_install()
    if cmd in ("version", "--version", "-V"):
        print(f"BEAR {version()}")
        return 0
    if cmd in ("help", "-h", "--help"):
        print(usage())
        return 0
    if cmd == "__clean-path":
        print(clean_path(argv[1] if len(argv) > 1 else ""))
        return 0
    if len(argv) != 2:
        print(usage(), file=sys.stderr)
        return 2
    return do_run(clean_path(argv[0]), " ".join(argv[1].split()))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
