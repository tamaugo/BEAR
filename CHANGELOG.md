# BEAR version log

Newest first. The current version is in the `VERSION` file and shows in the top corner of the web page.

## 0.4

- **First-line check**: before the full run, BEAR shows the first finished line (part name and number with the car name). Approve it, or pick another name model and check again. Works in Terminal and on the web page (the output field and *Model name* drop-down above GO).
- **Name model switching**: Qwen 3.8 Flash (default), Gemini 3.1 Flash Lite or Claude Haiku 5.5. A model approved on the web page is kept for every run until `bear ui` is closed.
- **No silent fallback on part names**: if the name model is rate limited, not responding or gives unusable names, BEAR stops and asks (try again / change model / stop) instead of writing messy names. The old mechanical name cleaner moved to `legacy/`.
- **Error banner with codes**: web page errors drop down from the top with a code (`BEAR-N01` rate limited, `N02` not responding, `N03` unusable names, `N04` every model gave a wrong line, `R01` anything else), a plain message and the full error under *Info*.
- **Finish names later**: a run that stopped at the names can be finished from the page (*Finish names*) without redoing the photo reads or eBay lookups.
- **Dev mode**: a drop-down next to the version number runs simulated runs of every scenario (no credits spent) and the offline test suite (`tests/test_names_offline.py`, `tests/test_web_flow_offline.py`).

## 0.3

- **Model selection**: the web page has a *Model setup* drop-down. Pick one whole setup per run: *Default*, *Beta* or *Experimental*.
- **Increased cost savings**: the *Beta* setup uses OpenAI Luna Decisions for the photo check (Gemini stays as the backup), about 26% cheaper per job with the same results on the i40 test.
- **Experimental Claude Haiku 5.5**: the *Experimental* setup reads the photos with Claude Haiku 5.5. It is a test version (16-17 of 18 part numbers on the i40 test), so not for real jobs yet.

## 0.2

- Mac `bear` command and `bear ui` web page: read part numbers from photos, price them against live eBay UK listings, and write `results.xlsx`.
