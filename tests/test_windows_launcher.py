#!/usr/bin/env python3
"""Offline tests for bin/bear_windows.py (the Windows launcher). Stdlib only.
Runs on any OS; the Windows-only checks run only on Windows.

usage: python tests/test_windows_launcher.py
"""
import os, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import bear_windows as bw  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print(("PASS: " if cond else "FAIL: ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILURES.append(name)


def test_clean_path():
    cases = {
        r"C:\Users\Bob\Photos": r"C:\Users\Bob\Photos",
        r'"C:\Users\Bob Smith\Job Photos"': r"C:\Users\Bob Smith\Job Photos",        # cmd drag-and-drop
        r"'C:\Users\Bob Smith\Job Photos'": r"C:\Users\Bob Smith\Job Photos",        # PowerShell
        r"& 'C:\Users\Bob Smith\Job Photos'": r"C:\Users\Bob Smith\Job Photos",      # PowerShell, pasted
        "  C:\\Photos\\  ": r"C:\Photos",
        "C:\\": "C:\\",
        r"\\server\share\Photos": r"\\server\share\Photos",
        "file:///C:/Users/Bob%20Smith/Photos": r"C:\Users\Bob Smith\Photos",
        r"C:\Users\Zoë\Škoda (2)": r"C:\Users\Zoë\Škoda (2)",
    }
    for raw, want in cases.items():
        got = bw.clean_path(raw)
        check(f"clean_path {raw!r}", got == want, f"got {got!r}")


def test_env_file():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".env"
        # Notepad-style BOM + an unrelated line + the .env.example placeholder
        p.write_bytes("\ufeff# my keys\nOPENROUTER_API_KEY=sk-or-...\nJEV_MODEL=typesafe/jev-1.13\n".encode("utf-8"))
        vals = bw.read_env_file(p)
        check("BOM does not break the first key", "OPENROUTER_API_KEY" in vals, str(vals))
        check("placeholder sk-or-... is not a key", not bw.is_real(vals["OPENROUTER_API_KEY"]))
        bw.write_env_keys({"OPENROUTER_API_KEY": "sk-or-v1-abc", "EBAY_APP_ID": "app"}, p)
        text = p.read_text(encoding="utf-8")
        check("keys written, other lines kept", "OPENROUTER_API_KEY=sk-or-v1-abc" in text
              and "EBAY_APP_ID=app" in text and "JEV_MODEL=typesafe/jev-1.13" in text and "# my keys" in text, text)
        check("written without BOM", not p.read_bytes().startswith(b"\xef\xbb\xbf"))
        p.write_bytes("EBAY_CERT_ID=PRD-xyz\r\n".encode("utf-16"))  # PowerShell 5 `>` writes UTF-16
        check("UTF-16 .env is read", bw.read_env_file(p).get("EBAY_CERT_ID") == "PRD-xyz")


def test_load_creds():
    with tempfile.TemporaryDirectory() as d:
        old = bw.ENV_FILE
        bw.ENV_FILE = Path(d) / ".env"
        try:
            bw.write_env_keys({"OPENROUTER_API_KEY": "file-key", "EBAY_APP_ID": "file-app"}, bw.ENV_FILE)
            env = bw.load_creds({"OPENROUTER_API_KEY": "env-key"})
            check("environment beats .env", env["OPENROUTER_API_KEY"] == "env-key")
            check(".env fills the rest", env["EBAY_APP_ID"] == "file-app")
            check("missing key reported", bw.missing_creds(env) == ["EBAY_CERT_ID"], str(bw.missing_creds(env)))
        finally:
            bw.ENV_FILE = old


def test_has_images():
    with tempfile.TemporaryDirectory() as d:
        check("empty folder has no photos", not bw.has_images(d))
        (Path(d) / "sub").mkdir()
        (Path(d) / "sub" / "a.jpg").write_bytes(b"x")
        check("photos in subfolders do not count", not bw.has_images(d))
        (Path(d) / "IMG_1.JPG").write_bytes(b"x")
        check("upper-case .JPG counts", bw.has_images(d))
    check("missing folder has no photos", not bw.has_images(os.path.join(d, "nope")))


def test_child_env():
    env = bw.child_env()
    check("pipeline runs in UTF-8 mode", env.get("PYTHONUTF8") == "1")
    check("jobs folder set", bool(env.get("BEAR_UI_JOBS_DIR")))
    if os.name == "nt":
        docs = bw.documents_dir()
        check("Documents folder found via Windows", docs.is_dir(), str(docs))
        check("venv python is Scripts\\python.exe", bw.VPY.parts[-2:] == ("Scripts", "python.exe"))


def test_cli():
    check("version", bw.main(["version"]) == 0)
    check("help", bw.main(["help"]) == 0)
    check("wrong number of arguments", bw.main(["a", "b", "c"]) == 2)
    check("run refuses a missing folder", bw.main(["Z:\\no\\such\\folder", "FORD FOCUS"]) == 1)


if __name__ == "__main__":
    for t in (test_clean_path, test_env_file, test_load_creds, test_has_images, test_child_env, test_cli):
        t()
    print(f"\n{len(FAILURES)} failed" if FAILURES else "\nall passed")
    sys.exit(1 if FAILURES else 0)
