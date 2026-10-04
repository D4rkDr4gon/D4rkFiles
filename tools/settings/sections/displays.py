"""Displays — mapa de monitores, luz nocturna (hyprsunset) y la tablet como
monitor (wayvnc), cada uno en su tarjeta (tab cambia de tarjeta).

- Monitors: los monitores dibujados según su posición y tamaño lógico
  (`hyprctl monitors -j`: resolución / escala, rotación incluida); el que tiene
  foco va marcado. enter abre hyprmon (de terceros) en la misma ventana.
- Night light: temperatura y brillo de la noche con barras (←/→ y -/+ los
  ajustan en vivo por IPC y los guardan en config/hypr/hyprsunset.conf), la franja
  nocturna en una línea de 24 h con la hora actual, enter prende/apaga,
  s el formulario de horario, l el arranque al iniciar sesión.
- Tablet: scripts/wayland/wayvnc-toggle.sh on/off/status.

Todo lo que pregunta a procesos corre en un worker; se refresca al mostrarse
y cada 5 s mientras se ve.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from typing import Optional

import nightlight
from common import DOTFILES, HYPRLAND, run
from dtui import THEME, Card, DView, Field, FormModal, Panel, bar, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding

WAYVNC = DOTFILES / "scripts" / "wayland" / "wayvnc-toggle.sh"
MAP_WIDTH = 64            # columnas del mapa para todo el ancho del escritorio
CHAR_ASPECT = 2.1         # una celda de terminal es ~2 veces más alta que ancha
TEMP_MIN, TEMP_MAX, TEMP_STEP = 2500, 6500, 250
GAMMA_MIN, GAMMA_STEP = 20, 5
TIMELINE = 48             # media hora por celda


def monitors() -> list[dict]:
    if not HYPRLAND:
        return []
    try:
        return [m for m in json.loads(run(["hyprctl", "monitors", "-j"]).stdout or "[]") if not m.get("disabled")]
    except ValueError:
        return []


def tablet_state() -> tuple[bool, str]:
    st = run(["bash", str(WAYVNC), "status"])
    m = re.search(r"([\d.]+:\d+)\s*$", st.stdout.strip())   # "wayvnc activo (PID n) en <ip>:<puerto>"
    return st.returncode == 0, m.group(1) if m else ""


def night_state() -> dict:
    cfg = nightlight.read_conf()
    d = {"installed": nightlight.installed(), "cfg": cfg, "running": False, "on": False,
         "login": run(["systemctl", "--user", "is-enabled", nightlight.UNIT]).stdout.strip() == "enabled"}
    if d["installed"] and HYPRLAND and nightlight.running():
        d["running"] = True
        on = nightlight.filtering()
        d["on"] = nightlight.in_night(cfg) if on is None else on
    return d


# ── dibujo ──

def draw_map(mons: list[dict]) -> Text:
    """Cajas con bordes de línea, ubicadas como en el escritorio."""
    if not mons:
        return Text("Monitor layout is only available on Hyprland", style=THEME["muted"])
    boxes = []
    for m in mons:
        w, h = m["width"] / m["scale"], m["height"] / m["scale"]
        if m.get("transform", 0) % 2:
            w, h = h, w
        boxes.append((m, m["x"], m["y"], w, h))
    minx, miny = min(b[1] for b in boxes), min(b[2] for b in boxes)
    total = max(b[1] + b[3] for b in boxes) - minx
    f = MAP_WIDTH / total
    placed = []
    for m, x, y, w, h in boxes:
        col, row = round((x - minx) * f), round((y - miny) * f / CHAR_ASPECT)
        placed.append((m, col, row, max(18, round(w * f)), max(5, round(h * f / CHAR_ASPECT))))
    width = max(c + w for _m, c, _r, w, _h in placed)
    height = max(r + h for _m, _c, r, _w, h in placed)
    grid = [[(" ", "")] * width for _ in range(height)]
    muted, primary = THEME["muted"], THEME["primary"]
    for m, col, row, w, h in placed:
        style = f"bold {primary}" if m.get("focused") else muted
        for c in range(w):
            grid[row][col + c] = ("─", style)
            grid[row + h - 1][col + c] = ("─", style)
        for r in range(h):
            grid[row + r][col] = ("│", style)
            grid[row + r][col + w - 1] = ("│", style)
        for (r, c), ch in {(0, 0): "╭", (0, w - 1): "╮", (h - 1, 0): "╰", (h - 1, w - 1): "╯"}.items():
            grid[row + r][col + c] = (ch, style)
        lines = [(("● " if m.get("focused") else "") + m["name"], f"bold {primary}" if m.get("focused") else "bold"),
                 (f"{m['width']}x{m['height']}", THEME["foreground"]),
                 (f"{m['refreshRate']:.0f}Hz · {m['scale']:g}x", muted)]
        top = row + max(1, (h - len(lines)) // 2)
        for i, (txt, st) in enumerate(lines):
            txt = txt[:w - 2]
            r = top + i
            if r >= row + h - 1:
                break
            start = col + (w - len(txt)) // 2
            for j, ch in enumerate(txt):
                grid[r][start + j] = (ch, st)
    out = Text()
    for r, line in enumerate(grid):
        for ch, st in line:
            out.append(ch, style=st or None)
        if r < height - 1:
            out.append("\n")
    return out


def hhmm_index(t: str) -> int:
    h, m = (int(x) for x in t.split(":"))
    return (h * 60 + m) // 30


def draw_night(d: dict) -> Text:
    muted, primary = THEME["muted"], THEME["primary"]
    t = Text()
    if not d["installed"]:
        return Text("hyprsunset is not installed: sudo pacman -S hyprsunset", style=THEME["status_warn"])
    cfg = d["cfg"]
    temp, gamma = int(cfg["temperature"]), int(cfg["gamma"])
    t.append("Temperature  ", style=muted)
    t.append_text(bar((TEMP_MAX - temp) * 100 / (TEMP_MAX - TEMP_MIN), 24))
    t.append(f"  {temp}K", style="bold")
    t.append("   ←/→ (→ warmer)\n", style=muted)
    t.append("Brightness   ", style=muted)
    t.append_text(bar(gamma, 24))
    t.append(f"  {gamma}%", style="bold")
    t.append("   -/+\n\n", style=muted)
    t.append("Schedule     ", style=muted)
    if cfg["schedule"] != "on":
        t.append("off · only when turned on by hand (s to set one)\n", style=muted)
    else:
        start, end = hhmm_index(cfg["from"]), hhmm_index(cfg["to"])
        night = [(start <= i or i < end) if start > end else (start <= i < end) for i in range(TIMELINE)]
        labels = "00          06          12          18          24"
        t.append(labels + "\n", style=muted)
        t.append(" " * 13)
        for n in night:
            t.append("█" if n else "░", style=primary if n else THEME["border"])
        now = datetime.now()
        idx = (now.hour * 60 + now.minute) // 30
        t.append("\n" + " " * (13 + idx) + "▲ ", style=muted)
        t.append(f"now {now:%H:%M}", style=muted)
        t.append(f"\n{' ' * 13}night {cfg['from']} → {cfg['to']}\n", style="bold")
    t.append("At login     ", style=muted)
    t.append("starts" if d["login"] else "doesn't start", style="bold" if d["login"] else muted)
    t.append("   l to change", style=muted)
    return t


class DisplaysView(DView):
    FOCUS = "#dsp-mon"
    DEFAULT_CSS = css("""
    DisplaysView .panel { height: auto; }
    #dsp-mon-panel Card { padding: 1 2; }
    #dsp-night-panel Card, #dsp-tablet-panel Card { padding: 0 1; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False),
        Binding("shift+tab", "cycle(-1)", show=False),
        Binding("enter", "activate", "card action (hyprmon / on-off)", show=False),
        Binding("left", "temp(-1)", "night light cooler", show=False),     # más fría (barra más vacía)
        Binding("right", "temp(1)", "night light warmer", show=False),     # más cálida (barra más llena)
        Binding("minus", "gamma(-1)", "night brightness down", show=False),
        Binding("plus,equals_sign", "gamma(1)", "night brightness up", show=False),
        Binding("s", "schedule", "night light schedule", show=False),
        Binding("l", "login", "night light at login on/off", show=False),
        Binding("r", "refresh", show=False),
    ]
    CARDS = ["dsp-mon", "dsp-night", "dsp-tablet"]

    def compose(self) -> ComposeResult:
        yield Panel(Card(id="dsp-mon"), title="󰍹  Monitors", id="dsp-mon-panel")
        yield Panel(Card(id="dsp-night"), title="󰖔  Night light", id="dsp-night-panel")
        yield Panel(Card(id="dsp-tablet"), title="󰓶  Tablet as monitor", id="dsp-tablet-panel")

    def on_mount(self) -> None:
        self.data: dict = {}
        self._busy = False
        for cid in self.CARDS:
            self.query_one(f"#{cid}", Card).update(Text("loading…", style=THEME["muted"]))
        self.reload()
        self.set_interval(5.0, self.tick)

    def on_show(self) -> None:
        if self.is_mounted:
            self.reload()

    def tick(self) -> None:
        if self.visible_now:
            self.reload()

    def reload(self) -> None:
        if not self._busy:
            self._busy = True
            self.load()

    @work(thread=True, exclusive=True, group="displays")
    def load(self) -> None:
        try:
            d = {"mons": monitors(), "night": night_state(), "tablet": tablet_state()}
        finally:
            self.app.call_from_thread(setattr, self, "_busy", False)
        self.app.call_from_thread(self.show_data, d)

    def show_data(self, d: dict) -> None:
        self.data = d
        mons = d["mons"]
        self.query_one("#dsp-mon", Card).update(draw_map(mons))
        self.query_one("#dsp-mon-panel").border_subtitle = (
            f" {len(mons)} monitor{'s' if len(mons) != 1 else ''} · enter: hyprmon " if mons else " enter: hyprmon ")
        self.paint_night()
        on, ip = d["tablet"]
        tab = Text()
        if on:
            tab.append("●  on", style=f"bold {THEME['status_ok']}")
            tab.append(f"   connect the tablet's VNC app to {ip or '<your IP>:5900'}", style=THEME["muted"])
        else:
            tab.append("○  off", style=THEME["muted"])
            tab.append("   enter to extend the desktop to a tablet over VNC "
                       "(first time: scripts/wayland/wayvnc-toggle.sh init)", style=THEME["muted"])
        self.query_one("#dsp-tablet", Card).update(tab)
        self.query_one("#dsp-tablet-panel").border_subtitle = " ● on " if on else " ○ off "

    def paint_night(self) -> None:
        n = self.data.get("night")
        if not n:
            return
        self.query_one("#dsp-night", Card).update(draw_night(n))
        self.query_one("#dsp-night-panel").border_subtitle = (
            " not installed " if not n["installed"] else " ● on " if n["on"]
            else " ○ off " if n["running"] else " ○ not running · enter to start ")

    # ── navegación ──

    def focused_card(self) -> str:
        f = self.app.focused
        return f.id if isinstance(f, Card) and f.id in self.CARDS else "dsp-mon"

    def action_cycle(self, step: int) -> None:
        i = self.CARDS.index(self.focused_card())
        self.query_one(f"#{self.CARDS[(i + step) % len(self.CARDS)]}", Card).focus()

    def hints(self) -> list[tuple[str, str]]:
        cid = self.focused_card()
        if cid == "dsp-night":
            h = [("enter", "on/off"), ("←/→", "temperature"), ("-/+", "brightness"), ("s", "schedule"),
                 ("l", "at login")]
        elif cid == "dsp-tablet":
            h = [("enter", "on/off")]
        else:
            h = [("enter", "hyprmon")]
        return h + [("tab", "card"), ("q", "quit")]

    def action_refresh(self) -> None:
        self.reload()

    # ── acciones ──

    def action_activate(self) -> None:
        cid = self.focused_card()
        if cid == "dsp-mon":
            if not shutil.which("hyprmon"):
                return self.app.notify_err("hyprmon is not installed")
            with self.app.suspend():
                subprocess.run(["hyprmon"])
            self.reload()
        elif cid == "dsp-night":
            self.toggle_night()
        else:
            self.toggle_tablet()

    def toggle_tablet(self) -> None:
        on = run(["bash", str(WAYVNC), "status"]).returncode == 0
        r = run(["bash", str(WAYVNC), "off" if on else "on"])
        if r.returncode == 0:
            self.app.notify_ok("Tablet monitor off" if on else "Tablet monitor on: connect from the tablet")
        else:
            out = (r.stderr or r.stdout).strip().splitlines()
            self.app.notify_err(out[-1] if out else "wayvnc failed")
        self.reload()

    def night_ready(self) -> Optional[dict]:
        n = self.data.get("night")
        if not n or not n["installed"]:
            self.app.notify_err("hyprsunset is not installed: sudo pacman -S hyprsunset")
            return None
        return n

    def toggle_night(self) -> None:
        n = self.night_ready()
        if not n:
            return
        cfg = n["cfg"]
        if not n["running"]:
            if not nightlight.CONF.exists():
                nightlight.write_conf(cfg)
            # enable: que arranque también en los próximos logins
            r = run(["systemctl", "--user", "enable", "--now", nightlight.UNIT])
            if r.returncode != 0:
                return self.app.notify_err(r.stderr.strip() or "could not start hyprsunset")
            time.sleep(0.5)   # que el socket IPC esté listo antes de releer
            self.app.notify_ok("night light started (follows the schedule)")
        elif n["on"]:
            nightlight.ipc("identity")
            nightlight.ipc("gamma", "100")
            self.app.notify_ok("night light off (until the next scheduled change)")
        else:
            nightlight.ipc("temperature", cfg["temperature"])
            nightlight.ipc("gamma", cfg["gamma"])
            self.app.notify_ok("night light on (until the next scheduled change)")
        self.reload()

    def adjust(self, key: str, value: int) -> None:
        """Guarda el valor y, si el daemon corre, lo aplica en vivo (preview)."""
        n = self.night_ready()
        if not n:
            return
        n["cfg"][key] = str(value)
        nightlight.write_conf(n["cfg"])
        if n["running"]:
            nightlight.ipc("temperature", n["cfg"]["temperature"])
            nightlight.ipc("gamma", n["cfg"]["gamma"])
            n["on"] = True
        self.paint_night()

    def action_temp(self, step: int) -> None:
        if self.focused_card() != "dsp-night" or not self.night_ready():
            return
        cur = int(self.data["night"]["cfg"]["temperature"])
        self.adjust("temperature", max(TEMP_MIN, min(TEMP_MAX, cur - step * TEMP_STEP)))

    def action_gamma(self, step: int) -> None:
        if self.focused_card() != "dsp-night" or not self.night_ready():
            return
        cur = int(self.data["night"]["cfg"]["gamma"])
        self.adjust("gamma", max(GAMMA_MIN, min(100, cur + step * GAMMA_STEP)))

    def action_login(self) -> None:
        if self.focused_card() != "dsp-night" or not self.night_ready():
            return
        on = self.data["night"]["login"]
        r = run(["systemctl", "--user", "disable" if on else "enable", nightlight.UNIT])
        if r.returncode == 0:
            self.app.notify_ok("night light: " + ("won't start at login" if on else "starts at login"))
        else:
            self.app.notify_err(r.stderr.strip() or "systemctl failed")
        self.reload()

    def action_schedule(self) -> None:
        if self.focused_card() != "dsp-night":
            return
        n = self.night_ready()
        if not n:
            return
        cfg = n["cfg"]

        def check(v: dict) -> Optional[str]:
            if not nightlight.TIME_RE.match(v["from"]) or not nightlight.TIME_RE.match(v["to"]):
                return "Times go as HH:MM (e.g. 21:00)"
            return None

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            new = dict(cfg) | {k: v[k].strip() for k in ("schedule", "from", "to")}
            nightlight.write_conf(new)
            if nightlight.running():
                run(["systemctl", "--user", "restart", nightlight.UNIT])   # relee los perfiles
                time.sleep(0.5)
            self.app.notify_ok("schedule saved")
            self.reload()

        onoff = [("on", "on"), ("off", "off")]
        self.app.push_screen(FormModal("Night light schedule", [
            Field("schedule", "Automatic schedule", cfg["schedule"], choices=onoff),
            Field("from", "Night starts at", cfg["from"], placeholder="21:00"),
            Field("to", "Night ends at", cfg["to"], placeholder="07:30"),
        ], hint="ctrl+s save · temperature and brightness: ←/→ and -/+ on the card", validate=check), done)
