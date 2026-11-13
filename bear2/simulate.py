"""Simulated BEAR run for the Discord bot's dev mode (BEAR_SIM): no network calls, no credits spent.

A drop-in for run.py (same arguments and output). The photo reads, eBay results and name
models are fake; everything after them is real: the stop on a failed name model, the finished
lines, the validator and results.xlsx. BEAR_SIM picks what goes wrong:

  ok                everything works
  rate-limit        the name model is rate limited (BEAR-N01)
  no-response       the name model doesn't respond (BEAR-N02)
  unusable          the name model gives unusable names (BEAR-N03)
  crash             the run crashes while pricing on eBay (BEAR-R01)
  flagged           the final check flags a row (BEAR-V01, owner only; the spreadsheet is posted)
  outage            eBay is down for most parts (BEAR-E01; the spreadsheet is posted)
  names-once        the name model fails once, then the bot's names-only retry works

usage: BEAR_SIM=rate-limit python3 bear2/simulate.py <photo_dir> "<VEHICLE STRING>" <out_dir> [--names-only]
"""
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import assemble

SCENARIOS = ["ok", "rate-limit", "no-response", "unusable", "crash", "flagged", "outage", "names-once"]
SCENARIO = os.environ.get("BEAR_SIM") if os.environ.get("BEAR_SIM") in SCENARIOS else "ok"
PAUSE = float(os.environ.get("BEAR_SIM_PAUSE", "0.15"))   # seconds per fake step, so progress is visible
# Fake Agent 2 results: (photo, part number, eBay title, sell price, clean name, a wrong name, unused
# since the Terminal/web page first-line check was removed).
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


def say(text, end="\n"):
    print(text, end=end, file=sys.stderr, flush=True)


def counter(label, n):
    for i in range(1, n + 1):
        time.sleep(PAUSE)
        say(f"\r{label} {i}/{n}", end="\n" if i == n else "")


def fake_clean_names(rows, model=assemble.MODEL, attempts=None):
    """Stands in for assemble.clean_names: same answers and failures, no API call."""
    time.sleep(PAUSE * 2)
    lab = assemble.label(model)
    if SCENARIO == "rate-limit":
        raise assemble.NamesFailed(f'{lab} is unavailable: OpenRouter HTTP 429: {{"error":{{"message":'
                                   f'"Rate limit exceeded: {model} is temporarily rate-limited upstream","code":429}}}} (simulated)')
    if SCENARIO == "names-once" and "--names-only" not in sys.argv:
        raise assemble.NamesFailed(f"{lab} is unavailable: <urlopen error timed out> (simulated, only the first time)")
    if SCENARIO == "no-response":
        raise assemble.NamesFailed(f"{lab} is unavailable: <urlopen error timed out> (simulated)")
    if SCENARIO == "unusable":
        f = next(iter(rows.values()))
        raise assemble.NamesFailed(f"{lab} gave a name BEAR can't use for {f[0]}: 'Relay 25252701' (simulated)")
    by_photo = {p[0]: p[4] for p in PARTS}
    return {k: by_photo[f[0]] for k, f in rows.items()}


assemble.clean_names = fake_clean_names


def agent2_line(p):
    if SCENARIO == "flagged" and PARTS.index(p) == 1:   # a price the final check can't read
        return f"{p[0]} | {p[1]} | {p[2]} | 9886 | ?? | https://www.ebay.co.uk/itm/200000000002"
    if SCENARIO == "outage" and PARTS.index(p) > 0:   # eBay down for all but the first part
        return f"{p[0]} | FAILED | Agent 2 | eBay Lookup Unavailable"
    if p[1] is None:
        return f"{p[0]} | FAILED | Agent 2 | No eBay Listing Found"
    return f"{p[0]} | {p[1]} | {p[2]} | 9886 | {p[3]} | https://www.ebay.co.uk/itm/2000000000{PARTS.index(p) + 1:02d}"


def main():
    out, vehicle = Path(sys.argv[3]), sys.argv[2]
    out.mkdir(parents=True, exist_ok=True)
    say(f"SIMULATED RUN ({SCENARIO}): fake photos, eBay results and name models. No credits are spent.")
    if "--names-only" in sys.argv:
        print(assemble.main(out, vehicle))
        return
    say(f"{len(PARTS)} photos to price. This takes a few seconds (simulated).")
    counter("Reading part numbers", len(PARTS) - 1)
    if SCENARIO == "crash":
        time.sleep(PAUSE * 3)
        raise RuntimeError("simulated crash while pricing on eBay (BEAR_SIM=crash)")
    counter("Pricing on eBay", len(PARTS) - 1)
    (out / "agent2_results.md").write_text("\n".join(agent2_line(p) for p in PARTS) + "\n")
    print(assemble.main(out, vehicle))
    print(f"\nrun cost $0.0000 for {len(PARTS)} parts (simulated, no credits spent)")


if __name__ == "__main__":
    try:
        main()
    except assemble.Stop as e:
        assemble.stop_exit(e)
