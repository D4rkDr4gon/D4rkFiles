"""Network tools (GUI): paridad con NetToolsView — interfaz, IP local, gateway y DNS; latencia
(4 pings a gateway, 1.1.1.1, 8.8.8.8 y google.com, en segundo plano); IP pública (ipinfo.io) y
prueba de velocidad (speed.cloudflare.com) a pedido; puertos escuchando (ss -tulnp)."""

from __future__ import annotations

import json
import re
import subprocess
import threading

from . import _lib as L

UI: dict = {}
STATE: dict = {"ping": None, "ping_busy": False, "public": "", "speed": "", "busy": set()}


def T():
    return L.tui_module("nettools")


def bg(name, fn):
    if name in STATE["busy"]:
        return
    STATE["busy"].add(name)

    def run():
        try:
            fn()
        finally:
            STATE["busy"].discard(name)
    threading.Thread(target=run, daemon=True).start()


def do_ping():
    t = T()
    info = t.local_info()
    rows = []
    for name, host in t.PING_TARGETS:
        host = host or info["gateway"]
        if host:
            rows.append((name, host, *t.ping(host)))
    STATE["ping"] = rows


def do_public():
    r = L.run(["curl", "-s", "--max-time", "8", "https://ipinfo.io/json"], timeout=12)
    try:
        d = json.loads(r.stdout)
        STATE["public"] = f"{d.get('ip')} · {d.get('org', '')} · {d.get('city', '')}, {d.get('country', '')}"
    except ValueError:
        STATE["public"] = "could not reach ipinfo.io"


def do_speed():
    STATE["speed"] = "testing… (25 MB down, 10 MB up)"
    down = L.run(["curl", "-s", "-o", "/dev/null", "--max-time", "40", "-w", "%{speed_download}",
                  "https://speed.cloudflare.com/__down?bytes=25000000"], timeout=45)
    try:
        up = subprocess.run(["curl", "-s", "-o", "/dev/null", "--max-time", "40", "-w", "%{speed_upload}", "--data-binary", "@-",
                             "https://speed.cloudflare.com/__up"], input=b"0" * 10_000_000, capture_output=True, timeout=45).stdout.decode()
    except (OSError, subprocess.TimeoutExpired):
        up = "0"
    try:
        STATE["speed"] = f"↓ {float(down.stdout or 0) * 8 / 1e6:.0f} Mbit/s · ↑ {float(up or 0) * 8 / 1e6:.0f} Mbit/s"
    except ValueError:
        STATE["speed"] = "speed test failed"


def get() -> dict:
    t = T()
    if STATE["ping"] is None:
        bg("ping", do_ping)
    i = t.local_info()
    conn = [L.info("dev", "Interface", i["dev"] or "—"), L.info("ip", "Local IP", i["ip"] or "—"),
            L.info("gw", "Gateway", i["gateway"] or "—"), L.info("dns", "DNS", ", ".join(i["dns"]) or "—"),
            L.button("public", "Public IP", STATE["public"] or "Look it up on ipinfo.io",
                     "…" if "public" in STATE["busy"] else "Look up"),
            L.button("speed", "Speed", STATE["speed"] or "Speed test against speed.cloudflare.com",
                     "…" if "speed" in STATE["busy"] else "Run")]
    lat = []
    for name, host, ms, loss in STATE["ping"] or []:
        lat.append(L.item(f"p:{host}", name, sub=f"{host} · loss {loss:.0f}%",
                          right="✗ unreachable" if ms is None else f"{ms:.0f} ms", on=ms is not None and ms < 120 and loss == 0,
                          glyph="󰓅"))
    if not lat:
        lat = [L.info("busy", "Pinging…", "4 packets per target")]
    lat.append(L.button("ping", "Ping again", "Gateway, Cloudflare, Google DNS and google.com", "…" if "ping" in STATE["busy"] else "Ping"))
    ports = []
    for line in L.run(["ss", "-tulnpH"]).stdout.splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        proc = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        ports.append(L.info(f"port:{f[0]}:{f[4]}", f"{f[0]} {f[4]}", f"{proc.group(1)} ({proc.group(2)})" if proc else "— (other user)"))
    return L.page("Network tools", "Connection, latency, public IP, speed and listening ports", [
        L.group("Network", conn), L.group("Latency", lat), L.group(f"Listening ports · {len(ports)}", ports)],
        refresh=2 if STATE["busy"] else 10)


def set_value(key, value):
    return L.fail("Unknown setting")


def act(key: str, text=None):
    if key == "ping":
        bg("ping", do_ping)
        return L.ok("Pinging…")
    if key == "public":
        bg("public", do_public)
        return L.ok("Looking up the public IP…")
    if key == "speed":
        bg("speed", do_speed)
        return L.ok("Speed test running…")
    return L.ok()
