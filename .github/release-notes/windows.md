BEAR {V} for **Windows 10 and Windows 11** — eBay part pricing.

**Install**
1. Install Python 3.12 (once): open PowerShell and run `winget install -e --id Python.Python.3.12`
   (or download it from python.org and tick **Add python.exe to PATH**).
2. Download `BEAR-{V}-windows.zip` below, right-click it > **Extract All**, and put the `bear` folder in your user folder (for example `C:\Users\<you>\bear`). Avoid Desktop or OneDrive folders.
3. Open the `bear` folder and double-click **install.cmd**. If Windows shows "Windows protected your PC", click **More info > Run anyway** (the file came from the internet).
4. Type the three keys when asked (OpenRouter API key, eBay App ID, eBay Cert ID). They are saved in the `.env` file inside the `bear` folder.

**Use**
- Double-click **BEAR** on your desktop. A window opens (keep it open; close it to stop BEAR) and the BEAR page opens in your browser.
- Or in a terminal: `bear` (drag the photo folder in), `bear <folder> "<vehicle>"`, `bear ui`, `bear check`, `bear keys`.

Results go to `<photo folder>\bear-results-YYYYmmdd-HHMMSS\results.xlsx` and open automatically. Full guide: WINDOWS.md in the zip.
