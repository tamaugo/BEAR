#!/usr/bin/env python3
"""
Reverse-image-search viability test for parts with NO part number.

Answers one question and nothing else: when you hand Google Vision a photo of an
unmarked car part, does it return a usable eBay.co.uk listing -- and is the right
one near the top?

Usage:
    export GOOGLE_API_KEY="..."          # set in your own shell; never stored here
    python3 image_search_test.py <folder-or-image> [more...] -o results.html

Then open results.html, and for each part click the candidate that is actually the
same component (or "none of these"). The script records your answers and prints the
numbers that decide whether this path is worth building.

Cost: Google Cloud Vision WEB_DETECTION is $3.50/1000 after the first 1,000 free
units each month. A 7-part test is free and stays free at ~3,000 parts/month.

Setup: create a Google Cloud project, enable the Cloud Vision API, create an API
key. No billing is charged inside the free tier, but a billing account must exist.
"""

import argparse, base64, html, json, os, sys, urllib.request, urllib.error
from pathlib import Path

VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
EBAY_HOSTS = ("ebay.co.uk", "ebay.com")   # reporting distinguishes the two


def vision_web_detection(path: Path, api_key: str, max_results: int = 20) -> dict:
    body = json.dumps({
        "requests": [{
            "image": {"content": base64.b64encode(path.read_bytes()).decode()},
            "features": [{"type": "WEB_DETECTION", "maxResults": max_results}],
        }]
    }).encode()
    req = urllib.request.Request(
        f"{VISION_URL}?key={api_key}", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise SystemExit(
            f"\nVision API error {e.code} on {path.name}:\n{detail}\n\n"
            "Common causes: API key wrong or restricted; Cloud Vision API not "
            "enabled on the project; no billing account attached (required even "
            "inside the free tier).")
    resp = payload.get("responses", [{}])[0]
    if "error" in resp:
        raise SystemExit(f"Vision returned an error for {path.name}: {resp['error']}")
    return resp.get("webDetection", {})


def ebay_candidates(web: dict) -> list[dict]:
    """Pages whose matching image sits on an eBay listing, best-first."""
    out = []
    for page in web.get("pagesWithMatchingImages", []):
        url = page.get("url", "")
        if not any(h in url for h in EBAY_HOSTS):
            continue
        thumbs = [i.get("url") for i in
                  (page.get("fullMatchingImages", []) + page.get("partialMatchingImages", []))
                  if i.get("url")]
        out.append({
            "url": url,
            "title": page.get("pageTitle") or "(no title returned)",
            "thumb": thumbs[0] if thumbs else None,
            "uk": "ebay.co.uk" in url,
        })
    return out


def render(results: list[dict], out_path: Path) -> None:
    esc = html.escape
    parts = []
    for i, r in enumerate(results):
        cands = r["candidates"]
        cells = []
        for j, c in enumerate(cands[:8], 1):
            thumb = (f'<img src="{esc(c["thumb"])}" loading="lazy" referrerpolicy="no-referrer">'
                     if c["thumb"] else '<div class="nothumb">no thumbnail</div>')
            flag = "" if c["uk"] else '<span class="us">.com</span>'
            cells.append(
                f'<label class="cand"><input type="radio" name="p{i}" value="{j}">'
                f'<span class="rank">#{j}</span>{flag}{thumb}'
                f'<a href="{esc(c["url"])}" target="_blank" rel="noreferrer">{esc(c["title"])[:90]}</a>'
                f'</label>')
        if not cells:
            cells.append('<div class="empty">No eBay pages returned at all.</div>')
        guess = ", ".join(r["labels"]) or "-"
        parts.append(f"""
<section>
  <h2>{esc(r['file'])}</h2>
  <div class="meta">Vision's best guess: <b>{esc(guess)}</b> &middot;
      {len(cands)} eBay page(s) of {r['total_pages']} total matches</div>
  <div class="row">
    <figure class="source"><img src="{esc(r['data_uri'])}"><figcaption>the part</figcaption></figure>
    <div class="cands">{''.join(cells)}
      <label class="cand none"><input type="radio" name="p{i}" value="0">
        <span class="rank">&times;</span><b>None of these is the part</b></label>
    </div>
  </div>
</section>""")

    out_path.write_text(f"""<!doctype html><meta charset="utf-8">
<title>Reverse image search test</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:0;padding:24px;background:#f6f7f9;color:#111}}
 h1{{margin:0 0 4px}} .lede{{color:#555;margin:0 0 24px;max-width:70ch}}
 section{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:16px;margin:0 0 20px}}
 h2{{margin:0 0 2px;font-size:15px}} .meta{{color:#666;font-size:12px;margin-bottom:12px}}
 .row{{display:flex;gap:20px;align-items:flex-start}}
 .source{{margin:0;flex:0 0 220px}} .source img{{width:220px;border-radius:8px;border:1px solid #ddd}}
 .source figcaption{{font-size:12px;color:#666;text-align:center;margin-top:4px}}
 .cands{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;flex:1}}
 .cand{{display:block;border:1px solid #e3e6ea;border-radius:8px;padding:8px;cursor:pointer;background:#fff;position:relative}}
 .cand:hover{{border-color:#7aa7d9}} .cand input{{margin-bottom:6px}}
 .cand img{{width:100%;height:110px;object-fit:contain;background:#fafafa;border-radius:4px}}
 .cand a{{display:block;font-size:11px;color:#0b5;text-decoration:none;margin-top:6px;word-break:break-word}}
 .rank{{position:absolute;top:6px;right:8px;font-size:11px;color:#999}}
 .us{{position:absolute;top:6px;right:28px;font-size:10px;color:#c60}}
 .none{{display:flex;align-items:center;gap:8px;border-style:dashed}}
 .nothumb,.empty{{font-size:12px;color:#999;padding:20px 0;text-align:center}}
 #out{{position:sticky;bottom:0;background:#111;color:#fff;padding:14px 18px;border-radius:10px;font:13px/1.6 ui-monospace,monospace;white-space:pre-wrap}}
</style>
<h1>Reverse image search &mdash; viability test</h1>
<p class="lede">For each part, click the candidate that is genuinely the same component.
Judge it as strictly as you would for a customer. If none match, click
&ldquo;none of these&rdquo;. The summary at the bottom updates as you go.</p>
{''.join(parts)}
<div id="out">Pick one option per part.</div>
<script>
const N={len(results)};
function upd(){{
  let done=0,hit=0,r1=0,miss=0,ranks=[];
  for(let i=0;i<N;i++){{
    const c=document.querySelector(`input[name="p${{i}}"]:checked`);
    if(!c)continue; done++;
    const v=+c.value;
    if(v===0){{miss++;}} else {{hit++; ranks.push(v); if(v===1)r1++;}}
  }}
  const pct=x=>done?(100*x/done).toFixed(0)+'%':'-';
  document.getElementById('out').textContent =
    `judged ${{done}}/${{N}}\\n`+
    `correct part found : ${{hit}} (${{pct(hit)}})\\n`+
    `  of those, at rank 1: ${{r1}}\\n`+
    `no correct match    : ${{miss}} (${{pct(miss)}})\\n`+
    (ranks.length?`ranks chosen        : ${{ranks.join(', ')}}\\n`:'')+
    `\\nRead: high "correct at rank 1" => a confidence gate is viable.\\n`+
    `High "no correct match" => this path is dead, stop here.`;
}}
document.addEventListener('change',upd);
</script>""", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", help="image files, or folders of images")
    ap.add_argument("-o", "--out", default="image_search_results.html")
    ap.add_argument("--limit", type=int, default=0, help="cap images processed (0 = no cap)")
    args = ap.parse_args()

    key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set GOOGLE_API_KEY in your shell first. This script never stores it.")

    imgs: list[Path] = []
    for p in map(Path, args.paths):
        if p.is_dir():
            imgs += sorted(q for q in p.iterdir() if q.suffix.lower() in IMAGE_EXTS)
        elif p.suffix.lower() in IMAGE_EXTS:
            imgs.append(p)
    if args.limit:
        imgs = imgs[:args.limit]
    if not imgs:
        raise SystemExit("No images found.")

    print(f"{len(imgs)} image(s). Free tier covers 1,000 lookups/month.\n")
    results = []
    for n, img in enumerate(imgs, 1):
        print(f"[{n}/{len(imgs)}] {img.name} ... ", end="", flush=True)
        web = vision_web_detection(img, key)
        cands = ebay_candidates(web)
        labels = [l.get("label", "") for l in web.get("bestGuessLabels", [])]
        uk = sum(1 for c in cands if c["uk"])
        print(f"{len(cands)} eBay page(s) ({uk} .co.uk)")
        results.append({
            "file": img.name,
            "data_uri": "data:image/jpeg;base64," + base64.b64encode(img.read_bytes()).decode(),
            "candidates": cands,
            "labels": [l for l in labels if l],
            "total_pages": len(web.get("pagesWithMatchingImages", [])),
        })

    out = Path(args.out)
    render(results, out)
    none_at_all = sum(1 for r in results if not r["candidates"])
    print(f"\nWrote {out.resolve()}")
    print(f"{len(results) - none_at_all}/{len(results)} parts returned at least one eBay page.")
    if none_at_all == len(results):
        print("\nNo eBay pages for any part. That is the answer -- this path is dead. Stop here.")
    else:
        print("Open the file and judge each one. The summary at the bottom is the result.")


if __name__ == "__main__":
    main()
