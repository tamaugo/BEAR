"""Score an agent2_results.md (stage-level) against the operator ground truth.
Checks: part number (normalised), listing == operator's listing, price after
.99-round + 19.99 floor == operator price."""
import json, math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as c

GT = Path(__file__).resolve().parent.parent / "tests/fixtures/ground_truth_hyundai_i40_2026-09-30.json"


def op_price(p):
    p = float(p)
    r = math.floor(p) + 0.99 if round(p % 1, 2) != 0.99 else p
    if r < p:
        r += 1
    return max(19.99, round(r, 2))


def main(path):
    gt = {p["image"]: p for p in json.loads(GT.read_text())["parts"]}
    n_pn = n_url = n_price = n = 0
    for line in Path(path).read_text().splitlines():
        f = [x.strip() for x in line.split("|")]
        name = f[0]
        g = gt.get(name)
        if not g:
            continue
        n += 1
        if g.get("expect_fail"):
            ok = f[1] == "FAILED"
            n_pn += ok; n_url += ok; n_price += ok
            print(f"{'OK ' if ok else 'BAD'} {name:18} expect FAIL -> {' | '.join(f[1:])[:60]}")
            continue
        if f[1] == "FAILED":
            print(f"BAD {name:18} FAILED ({f[-1]}) expected {g['part_number']}")
            continue
        pn_ok = c.norm(f[1]).startswith(c.norm(g["part_number"])) and len(c.norm(f[1])) - len(c.norm(g["part_number"])) <= 1
        url_ok = f[-1].rstrip("/").split("/")[-1] == g["url"].split("/")[-1]
        pr = op_price(f[-2])
        price_ok = g["price"] is None or abs(pr - g["price"]) < 0.01
        n_pn += pn_ok; n_url += url_ok; n_price += price_ok
        print(f"{'OK ' if pn_ok else 'BAD'} pn  {'OK ' if url_ok else '-- '}url {'OK ' if price_ok else '-- '}price "
              f"{name:18} {f[1]:14} {pr:>7} (op {g['price']}) | {f[2][:60]}")
    print(f"\npart numbers {n_pn}/{n}   exact operator listing {n_url}/{n}   price {n_price}/{n}")


if __name__ == "__main__":
    main(sys.argv[1])
