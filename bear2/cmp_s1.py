"""Compare stage-1 vision outputs across models: is the ground-truth number among candidates?"""
import json, glob, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

GT = {p['image']: p for p in json.load(open(Path(__file__).parent.parent / "tests/fixtures/ground_truth_hyundai_i40_2026-09-30.json"))["parts"]}
SHOW = sys.argv[2:] or ["IMG_4866.JPEG", "IMG_4700.JPEG", "IMG_4784.JPEG", "IMG_4768.JPEG"]


def hit(g, v):
    texts = [c.norm(t) for x in v.get('candidates', []) for t in [x.get('text') or ''] + list(x.get('alt_readings') or [])]
    if g is None:
        return not texts
    ng = c.norm(g)
    joined = "".join(texts)
    return any(ng in t or (t in ng and len(t) >= 9) for t in texts) or ng in joined


for f in sorted(glob.glob(sys.argv[1])):
    d = json.load(open(f))
    cost = sum((v.get('_cost') or 0) for v in d.values())
    miss = [k for k, v in d.items() if not hit(GT[k.replace('_rot180', '').replace('_rot90', '')]['part_number'] if k.replace('_rot180', '').replace('_rot90', '') in GT else None, v)]
    errs = sum(bool(v.get('_parse_error')) for v in d.values())
    print(f"{f:44} ${cost/len(d):.5f}/part  gt_found {len(d)-len(miss)}/{len(d)} parse_err {errs} miss={miss}")
    for k in SHOW:
        if k in d:
            print("    ", k, "|", d[k].get('part_description'), "| n=", d[k].get('item_count'))
