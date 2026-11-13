#!/usr/bin/env python3
"""#part-id speed test: joins the Mac's results (run_speed.py), the bot's timings from the VM
(speedtest.jsonl) and OpenRouter's own stats per call into one JSON, every time in ms.

usage: python build_json.py <mac results.jsonl> <vm speedtest.jsonl> <offset.json> <baseline nq.json> <out.json>
"""
import json, os, statistics, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import jev_client  # noqa: E402

mac = [json.loads(l) for l in open(sys.argv[1])]
vm = {r["msg"]: r for r in map(json.loads, open(sys.argv[2]))}
offset = json.load(open(sys.argv[3]))
baseline_nq = json.load(open(sys.argv[4]))
OFF = offset["vm_minus_mac_ms"] / 1000   # VM clock minus Mac clock, seconds
KEY = jev_client.resolve_api_key()


def snowflake(i):
    return ((int(i) >> 22) + 1420070400000) / 1000


def ms(a, b):
    return None if a is None or b is None else round((b - a) * 1000, 1)


def generation(gid):
    if not gid:
        return None
    for _ in range(5):
        try:
            req = urllib.request.Request(f"https://openrouter.ai/api/v1/generation?id={gid}",
                                         headers={"Authorization": f"Bearer {KEY}"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read())["data"]
            return {k: d.get(k) for k in ("provider_name", "model", "latency", "generation_time",
                                          "moderation_latency", "native_tokens_prompt",
                                          "native_tokens_completion", "total_cost", "streamed")}
        except Exception as e:  # stats can take a few seconds to appear
            err = str(e)
            time.sleep(2)
    return {"error": err}


runs, network = [], {}
for r in mac:
    if r["kind"] == "network":
        network[r["gate"]] = {"down_mbps": r["dl_throughput"] and round(r["dl_throughput"] / 1e6, 2),
                              "up_mbps": r["ul_throughput"] and round(r["ul_throughput"] / 1e6, 2),
                              "base_rtt_ms": r["base_rtt"] and round(r["base_rtt"], 1),
                              "error": r.get("error")}
        continue
    v = vm.get(r["msg"], {})
    inner = v.get("inner") or {}
    vt = lambda x: None if x is None else x - OFF          # VM time on the Mac's clock
    c = r["curl"]
    t0 = r["post_start"]
    created = snowflake(r["msg"])
    reply_created = snowflake(r["reply"]) if r.get("reply") else None
    chat = (inner.get("chat") or [[None, None]])[0]
    jev = (inner.get("jev") or [[None, None]])[0]
    enc = (inner.get("encode") or [[None, None]])[0]
    gen = generation(((inner.get("chat_ids") or [{}])[0]).get("id"))
    chat_ms = ms(*chat)
    jev_ms = ms(*jev)
    or_inside = (gen or {}).get("generation_time")
    run = {
        "gate": r["gate"], "cap_kbit": r["cap_kbit"], "run": r["run"], "message_id": r["msg"],
        "reply_id": r.get("reply"),
        "end_to_end_ms": ms(t0, r.get("reply_seen")),
        "client": {
            "dns_ms": round(c["time_namelookup"] * 1000, 1),
            "tcp_connect_ms": round((c["time_connect"] - c["time_namelookup"]) * 1000, 1),
            "tls_ms": round((c["time_appconnect"] - c["time_connect"]) * 1000, 1),
            "upload_and_discord_accept_ms": round((c["time_starttransfer"] - c["time_pretransfer"]) * 1000, 1),
            "post_total_ms": round(c["time_total"] * 1000, 1),
            "upload_bytes": c["size_upload"], "upload_speed_kbps": round(c["speed_upload"] * 8 / 1000, 1),
            "post_start_to_discord_created_ms": ms(t0, created),
            "photo_echo_back_on_mac_ms": ms(t0, r.get("echo_seen")),
            "reply_created_to_seen_on_mac_ms": ms(reply_created, r.get("reply_seen")),
        },
        "server": {
            "discord_to_bot_event_ms": ms(created, vt(v.get("event"))),
            "photo_download_vm_ms": ms(v.get("one"), v.get("saved")),
            "queue_wait_ms": ms(v.get("saved"), v.get("read_start")),
            "python_start_ms": ms(v.get("read_start"), inner.get("t0")),
            "imports_ms": ms(inner.get("t0"), inner.get("imported")),
            "image_encode_ms": ms(*enc),
            "agent1_openrouter_call_ms": chat_ms,
            "agent1_parse_ms": ms(chat[1], jev[0]) if jev[0] else None,
            "jev_openrouter_call_ms": jev_ms,
            "exit_and_json_ms": ms(inner.get("end"), v.get("read_end")),
            "pipeline_total_ms": ms(v.get("read_start"), v.get("read_end")),
            "reply_post_ms": ms(v.get("reply_start"), v.get("reply_end")),
            "card_save_ms": ms(v.get("reply_end"), v.get("saved_card")),
            "bot_event_to_reply_sent_ms": ms(v.get("event"), v.get("reply_end")),
        },
        "openrouter": {
            "agent1": {**(gen or {}), "round_trip_ms": chat_ms,
                       "network_and_queue_ms": round(chat_ms - or_inside, 1) if chat_ms and or_inside else None},
            "jev": {"round_trip_ms": jev_ms, "ids": inner.get("jev_ids")},
        },
        "options": v.get("options"), "cost_usd": v.get("cost"),
    }
    s = run["server"]
    run["split_ms"] = {
        "client_connection": round((ms(t0, created) or 0) + (run["client"]["reply_created_to_seen_on_mac_ms"] or 0), 1),
        "discord_to_server": s["discord_to_bot_event_ms"],
        "openrouter_calls": round((chat_ms or 0) + (jev_ms or 0), 1),
        "our_code": round(sum(x or 0 for x in (s["photo_download_vm_ms"], s["queue_wait_ms"], s["python_start_ms"],
                                               s["imports_ms"], s["image_encode_ms"], s["agent1_parse_ms"],
                                               s["exit_and_json_ms"], s["card_save_ms"])), 1),
        "reply_to_discord": s["reply_post_ms"],
    }
    runs.append(run)


def avg(gate, f):
    xs = [f(r) for r in runs if r["gate"] == gate and f(r) is not None]
    return round(statistics.mean(xs), 1) if xs else None


summary = {}
for g in dict.fromkeys(r["gate"] for r in runs):
    summary[g] = {
        "cap_kbit": next(r["cap_kbit"] for r in runs if r["gate"] == g),
        "measured": network.get(g),
        "runs": sum(r["gate"] == g for r in runs),
        "avg_end_to_end_ms": avg(g, lambda r: r["end_to_end_ms"]),
        "min_end_to_end_ms": min((r["end_to_end_ms"] for r in runs if r["gate"] == g and r["end_to_end_ms"]), default=None),
        "max_end_to_end_ms": max((r["end_to_end_ms"] for r in runs if r["gate"] == g and r["end_to_end_ms"]), default=None),
        **{f"avg_{k}_ms": avg(g, lambda r, k=k: r["split_ms"][k]) for k in runs[0]["split_ms"]},
        "avg_photo_upload_ms": avg(g, lambda r: r["client"]["post_start_to_discord_created_ms"]),
        "avg_reply_back_to_mac_ms": avg(g, lambda r: r["client"]["reply_created_to_seen_on_mac_ms"]),
    }

out = {"test": "#part-id end to end: photo sent from the Mac -> bot reply received on the Mac",
       "date": time.strftime("%Y-%m-%d"), "photo_bytes": runs[0]["client"]["upload_bytes"] if runs else None,
       "throttle": "Mac only, bandwidth cap up+down via dnctl/pf, no added latency; VM not throttled",
       "clock": {"vm_minus_mac_ms": offset["vm_minus_mac_ms"], "measured_rtt_ms": offset["rtt_ms"]},
       "baseline_connection": {"down_mbps": round(baseline_nq["dl_throughput"] / 1e6, 2),
                               "up_mbps": round(baseline_nq["ul_throughput"] / 1e6, 2),
                               "base_rtt_ms": round(baseline_nq["base_rtt"], 1)},
       "summary": summary, "runs": runs}
Path(sys.argv[5]).write_text(json.dumps(out, indent=1))
print(json.dumps(summary, indent=1))
