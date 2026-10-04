"""Network tools — datos de red, latencia, test de velocidad y puertos abiertos.

Lo que sale a internet (IP pública vía ipinfo.io, test de velocidad contra
speed.cloudflare.com) se corre solo cuando se pide (i / s), nunca al abrir.
"""

from __future__ import annotations

import json
import re
import subprocess

from common import run
from dtui import THEME, DView, Panel, Table, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static

PING_TARGETS = [("Gateway", None), ("Cloudflare DNS", "1.1.1.1"), ("Google DNS", "8.8.8.8"),
                ("google.com", "google.com")]


def local_info() -> dict:
    route = run(["ip", "-j", "route", "show", "default"]).stdout
    try:
        r = json.loads(route or "[]")[0]
    except (ValueError, IndexError):
        r = {}
    dev, gw = r.get("dev", ""), r.get("gateway", "")
    ip4 = ""
    if dev:
        try:
            addrs = json.loads(run(["ip", "-j", "-4", "addr", "show", dev]).stdout or "[]")
            ip4 = addrs[0]["addr_info"][0]["local"]
        except (ValueError, IndexError, KeyError):
            pass
    dns = re.findall(r"Current DNS Server: (\S+)", run(["resolvectl", "status"]).stdout)
    return {"dev": dev, "gateway": gw, "ip": ip4, "dns": sorted(set(dns))}


def ping(host: str) -> tuple[float | None, float]:
    """(latencia media en ms | None, % de pérdida) con 4 paquetes."""
    r = run(["ping", "-c", "4", "-i", "0.2", "-W", "2", host], timeout=15)
    loss = re.search(r"([\d.]+)% packet loss", r.stdout)
    avg = re.search(r"= [\d.]+/([\d.]+)/", r.stdout)
    return (float(avg.group(1)) if avg else None), (float(loss.group(1)) if loss else 100.0)


class NetToolsView(DView):
    FOCUS = "#net-ping"
    DEFAULT_CSS = css("""
    #net-info-panel { height: auto; }
    #net-info { height: auto; }
    #net-ping-panel { height: auto; }
    #net-ping { height: auto; }
    #net-ports-panel { height: 1fr; }
    """)
    BINDINGS = [Binding("p", "ping", "ping again"), Binding("s", "speed", "speed test"),
                Binding("i", "public_ip", "public IP")]

    def compose(self) -> ComposeResult:
        yield Panel(Static(id="net-info"), title="󰛳  Network", id="net-info-panel")
        yield Panel(Table(id="net-ping"), title="Latency", id="net-ping-panel")
        yield Panel(Table(id="net-ports"), title="Listening ports", id="net-ports-panel")

    def on_mount(self) -> None:
        p = self.query_one("#net-ping", Table)
        p.add_column("Target", key="name", width=22)
        p.add_column("Host", key="host", width=18)
        p.add_column("Latency", key="ms", width=24)
        p.add_column("Loss", key="loss", width=10)
        o = self.query_one("#net-ports", Table)
        o.add_column("Proto", key="proto", width=7)
        o.add_column("Address", key="addr", width=28)
        o.add_column("Process", key="proc", width=40)
        self.public = ""
        self.speed = ""
        self.info = local_info()
        self.show_info()
        self.load_ports()
        self.action_ping()

    def hints(self) -> list[tuple[str, str]]:
        return [("p", "ping again"), ("s", "speed test"), ("i", "public IP"), ("q", "quit")]

    def show_info(self) -> None:
        i, muted = self.info, THEME["muted"]
        t = Text()

        def row(label: str, value: str, style: str = "") -> None:
            t.append(f"{label:<12}", style=f"bold {muted}")
            t.append(value + "\n", style=style)

        row("Interface", i["dev"] or "—")
        row("Local IP", i["ip"] or "—")
        row("Gateway", i["gateway"] or "—")
        row("DNS", ", ".join(i["dns"]) or "—")
        row("Public IP", self.public or "press i to look it up (ipinfo.io)", "" if self.public else muted)
        row("Speed", self.speed or "press s to run a speed test (speed.cloudflare.com)",
            "" if self.speed else muted)
        self.query_one("#net-info", Static).update(t)

    def load_ports(self) -> None:
        o = self.query_one("#net-ports", Table)
        o.clear()
        for line in run(["ss", "-tulnpH"]).stdout.splitlines():
            f = line.split()
            if len(f) < 5:
                continue
            proc = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
            o.add_row(f[0], f[4], Text(f"{proc.group(1)} ({proc.group(2)})" if proc else "— (other user)",
                                       style="" if proc else THEME["muted"]))
        self.query_one("#net-ports-panel").border_subtitle = f" {o.row_count} · ss -tulnp "

    @work(thread=True, exclusive=True, group="net-ping")
    def action_ping(self) -> None:
        rows = []
        for name, host in PING_TARGETS:
            host = host or self.info["gateway"]
            if not host:
                continue
            rows.append((name, host, *ping(host)))
        self.app.call_from_thread(self.show_ping, rows)

    def show_ping(self, rows: list) -> None:
        p = self.query_one("#net-ping", Table)
        p.clear()
        for name, host, ms, loss in rows:
            if ms is None:
                lat = Text("✗ unreachable", style=THEME["status_error"])
            else:
                c = THEME["status_ok"] if ms < 40 else THEME["status_warn"] if ms < 120 else THEME["status_error"]
                lat = Text(f"{'▮' * max(1, min(10, int(ms // 15) + 1))} {ms:.0f} ms", style=c)
            p.add_row(name, Text(host, style=THEME["muted"]), lat,
                      Text(f"{loss:.0f}%", style=THEME["status_ok"] if loss == 0 else THEME["status_warn"]))

    @work(thread=True, exclusive=True, group="net-ip")
    def action_public_ip(self) -> None:
        r = run(["curl", "-s", "--max-time", "8", "https://ipinfo.io/json"])
        try:
            d = json.loads(r.stdout)
            self.public = f"{d.get('ip')} · {d.get('org', '')} · {d.get('city', '')}, {d.get('country', '')}"
        except ValueError:
            self.public = "could not reach ipinfo.io"
        self.app.call_from_thread(self.show_info)

    @work(thread=True, exclusive=True, group="net-speed")
    def action_speed(self) -> None:
        self.speed = "testing… (25 MB down, 10 MB up)"
        self.app.call_from_thread(self.show_info)
        down = run(["curl", "-s", "-o", "/dev/null", "--max-time", "40", "-w", "%{speed_download}",
                    "https://speed.cloudflare.com/__down?bytes=25000000"], timeout=45)
        try:
            up = subprocess.run(["curl", "-s", "-o", "/dev/null", "--max-time", "40", "-w", "%{speed_upload}",
                                 "--data-binary", "@-", "https://speed.cloudflare.com/__up"],
                                input=b"0" * 10_000_000, capture_output=True, timeout=45).stdout.decode()
        except (OSError, subprocess.TimeoutExpired):
            up = "0"
        try:
            d_mbps, u_mbps = float(down.stdout or 0) * 8 / 1e6, float(up or 0) * 8 / 1e6
            self.speed = f"↓ {d_mbps:.0f} Mbit/s · ↑ {u_mbps:.0f} Mbit/s"
        except ValueError:
            self.speed = "speed test failed"
        self.app.call_from_thread(self.show_info)
