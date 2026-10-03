## BEAR 0.2 — quick start (Windows 10 and Windows 11)

The Mac setup is described in README.md and is unchanged. This branch (`windows`) adds Windows support alongside it.

1. **Python 3.10 or newer** (once). In PowerShell: `winget install -e --id Python.Python.3.12`, or download it from python.org and tick **Add python.exe to PATH**.
2. **Get BEAR**, either:
   - the **"for Windows" zip** from the GitHub Releases page: right-click > Extract All, and put the `bear` folder in your user folder (`C:\Users\<you>\bear`), or
   - with git: `git clone -b windows https://github.com/tamaugo/BEAR.git %USERPROFILE%\bear` (then `bear update` keeps it current).

   Avoid the Desktop and OneDrive folders: OneDrive syncing thousands of small files slows BEAR down.
3. **Double-click `install.cmd`** in the `bear` folder. If Windows says "Windows protected your PC", click **More info > Run anyway**. The installer:
   - sets up BEAR's Python environment,
   - adds `bear` to your PATH,
   - puts a **BEAR** shortcut on your desktop,
   - asks for the three keys.
4. **Keys** are saved in `bear\.env` (never uploaded; it is gitignored). To change them later run `bear keys`, or edit `.env` in Notepad:
   ```
   OPENROUTER_API_KEY=...
   EBAY_APP_ID=...
   EBAY_CERT_ID=...
   ```

### Using it
- **Double-click BEAR on the desktop.** A window opens showing what BEAR is doing, and the BEAR page opens in your browser (same page as `bear ui` on the Mac). Keep the window open while you work; close it to stop BEAR.
- **Or from a terminal** (cmd or PowerShell, opened after installing):
  - `bear`: drag the photo folder into the window, press Enter, type the vehicle.
  - `bear <folder> "HYUNDAI I40 MK1 SEDAN 2015 1.7 DIESEL"`
  - `bear ui`, `bear check`, `bear keys`, `bear update`, `bear help`

**Results** go to `<photo folder>\bear-results-YYYYmmdd-HHMMSS\` and `results.xlsx` opens automatically. Photos added on the web page are saved under `Documents\BEAR\` (your real Documents folder, also when it is in OneDrive; change it with `BEAR_UI_JOBS_DIR`).

**Spend cap:** $1.00 per run. Change it in PowerShell with `$env:BEAR_RUN_CAP_USD=2; bear` (cmd: `set BEAR_RUN_CAP_USD=2` then `bear`).

### What is different from the Mac
| | Mac | Windows |
|---|---|---|
| Command | `bin/bear` (bash) | `bin\bear.cmd` → `bin\bear_windows.py` |
| Install | `./install.sh` | `install.cmd` |
| Keys | macOS Keychain | `.env` file |
| Start | `bear ui` in Terminal | BEAR desktop shortcut (or `bear ui`) |
| Results button | Show in Finder | Show in Explorer |

The pipeline code (`bear2/`) is shared. The Windows launcher runs it in Python's UTF-8 mode, because Windows otherwise writes text files in an older encoding and eBay titles like "Škoda ✅" would break the run.

The legacy 0.1 pi/tmux pipeline (`harness/`, `tools/bear.zsh`) is Mac-only.

### Checks
GitHub runs `.github/workflows/windows.yml` on every change to this branch, on Windows Server 2022 (Windows 10 generation) and 2025 (Windows 11 generation) with Python 3.10 and 3.13:
- install via `install.cmd`
- `bear.cmd` from cmd and PowerShell
- an offline pipeline run with non-English characters
- the web page server
- the validator tests

A Mac job confirms `bin/bear` and `install.sh` are identical to `main`.

### Releases
Pushing a tag like `release-v0.2.0` on this branch makes GitHub build two **draft** releases, "BEAR 0.2.0 for Mac" (from `main`) and "BEAR 0.2.0 for Windows" (from this branch). Review them under Releases and click **Publish**.
