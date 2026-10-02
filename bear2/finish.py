"""Run the UNCHANGED downstream chain on a bear2 run dir: Agent 3 (qwen3.8-flash, the
harness agent3-compiler.md prompt, thinking off) -> agent3_validator.py -> make_xlsx.py.
Then print each final part-info line next to the operator's line.

usage: python3 bear2/finish.py <run_dir> "<VEHICLE STRING>"
"""
import json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

ROOT = c.ROOT
PROMPT = ROOT / "harness/.pi/agents/agent3-compiler.md"
MODEL = "qwen/qwen3.8-flash"


def system_prompt():
    t = PROMPT.read_text()
    t = re.sub(r"^---.*?---\s*", "", t, count=1, flags=re.S)       # frontmatter
    return re.sub(r"<!--.*?-->", "", t, flags=re.S).strip()           # maintainer comments


def main(run_dir, vehicle):
    run = Path(run_dir)
    a2 = (run / "agent2_results.md").read_text()
    nulls = (run / "null_files.txt").read_text().strip() if (run / "null_files.txt").exists() else ""
    user = (f"Job inputs:\nVehicle string: {vehicle}\nNULL photos: {nulls or '(none)'}\n"
            f"Output path: ./output/agent3_results.txt\n\nAgent 2 results to process:\n{a2}")
    out, raw = c.chat(MODEL, [{"role": "system", "content": system_prompt()},
                              {"role": "user", "content": user}],
                      max_tokens=6000, extra={"reasoning": {"effort": "none", "exclude": True}}, tag="agent3")
    m = re.search(r"```(?:\w+)?\n(.*?)```", out, re.S)
    text = (m.group(1) if m else out).strip() + "\n"
    a3 = run / "agent3_results.txt"
    a3.write_text(text)
    v = subprocess.run([sys.executable, str(ROOT / "tools/agent3_validator.py"), str(a3), str(run / "agent2_results.md")],
                       capture_output=True, text=True)
    print(f"agent3 ${raw['usage'].get('cost', 0):.4f} | validator exit {v.returncode}")
    if v.returncode != 0:
        print(v.stdout[-1500:])
    x = subprocess.run([sys.executable, str(ROOT / "harness/make_xlsx.py"), str(a3), str(run / "results.xlsx")],
                       capture_output=True, text=True)
    print("xlsx:", (x.stdout or x.stderr).strip()[-200:])
    gt = {p["image"]: p for p in json.loads((ROOT / "tests/fixtures/ground_truth_hyundai_i40_2026-09-30.json").read_text())["parts"]}
    for line in a3.read_text().splitlines():
        f = [s.strip() for s in line.split("|")]
        if len(f) < 4:
            print("MALFORMED", line); continue
        img = f[3].split("/")[-1]
        g = gt.get(img) or gt.get(img.replace("_rot180", "").replace("_rot90", ""))
        op = f"{g['name']} {c.norm(g['part_number'])}" if g and g.get("name") else "(FAIL expected)"
        print(f"{img:18} {f[1]:>7} | {f[0].split(' - ', 1)[-1][:70]:70} || op: {op}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
