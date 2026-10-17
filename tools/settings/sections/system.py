"""System — estado del equipo en cuatro páginas (tab o 1-4 para cambiar):

1 Overview   host, CPU, memoria, swap y discos; temperaturas y ventiladores (hwmon); hardware.
2 Processes  los que más consumen, en vivo; s ordena por CPU/memoria, k termina (SIGTERM), K mata (SIGKILL).
3 Boot       cuánto tardó el arranque, las unidades más lentas y los errores del journal de este arranque.
4 Doctor     dotfiles-doctor en segundo plano (links, paquetes, servicios, configs, repo) con el detalle de cada aviso.

Todo es de solo lectura salvo terminar un proceso (con confirmación). Las páginas lentas (Boot, Doctor) se
cargan en un worker la primera vez que se abren; r las recarga.
"""

from __future__ import annotations

import json
import os
import platform
import pwd
import re
import shutil
import signal
import subprocess
import time
from collections import Counter
from pathlib import Path

from common import DOTFILES, run
from dtui import THEME, Card, ConfirmModal, DView, Panel, Table, TextModal, css, meter10
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, DataTable, Static

PAGES = [("overview", "Overview"), ("procs", "Processes"), ("boot", "Boot"), ("doctor", "Doctor")]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HWMON_SKIP = ("BAT", "hidpp", "ucsi", "ac")      # baterías y cargadores: no son temperaturas del equipo
CLK = os.sysconf("SC_CLK_TCK")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
PROTECTED = ("Hyprland", "systemd", "Xwayland", "dbus-broker", "pipewire", "wireplumber", "kitty", "waybar")


# ── datos ─────────────────────────────────────────────────

def temperatures() -> list[tuple[str, float, float | None]]:
    """[(nombre, °C, límite alto/crítico o None)] de /sys/class/hwmon."""
    out = []
    for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            chip = (hw / "name").read_text().strip()
        except OSError:
            continue
        if chip.startswith(HWMON_SKIP):
            continue
        for f in sorted(hw.glob("temp*_input")):
            try:
                value = int(f.read_text()) / 1000
            except (OSError, ValueError):
                continue
            base = f.name.removesuffix("_input")
            label = (hw / f"{base}_label")
            name = f"{chip} {label.read_text().strip()}" if label.exists() else chip
            limit = None
            for kind in ("crit", "max"):
                try:
                    limit = int((hw / f"{base}_{kind}").read_text()) / 1000
                    break
                except (OSError, ValueError):
                    pass
            out.append((name, value, limit))
    return out


def fans() -> list[tuple[str, int]]:
    out = []
    for f in sorted(Path("/sys/class/hwmon").glob("hwmon*/fan*_input")):
        try:
            out.append((f"{(f.parent / 'name').read_text().strip()} {f.name.split('_')[0]}", int(f.read_text())))
        except (OSError, ValueError):
            pass
    return out


def hardware() -> list[tuple[str, str]]:
    def dmi(name: str) -> str:
        try:
            return (Path("/sys/class/dmi/id") / name).read_text().strip()
        except OSError:
            return ""

    rows = []
    osr = {}
    try:
        osr = dict(l.split("=", 1) for l in Path("/etc/os-release").read_text().splitlines() if "=" in l)
    except OSError:
        pass
    rows.append(("OS", f"{osr.get('PRETTY_NAME', 'Linux').strip(chr(34))} · kernel {platform.release()}"))
    model = " ".join(filter(None, (dmi("sys_vendor"), dmi("product_version") or dmi("product_name"))))
    rows.append(("Machine", model or "?"))
    bios = " ".join(filter(None, (dmi("bios_version"), dmi("bios_date"))))
    if bios:
        rows.append(("BIOS", bios))
    try:
        cpus = [l.split(":", 1)[1].strip() for l in Path("/proc/cpuinfo").read_text().splitlines()
                if l.startswith("model name")]
        rows.append(("CPU", f"{cpus[0]} · {len(cpus)} threads" if cpus else "?"))
    except OSError:
        pass
    pci = run(["lspci", "-mm"]).stdout.splitlines() if shutil.which("lspci") else []
    for l in pci:
        parts = re.findall(r'"([^"]*)"', l)
        if parts and re.search(r"VGA|3D|Display", parts[0]):
            rows.append(("GPU", f"{parts[2]} {parts[3]}".replace("Corporation ", "").strip()))
    mem = Path("/proc/meminfo").read_text().splitlines()[0].split()[1]
    rows.append(("Memory", f"{int(mem) / 2**20:.1f} GB"))
    lsblk = run(["lsblk", "-dno", "NAME,SIZE,MODEL,TRAN", "-e", "7,11"]).stdout.splitlines()
    for l in lsblk:
        if l.startswith(("zram", "loop")):
            continue
        rows.append(("Disk", " ".join(l.split())))
    return rows


