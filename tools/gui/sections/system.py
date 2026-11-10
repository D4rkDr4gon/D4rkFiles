"""System (GUI): paridad con SystemView — cuatro pestañas: Overview (host, CPU, memoria, swap,
discos, temperaturas, ventiladores, hardware), Processes (los que más consumen en vivo; orden por
CPU o memoria; terminar o matar con confirmación), Boot (tiempo de arranque, unidades más lentas
y errores del journal agrupados) y Doctor (dotfiles-doctor con el detalle de cada aviso)."""

from __future__ import annotations

import json
import os
import platform
import pwd
import re
import shutil
import signal
import threading
import time
from collections import Counter
from pathlib import Path

from . import _lib as L

UI: dict = {}
STATE: dict = {"sort": "cpu", "prev": {}, "prev_t": 0.0, "procs": {}, "boot": None, "errs": {}, "doctor": None, "doctor_busy": False,
               "items": {}}
TABS = [("overview", "Overview"), ("procs", "Processes"), ("boot", "Boot"), ("doctor", "Doctor")]


def T():
    return L.tui_module("system")


def bar(pct: float) -> str:
    k = max(0, min(10, round(pct / 10)))
    return "▓" * k + "░" * (10 - k) + f" {pct:3.0f}%"


def page_overview() -> list:
    t = T()
    up = int(float(Path("/proc/uptime").read_text().split()[0]))
    load, cpus = os.getloadavg()[0], os.cpu_count() or 1
    mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in Path("/proc/meminfo").read_text().splitlines()
           if ln.split(":")[0] in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")}
    used = mem["MemTotal"] - mem["MemAvailable"]
    rows = [L.info("host", "Host", f"{platform.node()} · kernel {platform.release()} · up {up // 86400} d {up % 86400 // 3600} h {up % 3600 // 60} min"),
            L.info("cpu", "CPU", f"{bar(min(100.0, load * 100 / cpus))} · load {load:.2f} on {cpus} cores"),
            L.info("mem", "Memory", f"{bar(used * 100 / mem['MemTotal'])} · {used / 2**20:.1f} of {mem['MemTotal'] / 2**20:.1f} GB")]
    if mem.get("SwapTotal"):
        su = mem["SwapTotal"] - mem["SwapFree"]
        rows.append(L.info("swap", "Swap", f"{bar(su * 100 / mem['SwapTotal'])} · {su / 2**20:.1f} of {mem['SwapTotal'] / 2**20:.1f} GB"))
    for mount in ("/", "/files"):
        if Path(mount).exists():
            du = shutil.disk_usage(mount)
            rows.append(L.info(f"disk{mount}", f"Disk {mount}", f"{bar(du.used * 100 / du.total)} · {du.used / 2**30:.0f} of "
                               f"{du.total / 2**30:.0f} GB · {du.free / 2**30:.0f} GB free"))
    temps = [L.info(f"t{i}", name, f"{v:.0f}°C" + (f" · {bar(v * 100 / lim)}" if lim and lim > 30 else ""))
             for i, (name, v, lim) in enumerate(t.temperatures())]
    temps += [L.info(f"f{i}", name, f"{rpm} rpm" if rpm else "stopped") for i, (name, rpm) in enumerate(t.fans())]
    hw = [L.info(f"hw{i}", label, value) for i, (label, value) in enumerate(t.hardware())]
    return [L.group("Overview", rows), L.group("Temperatures and fans", temps or [L.info("none", "No sensors found", "")]),
            L.group("Hardware", hw)]


def page_procs() -> list:
    t = T()
    now, cur = time.monotonic(), t.read_procs()
    dt = now - STATE["prev_t"] if STATE["prev_t"] else 0
    rows = []
    for pid, (comm, ticks, rss, uid) in cur.items():
        before = STATE["prev"].get(pid)
        cpu = ((ticks - before[1]) / t.CLK / dt * 100) if before and dt > 0 else 0.0
        rows.append((pid, comm, cpu, rss, uid))
    STATE["prev"], STATE["prev_t"] = cur, now
    rows.sort(key=(lambda r: r[2]) if STATE["sort"] == "cpu" else (lambda r: r[3]), reverse=True)
    q = (UI.get("search") or "").lower()
    ncpu = os.cpu_count() or 1
    items = []
    STATE["procs"] = {}
    for pid, comm, cpu, rss, uid in rows:
        if q and q not in comm.lower() and q != str(pid):
            continue
        if len(items) >= 60:
            break
        try:
            user = pwd.getpwuid(uid).pw_name
        except KeyError:
            user = str(uid)
        STATE["procs"][str(pid)] = (pid, comm)
        items.append(L.item(f"proc:{pid}", comm, sub=f"PID {pid} · {user} · {rss / 2**20:,.0f} MB", right=f"{cpu / ncpu:5.1f}%",
                            on=cpu / ncpu < 20, glyph="󰍛",
                            actions=[L.action(f"term:{pid}", "Terminate", True), L.action(f"kill:{pid}", "Kill", True)]))
    head = [L.choice("sort", "Sort by", "CPU is % of the whole machine", STATE["sort"], ["cpu", "mem"])]
    return [L.group("Processes", head), L.group(f"Top 60 by {'CPU' if STATE['sort'] == 'cpu' else 'memory'}", items)]


