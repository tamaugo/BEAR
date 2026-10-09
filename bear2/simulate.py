"""Simulated BEAR run for the web page's dev mode: no network calls, no credits spent.

A drop-in for run.py (same arguments and output). The photo reads, eBay results and name
models are fake; everything after them is real: the first-line check and its questions
(assemble.verify / web_ask), the stop-and-ask on a failed name model, the finished lines,
the validator and results.xlsx. BEAR_SIM picks what goes wrong:

  ok                everything works
  wrong-line        the first name model gives a wrong line (reject it, pick another)
  all-wrong         every name model gives a wrong line (BEAR-N04)
  check-rate-limit  the first name model is rate limited at the first-line check
  rate-limit        the first name model is rate limited in the full run (BEAR-N01)
  no-response       the first name model doesn't respond in the full run (BEAR-N02)
  unusable          the first name model gives unusable names in the full run (BEAR-N03)
  crash             the run crashes while pricing on eBay (BEAR-R01)

"The first name model" is the one the run starts with (the page's Model name drop-down). It is
saved in the results folder, so Finish names later still treats that model as the faulty one.

usage: BEAR_SIM=rate-limit python3 bear2/simulate.py <photo_dir> "<VEHICLE STRING>" <out_dir> [--names-only]
"""
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import assemble

SCENARIOS = ["ok", "wrong-line", "all-wrong", "check-rate-limit", "rate-limit", "no-response", "unusable", "crash"]
SCENARIO = os.environ.get("BEAR_SIM") if os.environ.get("BEAR_SIM") in SCENARIOS else "ok"
PAUSE = float(os.environ.get("BEAR_SIM_PAUSE", "0.15"))   # seconds per fake step, so progress is visible
FIRST_FILE = "sim_first_model.txt"
FIRST = assemble.start_model()   # replaced by the saved one on Finish names (main)

# Fake Agent 2 results: (photo, part number, eBay title, sell price, clean name, wrong name).
# None as the part number = no eBay listing (a FAILED row).
PARTS = [
    ("IMG_0001.jpg", "1810A001", "MITSUBISHI SHOGUN 3.2 DID STARTER MOTOR 1810A001 BOSCH GENUINE", "45.99",
     "Starter Motor", "Shogun Starter Motor Bosch"),
    ("IMG_0002-OSF.jpg", "8301A123", "MITSUBISHI SHOGUN MK4 FRONT RIGHT HEADLIGHT 8301A123", "89.99",
     "Headlight", "Shogun Mk4 Headlight Genuine"),
    ("IMG_0003.jpg", "MR578042", "MITSUBISHI PAJERO SHOGUN ABS PUMP MR578042 2007", "64.99",
     "Abs Pump", "Pajero Abs Pump 2007"),
    ("IMG_0004.jpg", None, "", "", "", ""),
    ("IMG_0005-NSR.jpg", "5730A057", "SHOGUN 2007 REAR LEFT WINDOW REGULATOR MOTOR 5730A057", "29.99",
     "Window Regulator Motor", "Shogun Window Regulator Motor 2007"),
    ("IMG_0006.jpg", "MN132987", "MITSUBISHI SHOGUN 3.2 DI-D ECU ENGINE CONTROL UNIT MN132987", "119.99",
     "Engine Control Unit", "Shogun 3.2 Di-D Engine Control Unit"),
    ("IMG_0007.jpg", "8651A034", "MITSUBISHI SHOGUN 2007 RADIATOR COOLING FAN 8651A034 OEM", "39.99",
     "Radiator Cooling Fan", "Shogun Radiator Cooling Fan Oem"),
]
NULLS = ["IMG_0008-NULL.jpg"]


def say(text, end="\n"):
    print(text, end=end, file=sys.stderr, flush=True)


def counter(label, n):
    for i in range(1, n + 1):
        time.sleep(PAUSE)
        say(f"\r{label} {i}/{n}", end="\n" if i == n else "")


def fake_clean_names(rows, model=assemble.MODEL, attempts=None):
    """Stands in for assemble.clean_names: same answers and failures, no API call."""
    time.sleep(PAUSE * 2)
    first = FIRST
    check = len(rows) == 1   # the first-line check cleans one row; the full run cleans the rest
    lab = assemble.label(model)
    if model == first and SCENARIO == "check-rate-limit" and check or model == first and SCENARIO == "rate-limit" and not check:
        raise assemble.NamesFailed(f'{lab} is unavailable: OpenRouter HTTP 429: {{"error":{{"message":'
                                   f'"Rate limit exceeded: {model} is temporarily rate-limited upstream","code":429}}}} (simulated)')
    if model == first and SCENARIO == "no-response" and not check:
        raise assemble.NamesFailed(f"{lab} is unavailable: <urlopen error timed out> (simulated)")
    if model == first and SCENARIO == "unusable" and not check:
        f = next(iter(rows.values()))
        raise assemble.NamesFailed(f"{lab} gave a name BEAR can't use for {f[0]}: 'Relay 25252701' (simulated)")
    wrong = SCENARIO == "all-wrong" or SCENARIO == "wrong-line" and model == first
    by_photo = {p[0]: p[5 if wrong else 4] for p in PARTS}
    return {k: by_photo[f[0]] for k, f in rows.items()}


assemble.clean_names = fake_clean_names


def agent2_line(p):
    if p[1] is None:
        return f"{p[0]} | FAILED | Agent 2 | No eBay Listing Found"
    return f"{p[0]} | {p[1]} | {p[2]} | {p[3]} | https://www.ebay.co.uk/itm/2000000000{PARTS.index(p) + 1:02d}"


def main():
    global FIRST
    out, vehicle = Path(sys.argv[3]), sys.argv[2]
    out.mkdir(parents=True, exist_ok=True)
    saved = out / FIRST_FILE
    if saved.exists():
        FIRST = saved.read_text().strip()
    else:
        saved.write_text(FIRST)
    ask = assemble.asker()
    say(f"SIMULATED RUN ({SCENARIO}): fake photos, eBay results and name models. No credits are spent.")
    if "--names-only" in sys.argv:
        print(assemble.main(out, vehicle, ask, assemble.start_model() if ask else None))
        return
    say(f"{len(PARTS)} photos to price ({len(NULLS)} NULL). This takes a few seconds (simulated).")
    if ask:
        say("Checking the first part before the full run ...")
        time.sleep(PAUSE * 3)
        f = assemble.parse_row(agent2_line(PARTS[0]))
        model, name = assemble.verify(vehicle, f, ask, assemble.start_model())
        assemble.save_check(out, f[0], model, name)
    counter("Reading part numbers", len(PARTS) - 1)
    if SCENARIO == "crash":
        time.sleep(PAUSE * 3)
        raise RuntimeError("simulated crash while pricing on eBay (BEAR_SIM=crash)")
    counter("Pricing on eBay", len(PARTS) - 1)
    (out / "agent2_results.md").write_text("\n".join(agent2_line(p) for p in PARTS) + "\n")
    (out / "null_files.txt").write_text("\n".join(NULLS))
    print(assemble.main(out, vehicle, ask))
    print(f"\nrun cost $0.0000 for {len(PARTS)} parts (simulated, no credits spent)")


if __name__ == "__main__":
    try:
        main()
    except assemble.Stop as e:
        assemble.stop_exit(e)
