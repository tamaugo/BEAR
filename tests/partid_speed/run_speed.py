#!/usr/bin/env python3
"""#part-id speed test, Mac side: caps the Mac's bandwidth (dnctl/pf, no added latency), posts the same
photo into #part-id through the speed-test webhook, and times everything up to the bot's reply arriving
back on the Mac over the Discord gateway (how the Discord app gets it).

usage: DISCORD_TOKEN=... python run_speed.py <webhook-url-file> <photo> <out.jsonl> [runs per gate]
Needs sudo -n for /usr/sbin/dnctl and /sbin/pfctl (a temporary /etc/sudoers.d/bear-speedtest).
"""
import asyncio, json, os, re, subprocess, sys, time

import discord

GATES = [("really_slow", 256), ("slow", 1000), ("medium", 10000), ("fast", 50000), ("baseline", None)]  # Kbit/s
PF_RULES = ("dummynet out quick on en0 inet from any to ! 192.168.1.0/24 pipe 1\n"   # LAN (ssh to the VM) not capped
            "dummynet in quick on en0 inet from ! 192.168.1.0/24 to any pipe 2\n"
            "dummynet out quick on en0 inet6 from any to ! fe80::/10 pipe 1\n"      # Discord goes over IPv6 too
            "dummynet in quick on en0 inet6 from ! fe80::/10 to any pipe 2\n")
ANCHOR = "com.apple/bear-speedtest"
REPLY_TIMEOUT = 300
GAP = 5   # seconds between runs

webhook = open(sys.argv[1]).read().strip()
photo, out_path = sys.argv[2], sys.argv[3]
runs = int(sys.argv[4]) if len(sys.argv) > 4 else 3
seen = {}   # message id -> {"t", "ref", "author"}
pf_token = None


def sudo(*cmd, inp=None):
    return subprocess.run(["sudo", "-n", *cmd], input=inp, capture_output=True, text=True)


def throttle(kbit):
    global pf_token
    unthrottle()
    if kbit is None:
        return
    for pipe in ("1", "2"):
        r = sudo("/usr/sbin/dnctl", "pipe", pipe, "config", "bw", f"{kbit}Kbit/s")
        assert r.returncode == 0, r.stderr
    r = sudo("/sbin/pfctl", "-a", ANCHOR, "-f", "-", inp=PF_RULES)
    assert r.returncode == 0, r.stderr
    r = sudo("/sbin/pfctl", "-E")
    m = re.search(r"Token : (\d+)", r.stderr + r.stdout)
    pf_token = m and m.group(1)


def unthrottle():
    global pf_token
    sudo("/sbin/pfctl", "-a", ANCHOR, "-F", "all")
    if pf_token:
        sudo("/sbin/pfctl", "-X", pf_token)
        pf_token = None
    sudo("/usr/sbin/dnctl", "-q", "flush")


def write(rec):
    with open(out_path, "a") as f:
        f.write(json.dumps(rec) + "\n")


async def network_quality(gate):
    p = await asyncio.create_subprocess_exec("networkQuality", "-c", "-M", "20",
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await p.communicate()
    try:
        d = json.loads(out)
    except ValueError:
        d = {"error": out.decode(errors="replace")[:300]}
    write({"kind": "network", "gate": gate, "t": time.time(),
           **{k: d.get(k) for k in ("dl_throughput", "ul_throughput", "base_rtt", "responsiveness", "error")}})


async def one_run(gate, kbit, n):
    rec = {"kind": "run", "gate": gate, "cap_kbit": kbit, "run": n}
    payload = json.dumps({"content": f"speed test · {gate} · run {n}"})
    rec["post_start"] = time.time()
    p = await asyncio.create_subprocess_exec(
        "curl", "-s", "-o", "/tmp/bear-speed/resp.json", "-w", "%{json}",
        "-F", f"payload_json={payload}", "-F", f"files[0]=@{photo};filename=speedtest.jpeg",
        f"{webhook}?wait=true", stdout=asyncio.subprocess.PIPE)
    w, _ = await p.communicate()
    rec["post_end"] = time.time()
    rec["curl"] = {k: v for k, v in json.loads(w).items()
                   if k.startswith(("time_", "speed_", "size_", "http_code", "num_connects"))}
    msg_id = int(json.load(open("/tmp/bear-speed/resp.json"))["id"])
    rec["msg"] = msg_id
    deadline = time.time() + REPLY_TIMEOUT
    while time.time() < deadline:
        reply = next((m for m, e in seen.items() if e["ref"] == msg_id), None)
        if reply:
            rec.update(reply=reply, reply_seen=seen[reply]["t"])
            break
        await asyncio.sleep(0.005)
    rec["echo_seen"] = seen.get(msg_id, {}).get("t")
    write(rec)
    print(gate, n, "reply" if rec.get("reply") else "TIMEOUT",
          round((rec.get("reply_seen", time.time()) - rec["post_start"]) * 1000), "ms", flush=True)


class Listener(discord.Client):
    async def on_message(self, msg):
        seen[msg.id] = {"t": time.time(), "ref": msg.reference and msg.reference.message_id, "author": msg.author.id}

    async def on_ready(self):
        if getattr(self, "started", False):   # on_ready again after a reconnect: don't start over
            return
        self.started = True
        try:
            for gate, kbit in GATES:
                throttle(kbit)
                await asyncio.sleep(3)
                await network_quality(gate)
                for n in range(1, runs + 1):
                    await one_run(gate, kbit, n)
                    await asyncio.sleep(GAP)
        finally:
            unthrottle()
            await self.close()


intents = discord.Intents.none()
intents.guilds = intents.guild_messages = True
try:
    Listener(intents=intents).run(os.environ["DISCORD_TOKEN"], log_handler=None)
finally:
    unthrottle()