def read_procs() -> dict[int, tuple[str, int, int, int]]:
    """{pid: (comm, ticks de CPU acumulados, RSS en bytes, uid)} desde /proc."""
    out = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            data = (d / "stat").read_text()
            comm = data[data.index("(") + 1:data.rindex(")")]
            rest = data[data.rindex(")") + 2:].split()
            out[int(d.name)] = (comm, int(rest[11]) + int(rest[12]), int(rest[21]) * PAGE_SIZE, d.stat().st_uid)
        except (OSError, ValueError, IndexError):
            continue
    return out


def parse_doctor(text: str) -> tuple[list[tuple[str, str, str, str]], str]:
    """Salida de dotfiles-doctor → ([(clave, estado, mensaje, detalle)], resumen). Estado: ok/warn/err/info/head."""
    rows, summary, last = [], "", None
    for raw in ANSI.sub("", text).splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("══"):
            rows.append((f"hdr:{len(rows)}", "head", line.strip("═ ").strip(), ""))
            last = None
        elif line.startswith("Resumen"):
            summary = line
        elif line.startswith("      ") and last is not None:
            k, st, msg, det = rows[last]
            rows[last] = (k, st, msg, (det + "\n" if det else "") + line.strip())
        elif m := re.match(r"\s{2}(⚠|✗|✓|i|→)\s+(.*)", line):
            st = {"⚠": "warn", "✗": "err", "✓": "ok", "i": "info", "→": "ok"}[m.group(1)]
            rows.append((f"item:{len(rows)}", st, m.group(2), ""))
            last = len(rows) - 1
    return rows, summary


# ── vista ─────────────────────────────────────────────────