def load_boot():
    summary = L.run(["systemd-analyze"], timeout=20).stdout.strip().splitlines()[:1]
    blame = L.run(["systemd-analyze", "blame", "--no-pager"], timeout=20).stdout.splitlines()[:25]
    j = L.run(["journalctl", "-b", "-p", "err", "-o", "json", "--no-pager", "-n", "800"], timeout=30).stdout
    groups: dict[str, list[str]] = {}
    for line in j.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        msg = e.get("MESSAGE") or ""
        if isinstance(msg, list):
            msg = bytes(msg).decode(errors="replace")
        groups.setdefault(e.get("SYSLOG_IDENTIFIER") or e.get("_COMM") or "?", []).append(str(msg))
    STATE["boot"] = (summary[0] if summary else "systemd-analyze unavailable", blame)
    STATE["errs"] = groups


def page_boot() -> list:
    if STATE["boot"] is None:
        load_boot()
    summary, blame = STATE["boot"]
    rows = []
    for i, line in enumerate(blame):
        tm, _, unit = line.strip().partition(" ")
        secs = re.search(r"([\d.]+)s", tm)
        slow = bool(secs) and float(secs.group(1)) >= 5 and "min" not in tm
        rows.append(L.item(f"blame:{i}", unit.strip(), right=tm.strip(), on=not slow, glyph="󰔟"))
    counts = Counter({k: len(v) for k, v in STATE["errs"].items()})
    errs = [L.item(f"err:{src}", src, sub=" ".join(STATE["errs"][src][-1].split())[:100], right=str(n), on=False, glyph="",
                   actions=[L.action(f"err:{src}", "Read")]) for src, n in counts.most_common(25)]
    return [L.group("Boot", [L.info("sum", "Startup", summary), L.button("reboot-load", "Reload", "", "Reload")]),
            L.group("Slowest units", rows),
            L.group(f"Errors this boot · {sum(counts.values())} from {len(counts)} sources" if counts else "Errors this boot",
                    errs or [L.info("none", "No errors this boot", "✓")])]


def run_doctor():
    STATE["doctor_busy"] = True
    try:
        r = L.run(["bash", str(L.DOTFILES / "scripts" / "dotfiles-doctor.sh")], timeout=120, cwd=L.DOTFILES)
        STATE["doctor"] = T().parse_doctor(r.stdout + r.stderr)
    finally:
        STATE["doctor_busy"] = False


def page_doctor() -> list:
    if STATE["doctor"] is None and not STATE["doctor_busy"]:
        threading.Thread(target=run_doctor, daemon=True).start()
    if STATE["doctor"] is None:
        return [L.group("Doctor", [L.info("busy", "dotfiles-doctor", "running…")])]
    rows, summary = STATE["doctor"]
    groups = [L.group("Doctor", [L.info("sum", "Summary", summary.removeprefix("Resumen: ") + (" · running again…" if STATE["doctor_busy"] else "")),
                                 L.button("doctor", "Run again", "links, packages, services, configs, repo", "Run")])]
    cur = None
    STATE["items"] = {}
    glyph = {"ok": "✓", "warn": "⚠", "err": "✗", "info": "i"}
    for key, st, msg, det in rows:
        if st == "head":
            cur = L.group(msg, [])
            groups.append(cur)
            continue
        if cur is None:
            cur = L.group("Checks", [])
            groups.append(cur)
        STATE["items"][key] = (msg, det)
        cur["rows"].append(L.item(f"doc:{key}", f"{glyph[st]} {msg}", sub=det.splitlines()[0] if det else "", on=st in ("ok", "info"),
                                  glyph=""))
    return groups


def get() -> dict:
    tab = UI.get("tab") or "overview"
    groups = {"overview": page_overview, "procs": page_procs, "boot": page_boot, "doctor": page_doctor}[tab]()
    p = L.page("System", "Overview, processes, boot and doctor", groups,
               refresh={"overview": 3, "procs": 2, "doctor": 2 if STATE["doctor_busy"] or STATE["doctor"] is None else 0}.get(tab, 0))
    p.update(tabs=[{"key": k, "label": lbl} for k, lbl in TABS], tab=tab, search="Filter processes…" if tab == "procs" else "")
    return p


def set_value(key, value):
    if key == "sort":
        STATE["sort"] = value
        return L.ok()
    return L.fail("Unknown setting")


def act(key: str, text=None):
    t = T()
    op, _, arg = key.partition(":")
    if op in ("term", "kill"):
        p = STATE["procs"].get(arg)
        if not p:
            return L.ok()
        pid, comm = p
        sig = signal.SIGTERM if op == "term" else signal.SIGKILL
        if not L.yes(text):
            extra = "\n\nThis is part of your session: it may close or log you out." if comm.startswith(t.PROTECTED) else ""
            return L.confirm(key, f"Send {sig.name}", f"{comm} (PID {pid}){extra}", ok_label="Terminate" if op == "term" else "Kill")
        try:
            os.kill(pid, sig)
            return L.ok(f"{sig.name} sent to {comm} ({pid})")
        except ProcessLookupError:
            return L.fail("That process is already gone")
        except PermissionError:
            return L.fail("Not allowed: it belongs to another user")
    if op == "err":
        msgs = STATE["errs"].get(arg, [])
        return L.text_view(f"{arg} · {len(msgs)} errors", "\n\n".join(msgs[-30:]))
    if op == "reboot-load":
        load_boot()
        return L.ok()
    if op == "doctor":
        if not STATE["doctor_busy"]:
            threading.Thread(target=run_doctor, daemon=True).start()
        return L.ok("Running dotfiles-doctor…")
    if op == "doc":
        msg, det = STATE["items"].get(arg, ("", ""))
        return L.text_view(msg[:60] or "Detail", f"{msg}\n\n{det or '(no extra detail)'}")
    return L.ok()
