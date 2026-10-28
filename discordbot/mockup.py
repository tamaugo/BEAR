#!/usr/bin/env python3
"""Draw what the Discord server will look like, from the real look.py posts, as one HTML page in
Discord's dark style. Nothing connects to Discord. Re-run after changing look.py.

usage: python3 discordbot/mockup.py            -> discordbot/mockup.html (open it in a browser)
"""
import html, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import look  # noqa: E402

ERRORS_ID, GUIDE_ID, CAR_ID, CAR2_ID, GENERAL_ID = 101, 102, 201, 202, 301
CHANNELS = {ERRORS_ID: "bear-errors", GUIDE_ID: "how-to-bear", CAR_ID: "ford-fiesta-mk7-2012",
            CAR2_ID: "vw-golf-mk6-2010", GENERAL_ID: "general"}
CAR = "FORD FIESTA MK7 2012 HATCHBACK 1.4 DIESEL"
CAR2 = "VW GOLF MK6 2010 ESTATE 1.6 TDI"
NOW = time.time()


def md(text):
    """The bits of Discord markdown look.py uses."""
    text = html.escape(text or "", quote=False)
    blocks = []

    def keep(m):
        blocks.append(f"<pre>{m.group(1).strip(chr(10))}</pre>")
        return f"\x00{len(blocks) - 1}\x00"
    text = re.sub(r"```(.*?)```", keep, text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="#">\1</a>', text)
    text = re.sub(r"(?m)^# (.+)$", r'<div class="h1">\1</div>', text)
    text = re.sub(r"&lt;#(\d+)&gt;", lambda m: f'<span class="mention">#{CHANNELS.get(int(m.group(1)), "channel")}</span>', text)
    text = re.sub(r"&lt;@(\w+)&gt;", r'<span class="mention">@\1</span>', text)
    text = re.sub(r"&lt;t:(\d+):R&gt;", lambda m: f'<span class="ts">{max(1, int((NOW - int(m.group(1))) // 60))} minutes ago</span>', text)
    text = text.replace("\n", "<br>")
    return re.sub(r"\x00(\d+)\x00", lambda m: blocks[int(m.group(1))], text)


def embed(e):
    colour = f"#{e['color']:06x}"
    out = [f'<div class="embed" style="border-left-color:{colour}">']
    if e.get("title"):
        out.append(f'<div class="etitle">{md(e["title"])}</div>')
    if e.get("description"):
        out.append(f'<div class="edesc">{md(e["description"])}</div>')
    for f in e.get("fields", []):
        out.append(f'<div class="field"><div class="fname">{md(f["name"])}</div><div>{md(f["value"])}</div></div>')
    if e.get("footer"):
        out.append(f'<div class="efoot">{md(e["footer"]["text"])}</div>')
    return "".join(out) + "</div>"


def buttons(post_buttons):
    """[(label, style)] under a message; style: ok | fix | alt (Discord's green, blurple, grey)."""
    return ('<div class="btns">' + "".join(f'<span class="btn {st}">{html.escape(label)}</span>'
                                           for label, st in post_buttons) + "</div>") if post_buttons else ""


def check_buttons(number, alts):
    """The part-check card's buttons, as bot.check_buttons makes them."""
    if not number:
        return [(f"{look.PENCIL} {look.CHECK_BUTTONS['type']}", "fix")]
    return ([(f"{look.TICK} {look.CHECK_BUTTONS['ok']}", "ok")] + [(a, "alt") for a in alts]
            + [(f"{look.PENCIL} {look.CHECK_BUTTONS['fix']}", "fix")])


def bot(post, used=None, who="Sam", ephemeral=False, file=None, when="Today at 14:02", note=None,
        btns=None, reply_to=None):
    head = ""
    if reply_to:
        head = f'<div class="used">↱ <span class="uname">@{reply_to}</span> <span class="ph-s">🏷️ Click to see attachment</span></div>'
    if used:
        head = f'<div class="used"><span class="uname">@{who}</span> used <span class="cmd">{used}</span></div>'
    body = md(post["content"]) if post.get("content") else ""
    embeds = "".join(embed(e) for e in post.get("embeds", []))
    att = f'<div class="file"><span class="ficon">XLSX</span><div><a href="#">{file}</a><div class="fsize">5.2 KB</div></div></div>' if file else ""
    eph = '<div class="eph">👁 Only you can see this · <a href="#">Dismiss message</a></div>' if ephemeral else ""
    n = f'<div class="note">{note}</div>' if note else ""
    return (f'{n}<div class="msg">{head}<div class="row"><div class="av bot">🐻</div><div class="mbody">'
            f'<div class="who"><span class="bname">BEAR</span><span class="tag">APP</span><span class="when">{when}</span></div>'
            f'<div class="text">{body}</div>{embeds}{buttons(btns)}{att}{eph}</div></div></div>')


def person(photos=0, who="Sam", text=None, when="Today at 13:58", note=None, struck=False):
    tiles = "".join('<div class="ph">🏷️ label</div>' for _ in range(photos))
    t = f'<div class="text{" struck" if struck else ""}">{html.escape(text)}</div>' if text else ""
    n = f'<div class="note">{note}</div>' if note else ""
    return (f'{n}<div class="msg"><div class="row"><div class="av">{who[0]}</div><div class="mbody">'
            f'<div class="who"><span class="uname">{who}</span><span class="when">{when}</span></div>'
            f'{t}<div class="photos">{tiles}</div></div></div></div>')


def scenes():
    folder = look.folder_card("Q184", CAR)
    fname = "Q184-ford-fiesta-mk7.xlsx"
    s = {}
    num, alts = "82481-3Z000", ["82481-3Z0O0", "82481-3Z010"]
    ask = look.check_card("ask", num, alts, seconds=3.4)
    s["general"] = (
        "Part check: a photo posted in ANY channel gets a reply with the part number Agent 1 reads. "
        "One card per photo, edited in place.",
        person(1, when="Today at 10:14", note="Someone posts a photo of a part number")
        + bot(look.check_card("reading"), reply_to="Sam", when="Today at 10:14",
              note="Straight away: the bot replies so they know it's being read")
        + bot(ask, btns=check_buttons(num, alts), reply_to="Sam", when="Today at 10:14",
              note="About 3-5 s later, the same card: the number, big. ✅ / another reading / ✏️ Fix")
        + '<div class="modal"><div class="mtitle">' + html.escape(look.CHECK_BOX["title"]) + '</div>'
          '<div class="mlabel">' + html.escape(look.CHECK_BOX["label"]).upper() + '</div>'
          '<div class="minput">' + num + '</div><div class="mfoot"><span class="btn alt">Cancel</span>'
          '<span class="btn fix">Submit</span></div></div>'
        + bot(look.check_card("done", num, who="<@Sam>", how="ok"), reply_to="Sam",
              when="Today at 10:15", note="Tapped ✅ Correct: card goes green, buttons go, a line is saved")
        + bot(look.check_card("done", "82481-3Z010", who="<@Sam>", how="alt", read=num), reply_to="Sam",
              when="Today at 10:15", note="…or tapped another reading")
        + bot(look.check_card("done", "82481-3Z000-RY", who="<@Sam>", how="fix", read=num), reply_to="Sam",
              when="Today at 10:15", note="…or ✏️ Fix: a box filled with BEAR's reading (above), edited and sent")
        + person(3, when="Today at 10:20", note="Several photos in one message: one card each")
        + bot(look.check_card("ask", "97420-3Z000", ["97420-3Z00O"], 2, 3, seconds=2.9),
              btns=check_buttons("97420-3Z000", ["97420-3Z00O"]), reply_to="Sam", when="Today at 10:20")
        + bot(look.check_card("none", photo=3, of=3, seconds=4.8), btns=check_buttons(None, []), reply_to="Sam",
              when="Today at 10:20", note="No number found (rotated re-reads included)")
        + bot(look.check_card("failed"), reply_to="Sam", when="Today at 10:31",
              note="Model down or over 60 s: red, send again (owner told once in #bear-errors, BEAR-C01)")
        + bot({"content": look.reply("check_answered"), "embeds": []}, ephemeral=True,
              when="Today at 10:15", note="Someone taps a card that was already answered")
        + '<div class="note">What lands in checks/part-numbers.txt (one tab-separated line per answer)</div>'
          '<pre class="txt">time                       channel   who  part_number     bear_read    how                     wait_s read_s\n'
          '2026-10-28T10:14:09+00:00  #general  Sam  82481-3Z000     82481-3Z000  correct                 4.1    3.4\n'
          '2026-10-28T10:15:30+00:00  #general  Sam  82481-3Z010     82481-3Z000  picked another reading  3.8    3.1\n'
          '2026-10-28T10:16:02+00:00  #general  Sam  82481-3Z000-RY  82481-3Z000  typed                   3.9    3.2\n'
          '<i>(+ photo link and saved photo path in the last two columns)</i></pre>')
    s["how-to-bear"] = ("Pinned guide. Read-only for everyone; the bot posts it once and pins it.",
                        bot(look.guide(ERRORS_ID), note="📌 Pinned"))
    s["ford-fiesta-mk7-2012"] = (
        "The normal flow. Topic: " + CAR,
        bot(folder, used="/newfolder name: Q184", when="Today at 13:50")
        + person(5, when="Today at 13:51", note="Only part-number photos; each photo is one part")
        + person(7, when="Today at 13:53")
        + person(text="that's the box done", when="Today at 13:54", struck=True,
                 note="Text is removed by the bot (a 10-second notice tells them why)")
        + bot({"content": look.reply("text_removed"), "embeds": []}, when="Today at 13:54",
              note="Notice, deletes itself after 10 s")
        + bot({"content": look.reply("on_it"), "embeds": []}, used="/run",
              ephemeral=True, when="Today at 14:02", note="/run: a private \"on it\", then ONE live card, edited in place")
        + bot(look.run_card("checking", "Q184", CAR), note="Stage 1: checking")
        + bot(look.run_card("waiting", "Q184", CAR, wait_seconds=30), note="Stage 2 (only if photos are still arriving)")
        + bot(look.run_card("downloading", "Q184", CAR, parts=12, got=7), note="Stage 3: \"Running 12 parts\" appears straight away")
        + bot(look.run_card("queued", "Q184", CAR, parts=12, queue_ahead=1, max_runs=2), note="Stage 4 (only if 2 folders are already running)")
        + bot(look.run_card("running", "Q184", CAR, parts=12, since=NOW - 240), note="Stage 5")
        + bot(look.done_card("Q184", CAR, 12, 10, fname, minutes=9), file=fname, when="Today at 14:11",
              note="Final state: the same card, green, with the spreadsheet"))
    s["vw-golf-mk6-2010"] = (
        "Problems as the uploader sees them. Topic: " + CAR2,
        bot(look.problem_card("Q190", "BEAR-D05", ERRORS_ID, ["https://discord.com/x/1"]), used="/run",
            note="Uploader can fix it: what to do + a tap-able link to the exact photo")
        + bot(look.problem_card("Q190", "BEAR-D03", ERRORS_ID), used="/run")
        + bot(look.problem_card("Q191", "BEAR-N01", ERRORS_ID), used="/run",
              note="Owner has to fix it: the uploader is told there's nothing to do")
        + bot(look.problem_card("Q192", "BEAR-K02", ERRORS_ID, partial=True),
              note="Spreadsheet posted, but some parts lost to the spend cap")
        + bot({"content": look.reply("busy", folder="Q192", state="running"), "embeds": []},
              used="/run", ephemeral=True, note="Small refusals are only shown to the person who typed")
        + bot(look.status_card([
            {"folder": "Q184", "channel_id": CAR_ID, "state": "running", "parts": 12, "since": NOW - 420},
            {"folder": "Q192", "channel_id": CAR2_ID, "state": "queued", "parts": 4, "since": NOW - 60}],
            2, NOW), used="/status"))
    s["bear-errors"] = (
        "Owner's channel. Read-only for staff; the bot posts here.",
        bot(look.bot_started(2, version="0.4.12"), when="Today at 08:00")
        + bot(look.error_report("Q190", "BEAR-D05",
                                "A photo in the folder is a type BEAR can't read (e.g. HEIC).",
                                "Re-upload it as JPG, PNG or WEBP, delete the original, then /run again.",
                                CAR2_ID, CAR2, "IMG_5.HEIC: https://discord.com/channels/1/202/9", "#"))
        + bot(look.error_report("Q191", "BEAR-N01", "The name model is rate limited.",
                                "Wait a few minutes and /run again, or set BEAR_NAME_MODEL in the server's .env.",
                                CAR2_ID, CAR2, "qwen/qwen3-... is unavailable: HTTP 429", "#"),
              file="Q191-log.txt"))
    return s


CSS = """
*{box-sizing:border-box}body{margin:0;font:15px/1.375 "gg sans","Noto Sans","Helvetica Neue",Arial,sans-serif;background:#313338;color:#dbdee1;display:flex;height:100vh}
.servers{width:72px;background:#1e1f22;padding:12px;display:flex;flex-direction:column;gap:8px;align-items:center}
.srv{width:48px;height:48px;border-radius:16px;background:#9f3434;display:grid;place-items:center;font-size:24px}
.side{width:240px;background:#2b2d31;overflow:auto}.sname{padding:14px 16px;font-weight:700;color:#f2f3f5;border-bottom:1px solid #1f2023}
.cat{padding:18px 8px 4px 16px;font-size:12px;font-weight:700;color:#949ba4;text-transform:uppercase}
.ch{margin:1px 8px;padding:6px 8px;border-radius:4px;color:#949ba4;cursor:pointer}.ch:hover{background:#35373c;color:#dbdee1}.ch.on{background:#404249;color:#fff}
.ch.dim{opacity:.55;cursor:default}
.main{flex:1;display:flex;flex-direction:column;min-width:0}.top{padding:12px 16px;border-bottom:1px solid #26272b;display:flex;gap:12px;align-items:baseline}
.top b{color:#f2f3f5}.top span{color:#949ba4;font-size:14px}.feed{flex:1;overflow:auto;padding:16px 0 40px}
.msg{padding:4px 16px 4px 16px}.msg:hover{background:#2e3035}.row{display:flex;gap:16px}
.av{width:40px;height:40px;border-radius:50%;background:#5865f2;display:grid;place-items:center;color:#fff;font-weight:700;flex:none}.av.bot{background:#9f3434;font-size:22px}
.mbody{min-width:0;flex:1}.who{display:flex;gap:6px;align-items:baseline}.bname,.uname{color:#f2f3f5;font-weight:600}
.tag{background:#5865f2;color:#fff;font-size:10px;font-weight:700;padding:0 4px;border-radius:3px}.when{color:#949ba4;font-size:12px}
.used{color:#949ba4;font-size:13px;margin:0 0 2px 56px}.used .uname{color:#c9cdfb}.cmd{color:#00a8fc}
.text{white-space:normal}.struck{text-decoration:line-through;opacity:.5}
.embed{background:#2b2d31;border-left:4px solid;border-radius:4px;padding:8px 16px 12px 12px;margin-top:4px;max-width:520px}
.etitle{font-weight:700;color:#f2f3f5;margin-top:4px}.edesc{margin-top:6px;font-size:14px}.field{margin-top:8px;font-size:14px}.fname{font-weight:700;color:#f2f3f5}
.efoot{margin-top:8px;font-size:12px;color:#b5bac1}
code{background:#1e1f22;padding:1px 4px;border-radius:3px;font-size:13px}pre{background:#1e1f22;border:1px solid #1f2023;padding:7px;border-radius:4px;font-size:12px;white-space:pre-wrap}
a{color:#00a8fc;text-decoration:none}.mention{background:#3c4270;color:#c9cdfb;padding:0 2px;border-radius:3px}.ts{background:#3f4147;padding:0 3px;border-radius:3px}
.photos{display:flex;gap:4px;flex-wrap:wrap;margin-top:4px}.ph{width:84px;height:84px;background:#404249;border-radius:6px;display:grid;place-items:center;font-size:13px;color:#b5bac1}
.react{display:inline-block;margin-top:4px;background:#373a54;border:1px solid #5865f2;border-radius:8px;padding:1px 8px;font-size:14px}
.file{display:flex;gap:10px;align-items:center;background:#2b2d31;border:1px solid #1f2023;border-radius:8px;padding:10px;margin-top:6px;max-width:400px}
.ficon{background:#1d6f42;color:#fff;font-size:10px;font-weight:700;padding:8px 4px;border-radius:3px}.fsize{font-size:12px;color:#949ba4}
.eph{font-size:12px;color:#949ba4;margin-top:4px}
.note{margin:14px 16px 2px 72px;font-size:12px;color:#f0b232;text-transform:uppercase;letter-spacing:.03em}
.scene{display:none}.scene.on{display:block}
.h1{font-size:26px;font-weight:700;color:#f2f3f5;margin:2px 0 4px}.h1 code{font-size:24px;padding:2px 6px}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.btn{padding:3px 14px;border-radius:4px;font-size:14px;font-weight:500;color:#fff;line-height:26px}
.btn.ok{background:#248046}.btn.fix{background:#5865f2}.btn.alt{background:#4e5058}.ph-s{color:#949ba4;font-style:italic}
.modal{margin:6px 16px 6px 72px;max-width:440px;background:#313338;border:1px solid #1e1f22;border-radius:8px;padding:16px;box-shadow:0 8px 24px #0008}
.mtitle{font-size:20px;font-weight:700;color:#f2f3f5;margin-bottom:12px}.mlabel{font-size:12px;font-weight:700;color:#b5bac1;margin-bottom:6px}
.minput{background:#1e1f22;border-radius:4px;padding:10px;color:#dbdee1}.mfoot{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
.txt{margin:4px 16px 0 72px;max-width:900px;overflow:auto;white-space:pre}
"""


def page():
    sc = scenes()
    side = ('<div class="sname">BEAR Parts</div><div class="cat">🐻 BEAR</div>'
            + "".join(f'<div class="ch" data-s="{n}"># {n}</div>' for n in ("how-to-bear", "bear-errors"))
            + '<div class="cat">💬 Chat</div><div class="ch" data-s="general"># general</div>'
            + '<div class="cat">🚗 Cars</div>'
            + "".join(f'<div class="ch" data-s="{n}"># {n}</div>' for n in ("ford-fiesta-mk7-2012", "vw-golf-mk6-2010"))
            + '<div class="cat">🗄️ Done</div><div class="ch dim"># bmw-e90-2008</div>')
    topics = {"general": "Any channel: photos get a part check", "how-to-bear": "How BEAR works", "bear-errors": "Problems and the owner's notes",
              "ford-fiesta-mk7-2012": CAR, "vw-golf-mk6-2010": CAR2}
    main = "".join(
        f'<div class="scene" id="s-{n}"><div class="top"><b># {n}</b><span>{html.escape(topics[n])}</span></div>'
        f'<div class="feed"><div class="note" style="margin-left:16px;color:#949ba4">{html.escape(about)}</div>{body}</div></div>'
        for n, (about, body) in sc.items())
    js = ("const show=n=>{document.querySelectorAll('.scene').forEach(e=>e.classList.toggle('on',e.id=='s-'+n));"
          "document.querySelectorAll('.ch[data-s]').forEach(e=>e.classList.toggle('on',e.dataset.s==n))};"
          "document.querySelectorAll('.ch[data-s]').forEach(e=>e.onclick=()=>show(e.dataset.s));show('general');")
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>BEAR on Discord: mockup</title>'
            f'<style>{CSS}</style></head><body><div class="servers"><div class="srv">🐻</div></div>'
            f'<div class="side">{side}</div><div class="main">{main}</div><script>{js}</script></body></html>')


if __name__ == "__main__":
    out = HERE / "mockup.html"
    out.write_text(page())
    print(out)