class SystemView(DView):
    FOCUS = "#sysinfo"
    DEFAULT_CSS = css("""
    #sys-tabs { height: 1; padding: 0 1; }
    #sys-pages { height: 1fr; }
    #sysinfo-panel { height: auto; }
    #sysinfo, #temps, #hw { height: auto; }
    #ov-bottom { height: auto; }
    #temps-panel { width: 1fr; }
    #hw-panel { width: 1fr; }
    #boot-row { height: 1fr; }
    #blame-panel { width: 1fr; }
    #errors-panel { width: 1fr; }
    #doctor-panel { height: 1fr; }
    #doctor-detail-panel { height: 8; }
    """)
    BINDINGS = [
        Binding("1", "page('overview')", "overview", show=False),
        Binding("2", "page('procs')", "processes", show=False),
        Binding("3", "page('boot')", "boot", show=False),
        Binding("4", "page('doctor')", "doctor", show=False),
        Binding("tab", "next_page(1)", "next page", show=False),
        Binding("shift+tab", "next_page(-1)", "previous page", show=False),
        Binding("s", "sort", "sort"),
        Binding("k", "kill", "terminate"),
        Binding("K", "kill9", "kill"),
        Binding("r", "reload_page", "reload"),
    ]

    page = "overview"
    sort = "cpu"

    def compose(self) -> ComposeResult:
        yield Static(id="sys-tabs")
        with ContentSwitcher(initial="overview", id="sys-pages"):
            with Vertical(id="overview"):
                yield Panel(Card(id="sysinfo"), title="󰌢  System", id="sysinfo-panel")
                with Horizontal(id="ov-bottom"):
                    yield Panel(Static(id="temps"), title="󰔏  Temperatures", id="temps-panel")
                    yield Panel(Static(id="hw"), title="󰘚  Hardware", id="hw-panel")
            with Vertical(id="procs-page"):
                yield Panel(Table(id="procs"), title="󰓅  Processes", id="procs-panel")
            with Vertical(id="boot"):
                yield Static(id="boot-summary")
                with Horizontal(id="boot-row"):
                    yield Panel(Table(id="blame"), title="󰔟  Slowest units", id="blame-panel")
                    yield Panel(Table(id="errors"), title="  Errors this boot", id="errors-panel")
            with Vertical(id="doctor"):
                yield Panel(Table(id="doctor-table", show_header=False), title="󰓙  dotfiles doctor", id="doctor-panel")
                yield Panel(Static(id="doctor-detail"), title="Detail", id="doctor-detail-panel")

    def on_mount(self) -> None:
        p = self.query_one("#procs", Table)
        for key, label, w in (("pid", "PID", 8), ("user", "User", 12), ("cpu", "CPU", 8),
                              ("mem", "Memory", 10), ("cmd", "Command", 40)):
            p.add_column(label, key=key, width=w)
        b = self.query_one("#blame", Table)
        b.add_column("Time", key="t", width=10)
        b.add_column("Unit", key="u", width=40)
        e = self.query_one("#errors", Table)
        e.add_column("Count", key="n", width=7)
        e.add_column("Source", key="s", width=26)
        e.add_column("Last message", key="m", width=60)
        d = self.query_one("#doctor-table", Table)
        d.add_column("", key="st", width=3)
        d.add_column("", key="msg", width=150)
        self.prev: dict[int, tuple[str, int, int, int]] = {}
        self.prev_t = 0.0
        self.loaded: set[str] = set()
        self.proc_rows: dict[str, tuple[int, str]] = {}
        self.err_groups: dict[str, list[str]] = {}
        self.doctor_items: dict[str, tuple[str, str]] = {}
        self.update_overview()
        self.query_one("#hw", Static).update(self.hw_text())
        self.render_tabs()
        self.set_interval(2, self.tick)

    def on_show(self) -> None:
        if self.is_mounted:
            self.update_overview()

    # ── páginas ──

    def render_tabs(self) -> None:
        t = Text()
        for i, (pid, label) in enumerate(PAGES, 1):
            on = pid == self.page
            t.append(f" {i} {label} ", style=f"bold reverse {THEME['primary']}" if on else THEME["muted"])
            t.append("  ")
        self.query_one("#sys-tabs", Static).update(t)

    def action_page(self, name: str) -> None:
        self.page = name
        self.query_one("#sys-pages", ContentSwitcher).current = "procs-page" if name == "procs" else name
        self.render_tabs()
        # cada página enfoca algo: sin foco las teclas (1-4, tab) no le llegan a la vista
        self.query_one({"overview": "#sysinfo", "procs": "#procs", "boot": "#errors",
                        "doctor": "#doctor-table"}[name]).focus()
        if name == "procs":
            self.sample_procs()
        elif name == "boot" and "boot" not in self.loaded:
            self.load_boot()
        elif name == "doctor" and "doctor" not in self.loaded:
            self.load_doctor()
        self.update_hints()

    def action_next_page(self, step: int) -> None:
        ids = [p for p, _ in PAGES]
        self.action_page(ids[(ids.index(self.page) + step) % len(ids)])

    def action_reload_page(self) -> None:
        if self.page == "boot":
            self.load_boot()
        elif self.page == "doctor":
            self.load_doctor()
        elif self.page == "overview":
            self.update_overview()

    def hints(self) -> list[tuple[str, str]]:
        base = [("tab", "page"), ("1-4", "jump")]
        if self.page == "procs":
            return [("s", f"sort: {self.sort}"), ("k", "terminate"), ("K", "kill")] + base + [("q", "quit")]
        if self.page in ("boot", "doctor"):
            return [("r", "reload")] + base + [("q", "quit")]
        return base + [("q", "quit")]

    def tick(self) -> None:
        if not self.visible_now:
            return
        if self.page == "overview":
            self.update_overview()
        elif self.page == "procs":
            self.sample_procs()

    # ── 1 · Overview ──

    def update_overview(self) -> None:
        info = Text()

        def row(label: str, value: Text | str) -> None:
            info.append(f"{label:<13}", style=f"bold {THEME['muted']}")
            info.append(value if isinstance(value, Text) else Text(value))
            info.append("\n")

        up = int(float(Path("/proc/uptime").read_text().split()[0]))
        row("Host", f"{platform.node()} · kernel {platform.release()} · "
                    f"up {up // 86400} d {up % 86400 // 3600} h {up % 3600 // 60} min")
        load = os.getloadavg()[0]
        cpus = os.cpu_count() or 1
        m = meter10(min(100.0, load * 100 / cpus))
        m.append(f"  load {load:.2f} on {cpus} cores", style=THEME["muted"])
        row("CPU", m)
        mem = {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines()
               if l.split(":")[0] in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")}
        used = mem["MemTotal"] - mem["MemAvailable"]
        m = meter10(used * 100 / mem["MemTotal"])
        m.append(f"  {used / 2**20:.1f} of {mem['MemTotal'] / 2**20:.1f} GB", style=THEME["muted"])
        row("Memory", m)
        if mem.get("SwapTotal"):
            su = mem["SwapTotal"] - mem["SwapFree"]
            m = meter10(su * 100 / mem["SwapTotal"])
            m.append(f"  {su / 2**20:.1f} of {mem['SwapTotal'] / 2**20:.1f} GB", style=THEME["muted"])
            row("Swap", m)
        for mount in ("/", "/files"):
            if Path(mount).exists():
                du = shutil.disk_usage(mount)
                m = meter10(du.used * 100 / du.total)
                m.append(f"  {du.used / 2**30:.0f} of {du.total / 2**30:.0f} GB · {du.free / 2**30:.0f} GB free",
                         style=THEME["muted"])
                row(f"Disk {mount}", m)
        self.query_one("#sysinfo", Static).update(info)
        self.query_one("#temps", Static).update(self.temps_text())

    def temps_text(self) -> Text:
        t = Text()
        temps = temperatures()
        for name, value, limit in temps:
            pct = value * 100 / (limit if limit and limit > 30 else 100)
            t.append(f"{name:<24.24}", style=THEME["muted"])
            t.append_text(meter10(min(100.0, pct), label=False))
            t.append("  ")
            t.append(f"{value:.0f}°C\n")
        for name, rpm in fans():
            t.append(f"{name:<24.24}", style=THEME["muted"])
            t.append(f"{rpm} rpm\n" if rpm else "stopped\n")
        return t if temps else Text("no sensors found", style=THEME["muted"])

    def hw_text(self) -> Text:
        t = Text()
        for label, value in hardware():
            t.append(f"{label:<9}", style=f"bold {THEME['muted']}")
            t.append(value + "\n")
        return t

    # ── 2 · Processes ──

    @work(thread=True, exclusive=True, group="procs")
    def sample_procs(self) -> None:
        now, cur = time.monotonic(), read_procs()
        dt = now - self.prev_t if self.prev_t else 0
        rows = []
        for pid, (comm, ticks, rss, uid) in cur.items():
            before = self.prev.get(pid)
            cpu = ((ticks - before[1]) / CLK / dt * 100) if before and dt > 0 else 0.0
            rows.append((pid, comm, cpu, rss, uid))
        self.prev, self.prev_t = cur, now
        key = (lambda r: r[2]) if self.sort == "cpu" else (lambda r: r[3])
        rows.sort(key=key, reverse=True)
        self.app.call_from_thread(self.show_procs, rows[:60])

    def show_procs(self, rows: list) -> None:
        ncpu = os.cpu_count() or 1
        out = []
        self.proc_rows = {}
        for pid, comm, cpu, rss, uid in rows:
            try:
                user = pwd.getpwuid(uid).pw_name
            except KeyError:
                user = str(uid)
            cpu_style = THEME["status_error"] if cpu > 60 else THEME["status_warn"] if cpu > 20 else ""
            self.proc_rows[str(pid)] = (pid, comm)
            out.append((str(pid), [str(pid), Text(user, style=THEME["muted"]),
                                   Text(f"{cpu / ncpu:5.1f}%" if cpu else "  0.0%", style=cpu_style),
                                   f"{rss / 2**20:,.0f} MB", comm]))
        self.query_one("#procs", Table).set_rows(out)
        self.query_one("#procs-panel").border_subtitle = f" top 60 by {'CPU' if self.sort == 'cpu' else 'memory'} · CPU is % of the whole machine "

    def action_sort(self) -> None:
        if self.page == "procs":
            self.sort = "mem" if self.sort == "cpu" else "cpu"
            self.update_hints()
            self.sample_procs()

    def signal_selected(self, sig: signal.Signals) -> None:
        if self.page != "procs":
            return
        key = self.query_one("#procs", Table).selected_key()
        if key not in self.proc_rows:
            return
        pid, comm = self.proc_rows[key]
        extra = "\n\nThis is part of your session: it may close or log you out." if comm.startswith(PROTECTED) else ""

        def done(yes: bool) -> None:
            if not yes:
                return
            try:
                os.kill(pid, sig)
                self.app.notify_ok(f"{sig.name} sent to {comm} ({pid})")
            except ProcessLookupError:
                self.app.notify_err("That process is already gone")
            except PermissionError:
                self.app.notify_err("Not allowed: it belongs to another user")
            self.sample_procs()

        self.app.push_screen(ConfirmModal(f"Send {sig.name}", f"{comm} (PID {pid}){extra}"), done)

    def action_kill(self) -> None:
        self.signal_selected(signal.SIGTERM)

    def action_kill9(self) -> None:
        self.signal_selected(signal.SIGKILL)

    # ── 3 · Boot ──

    @work(thread=True, exclusive=True, group="boot")
    def load_boot(self) -> None:
        summary = run(["systemd-analyze"], timeout=20).stdout.strip().splitlines()[:1]
        blame = run(["systemd-analyze", "blame", "--no-pager"], timeout=20).stdout.splitlines()[:25]
        j = run(["journalctl", "-b", "-p", "err", "-o", "json", "--no-pager", "-n", "800"], timeout=30).stdout
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
        self.app.call_from_thread(self.show_boot, summary[0] if summary else "", blame, groups)

    def show_boot(self, summary: str, blame: list[str], groups: dict[str, list[str]]) -> None:
        self.loaded.add("boot")
        self.query_one("#boot-summary", Static).update(Text(" " + (summary or "systemd-analyze unavailable"),
                                                            style=THEME["muted"]))
        rows = []
        for i, line in enumerate(blame):
            t, _, unit = line.strip().partition(" ")
            secs = re.search(r"([\d.]+)s", t)
            slow = bool(secs) and float(secs.group(1)) >= 5 and "min" not in t
            rows.append((f"b{i}", [Text(t.strip(), style=THEME["status_warn"] if slow else ""), unit.strip()]))
        self.query_one("#blame", Table).set_rows(rows)
        self.err_groups = groups
        counts = Counter({k: len(v) for k, v in groups.items()})
        erows = [(src, [Text(str(n), style=THEME["status_error"] if n > 20 else THEME["status_warn"]), src,
                        Text(" ".join(groups[src][-1].split())[:80], style=THEME["muted"])])
                 for src, n in counts.most_common(25)]
        self.query_one("#errors", Table).set_rows(erows)
        self.query_one("#errors-panel").border_subtitle = (
            f" {sum(counts.values())} errors from {len(counts)} sources · enter reads them " if counts
            else " ✓ no errors this boot ")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "errors":
            src = str(event.row_key.value)
            msgs = self.err_groups.get(src, [])
            self.app.push_screen(TextModal(f"{src} · {len(msgs)} errors", "\n\n".join(msgs[-30:]), end=True))

    # ── 4 · Doctor ──

    @work(thread=True, exclusive=True, group="doctor")
    def load_doctor(self) -> None:
        self.app.call_from_thread(self.set_doctor_busy)
        r = run(["bash", str(DOTFILES / "scripts" / "dotfiles-doctor.sh")], timeout=120, cwd=DOTFILES)
        rows, summary = parse_doctor(r.stdout + r.stderr)
        self.app.call_from_thread(self.show_doctor, rows, summary)

    def set_doctor_busy(self) -> None:
        self.query_one("#doctor-panel").border_subtitle = " running… "

    def show_doctor(self, rows: list, summary: str) -> None:
        self.loaded.add("doctor")
        glyph = {"ok": ("✓", THEME["status_ok"]), "warn": ("⚠", THEME["status_warn"]),
                 "err": ("✗", THEME["status_error"]), "info": ("i", THEME["muted"])}
        out, self.doctor_items = [], {}
        for key, st, msg, det in rows:
            if st == "head":
                out.append((key, [Text(msg, style=f"bold {THEME['primary']}"), ""]))
            else:
                g, style = glyph[st]
                out.append((key, [Text(g, style=style), Text(msg, style="" if st != "ok" else THEME["muted"])]))
                self.doctor_items[key] = (msg, det)
        self.query_one("#doctor-table", Table).set_rows(out)
        self.query_one("#doctor-panel").border_subtitle = f" {summary.removeprefix('Resumen: ')} · r runs it again "
        self.show_doctor_detail()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "doctor-table":
            self.show_doctor_detail()

    def show_doctor_detail(self) -> None:
        key = self.query_one("#doctor-table", Table).selected_key()
        msg, det = self.doctor_items.get(key or "", ("", ""))
        t = Text(msg + "\n", style="bold") if msg else Text()
        t.append(det or ("" if not msg else "(no extra detail)"), style=THEME["muted"])
        self.query_one("#doctor-detail", Static).update(t)
