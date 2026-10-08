# Legacy code

Code BEAR no longer runs. It's kept here for reference while the repo is cleaned up.
Nothing in `bear2/`, `bin/` or the web page imports from this folder.

| File | What it was | Why it was removed |
|---|---|---|
| `mechanical_name_clean.py` | The backup part-name cleaner (`safe_name`) from `bear2/assemble.py` | It wrote messy names such as "Mitsubishi Shogun Pajero . Relay Omron" whenever the name model failed (issue 19). BEAR now stops and asks instead. |
