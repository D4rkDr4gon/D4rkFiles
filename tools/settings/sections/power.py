"""Power — batería, perfil de energía, brillo, acciones por inactividad y sesión.

- Battery: carga (charge10), estado, tiempo restante, consumo y salud (upower,
  mismo parser que Battery).
- Power profile: powerprofilesctl; enter aplica.
- Brightness: pantalla (y teclado si tiene luz) con brightnessctl; ←/→ cambia.
- Idle actions: hypridle on/off y los minutos para bloquear, apagar la pantalla
  y suspender, con una línea de tiempo. Genera config/hypr/hypridle.conf (lo
  que lee hypridle; generado y en .gitignore; lo elegido en
  su línea `# settings:`) y reinicia hypridle.service si corre.
- Session: bloquear, suspender, cerrar sesión, reiniciar, apagar (los tres
  últimos piden confirmación; reboot/poweroff por systemctl y, si polkit no lo
  deja, con sudo en la terminal como el menú de rofi).

Batería y brillo se refrescan en un worker cada 10 s mientras se ve.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Optional

from battery import upower_info
from common import DOTFILES, HYPRLAND, run
from dtui import THEME, Card, ConfirmModal, DView, Field, FormModal, Panel, Table, bar, charge10, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Static

IDLE_CONF = DOTFILES / "config" / "hypr" / "hypridle.conf"
IDLE_DEFAULTS = {"lock": 10, "screen": 15, "suspend": 0}   # minutos (0 = nunca)
IDLE_UNIT = "hypridle.service"
PROFILES = [("power-saver", "󰾆", "less heat and noise, longer battery"), ("balanced", "󰾅", "default"),
            ("performance", "󰓅", "maximum speed, more power")]
SESSION = [("lock", "󰌾", "Lock", False), ("suspend", "󰒲", "Suspend", False), ("logout", "󰍃", "Log out", True),
           ("reboot", "󰜉", "Reboot", True), ("poweroff", "󰐥", "Power off", True)]
IDLE_ITEMS = [("lock", "󰌾", "Lock screen after"), ("screen", "󰍹", "Turn screen off after"),
              ("suspend", "󰒲", "Suspend after")]


def idle_settings() -> dict:
    """Tiempos de hypridle guardados en la cabecera de hypridle.conf."""
    try:
        m = re.search(r"# settings: lock=(\d+) screen=(\d+) suspend=(\d+)", IDLE_CONF.read_text())
        if m:
            return {"lock": int(m.group(1)), "screen": int(m.group(2)), "suspend": int(m.group(3))}
    except OSError:
        pass
    return dict(IDLE_DEFAULTS)


def write_idle_conf(st: dict) -> None:
    lines = [
        "# hypridle.conf — generado por Settings → Power (tools/settings/sections/power.py).",
        "# No editar a mano: se reescribe al cambiar los tiempos. 0 = nunca.",
        f"# settings: lock={st['lock']} screen={st['screen']} suspend={st['suspend']}",
        "",
        "general {",
        f"    lock_cmd = pidof gtklock || bash {DOTFILES}/scripts/lock-screen.sh",
        "    before_sleep_cmd = loginctl lock-session",
        "    after_sleep_cmd = hyprctl dispatch dpms on",
        "}",
    ]
    if st["lock"]:
        lines += ["", "listener {", f"    timeout = {st['lock'] * 60}", "    on-timeout = loginctl lock-session", "}"]
    if st["screen"]:
        lines += ["", "listener {", f"    timeout = {st['screen'] * 60}", "    on-timeout = hyprctl dispatch dpms off",
                  "    on-resume = hyprctl dispatch dpms on", "}"]
    if st["suspend"]:
        lines += ["", "listener {", f"    timeout = {st['suspend'] * 60}", "    on-timeout = systemctl suspend", "}"]
    tmp = IDLE_CONF.with_suffix(".conf.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, IDLE_CONF)


def idle_active() -> bool:
    return run(["systemctl", "--user", "is-active", IDLE_UNIT]).stdout.strip() == "active"


def brightness_devices() -> list[dict]:
    """Pantalla (backlight) y luz de teclado (leds *kbd_backlight*) de brightnessctl -l -m."""
    out = []
    for line in run(["brightnessctl", "-l", "-m"]).stdout.splitlines():
        p = line.split(",")
        if len(p) < 5:
            continue
        if p[1] == "backlight" or "kbd_backlight" in p[0]:
            out.append({"name": p[0], "kind": "screen" if p[1] == "backlight" else "keyboard",
                        "cur": int(p[2]), "max": int(p[4]) or 1, "pct": int(p[3].rstrip("%"))})
    return sorted(out, key=lambda d: d["kind"] != "screen")


def battery() -> Optional[dict]:
    paths = [p for p in run(["upower", "-e"]).stdout.split() if "/battery_BAT" in p]
    return upower_info(paths[0]) if paths else None


def fmt_min(m: int) -> str:
    return "never" if not m else f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d}" if m % 60 else f"{m // 60} h"


class PowerView(DView):
    FOCUS = "#pw-profile"
    DEFAULT_CSS = css("""
    PowerView .panel { height: auto; }
    #pw-top { height: auto; }
    #pw-bat-panel { width: 1fr; }
    #pw-profile-panel { width: 1fr; }
    #pw-bottom { height: 1fr; }
    #pw-idle-panel { width: 1fr; height: 100%%; }
    #pw-session-panel { width: 34; height: 100%%; }
    #pw-idle-line { margin: 1 0; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False),
        Binding("shift+tab", "cycle(-1)", show=False),
        Binding("left,minus", "bright(-5)", "brightness down", show=False),
        Binding("right,plus,equals_sign", "bright(5)", "brightness up", show=False),
        Binding("down", "bright_dev(1)", "next backlight", show=False),
        Binding("up", "bright_dev(-1)", "previous backlight", show=False),
    ]
    FOCUSABLE = ["pw-profile", "pw-bright", "pw-idle", "pw-session"]

    def compose(self) -> ComposeResult:
        with Horizontal(id="pw-top"):
            yield Panel(Static(id="pw-bat"), title="󰁹  Battery", id="pw-bat-panel")
            yield Panel(Table(id="pw-profile", show_header=False), title="󰓅  Power profile", id="pw-profile-panel")
        yield Panel(Card(id="pw-bright"), title="󰃠  Brightness", id="pw-bright-panel")
        with Horizontal(id="pw-bottom"):
            yield Panel(Static(id="pw-idle-line"), Table(id="pw-idle", show_header=False),
                        title="󰒲  Idle actions", id="pw-idle-panel")
            yield Panel(Table(id="pw-session", show_header=False), title="󰐥  Session", id="pw-session-panel")

    def on_mount(self) -> None:
        p = self.query_one("#pw-profile", Table)
        p.add_column("", key="name", width=20)
        p.add_column("", key="desc", width=40)
        i = self.query_one("#pw-idle", Table)
        i.add_column("", key="name", width=28)
        i.add_column("", key="value", width=14)
        s = self.query_one("#pw-session", Table)
        s.add_column("", key="name", width=26)
        s.set_rows([(k, [f"{icon}  {name}"]) for k, icon, name, _c in SESSION])
        self.bright_idx = 0
        self.data: dict = {}
        self.paint_idle()
        self.reload()
        self.set_interval(10.0, self.tick)

    def on_show(self) -> None:
        if self.is_mounted:
            self.reload()

    def tick(self) -> None:
        if self.visible_now:
            self.reload()

    @work(thread=True, exclusive=True, group="power")
    def reload(self) -> None:
        d = {"bat": battery(), "profile": run(["powerprofilesctl", "get"]).stdout.strip(),
             "bright": brightness_devices(), "idle_on": idle_active()}
        self.app.call_from_thread(self.show_data, d)

    # ── dibujo ──

    def show_data(self, d: dict) -> None:
        self.data = d
        self.paint_battery()
        ok, muted = THEME["status_ok"], THEME["muted"]
        self.query_one("#pw-profile", Table).set_rows([
            (f"profile:{p}", [Text(f"{'●' if p == d['profile'] else '○'}  {icon}  {p}",
                                   style=f"bold {ok}" if p == d["profile"] else ""), Text(desc, style=muted)])
            for p, icon, desc in PROFILES])
        self.paint_bright()
        self.paint_idle()

    def paint_battery(self) -> None:
        b, muted = self.data.get("bat"), THEME["muted"]
        t = Text()
        if not b:
            t.append("no battery (desktop or not reported by upower)", style=muted)
        else:
            t.append_text(charge10(b["pct"]))
            charging = b["state"] in ("charging", "fully-charged")
            t.append(f"   {'󰂄 ' if charging else ''}{b['state']}\n", style=THEME["status_ok"] if charging else "")
            if b["state"] == "fully-charged":
                t.append("left     ", style=muted)
                t.append("plugged in\n", style="bold")
            else:
                left = b["to_full"] if b["state"] == "charging" else b["to_empty"]
                t.append(f"{'to full' if b['state'] == 'charging' else 'left':<9}", style=muted)
                t.append((left or "—") + "\n", style="bold")
            t.append("draw     ", style=muted)
            t.append(f"{b['rate']:.1f} W\n" if b["rate"] else "—\n", style="bold")
            health = b["full"] / b["design"] * 100 if b["design"] else 0
            t.append("health   ", style=muted)
            t.append(f"{health:.0f}%" if health else "—", style="bold")
            if b["cycles"] and b["cycles"] not in ("0", "N/A"):
                t.append(f" · {b['cycles']} cycles", style=muted)
        self.query_one("#pw-bat", Static).update(t)

    def paint_bright(self) -> None:
        devs, muted = self.data.get("bright", []), THEME["muted"]
        t = Text()
        if not devs:
            t.append("no backlight found (brightnessctl)", style=muted)
        for n, dv in enumerate(devs):
            sel = n == self.bright_idx and len(devs) > 1
            t.append(f"{'▸ ' if sel else '  '}{'Screen' if dv['kind'] == 'screen' else 'Keyboard':<10}",
                     style=f"bold {THEME['primary']}" if sel else muted)
            t.append_text(bar(dv["pct"], 40))
            t.append(f"  {dv['pct']:3d}%", style="bold")
            if dv["kind"] == "keyboard" and dv["max"] <= 5:
                t.append(f"  ({dv['cur']}/{dv['max']})", style=muted)
            if n < len(devs) - 1:
                t.append("\n")
        self.query_one("#pw-bright", Card).update(t)
        self.query_one("#pw-bright-panel").border_subtitle = (
            " ←/→ change · ↑/↓ screen/keyboard " if len(devs) > 1 else " ←/→ change ")

    def paint_idle(self) -> None:
        st, on = idle_settings(), self.data.get("idle_on", False)
        muted, ok, primary = THEME["muted"], THEME["status_ok"], THEME["primary"]
        # Línea de tiempo: dónde cae cada acción (proporcional al mayor tiempo)
        width = 52
        steps = [(st[k], icon) for k, icon, _n in IDLE_ITEMS if st[k]]
        top = max([m for m, _ in steps] + [1]) * 1.15
        line = ["─"] * width
        marks = []
        for m, icon in sorted(steps):
            pos = min(width - 1, round(m / top * width))
            line[pos] = icon
            marks.append((pos, fmt_min(m)))
        t = Text("idle  ", style=muted)
        t.append("".join(line), style=primary if on else muted)
        t.append("\n      ")
        lbl = [" "] * (width + 8)
        for pos, txt in marks:
            for j, ch in enumerate(txt):
                if pos + j < len(lbl):
                    lbl[pos + j] = ch
        t.append("".join(lbl).rstrip(), style=muted)
        if not steps:
            t = Text("nothing happens when idle (all actions set to never)", style=muted)
        self.query_one("#pw-idle-line", Static).update(t)
        if not shutil.which("hypridle"):
            self.query_one("#pw-idle", Table).set_rows([("noidle", [Text("○  Idle actions", style=muted),
                                                                   Text("not installed", style=muted)])])
            self.query_one("#pw-idle-line", Static).update(
                Text("install hypridle to lock / turn off the screen / suspend when idle", style=muted))
            self.query_one("#pw-idle-panel").border_subtitle = " hypridle not installed "
            return
        rows = [("idle", [Text(f"{'●' if on else '○'}  Idle actions", style=f"bold {ok}" if on else ""),
                          Text("on" if on else "off", style=ok if on else muted)])]
        rows += [(f"idle:{k}", [f"{icon}  {name}", Text(fmt_min(st[k]), style="bold" if st[k] else muted)])
                 for k, icon, name in IDLE_ITEMS]
        self.query_one("#pw-idle", Table).set_rows(rows)
        self.query_one("#pw-idle-panel").border_subtitle = " ● hypridle on " if on else " ○ hypridle off "

    # ── navegación ──

    def focused(self) -> str:
        f = self.app.focused
        return f.id if f is not None and f.id in self.FOCUSABLE else "pw-profile"

    def action_cycle(self, step: int) -> None:
        i = self.FOCUSABLE.index(self.focused())
        self.query_one(f"#{self.FOCUSABLE[(i + step) % len(self.FOCUSABLE)]}").focus()

    def hints(self) -> list[tuple[str, str]]:
        f = self.focused()
        h = {"pw-profile": [("enter", "use profile")],
             "pw-bright": [("←/→", "brightness")] + ([("↑/↓", "screen/keyboard")]
                                                    if len(self.data.get("bright", [])) > 1 else []),
             "pw-idle": [("enter", "on/off · edit minutes")],
             "pw-session": [("enter", "run")]}[f]
        return h + [("tab", "panel"), ("q", "quit")]

    # ── acciones ──

    def action_bright(self, step: int) -> None:
        if self.focused() != "pw-bright":
            return
        devs = self.data.get("bright", [])
        if not devs:
            return
        dv = devs[min(self.bright_idx, len(devs) - 1)]
        # teclados con pocos niveles: de a uno; pantalla: de a 5 %
        amount = "1" if dv["kind"] == "keyboard" and dv["max"] <= 5 else f"{abs(step)}%"
        run(["brightnessctl", "-d", dv["name"], "set", f"{amount}{'+' if step > 0 else '-'}"])
        self.data["bright"] = brightness_devices()
        self.paint_bright()

    def action_bright_dev(self, step: int) -> None:
        devs = self.data.get("bright", [])
        if self.focused() == "pw-bright" and len(devs) > 1:
            self.bright_idx = (self.bright_idx + step) % len(devs)
            self.paint_bright()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tid, key = event.data_table.id, str(event.row_key.value)
        if tid == "pw-profile":
            r = run(["powerprofilesctl", "set", key.split(":", 1)[1]])
            self.app.notify_ok(f"Profile: {key[8:]}") if r.returncode == 0 else self.app.notify_err(r.stderr.strip())
            self.reload()
        elif tid == "pw-idle":
            self.idle_action(key)
        elif tid == "pw-session":
            self.session(key)

    def idle_action(self, key: str) -> None:
        if key == "noidle":
            return self.app.notify_err("hypridle is not installed: sudo pacman -S hypridle")
        if key == "idle":
            if not idle_active():
                if not IDLE_CONF.exists():
                    write_idle_conf(idle_settings())
                run(["systemctl", "--user", "enable", "--now", IDLE_UNIT])
                self.app.notify_ok("Idle actions on")
            else:
                run(["systemctl", "--user", "disable", "--now", IDLE_UNIT])
                self.app.notify_ok("Idle actions off")
            return self.reload()
        k, st = key[5:], idle_settings()
        name = next(n for kk, _i, n in IDLE_ITEMS if kk == k)

        def check(v: dict) -> Optional[str]:
            return None if v["min"].isdigit() and int(v["min"]) <= 600 else "Minutes from 0 to 600 (0 = never)"

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            st[k] = int(v["min"])
            write_idle_conf(st)
            if idle_active():
                run(["systemctl", "--user", "restart", IDLE_UNIT])
            self.paint_idle()

        self.app.push_screen(FormModal(name, [Field("min", "Minutes (0 = never)", str(st[k]))],
                                       hint="Lock should come before turning the screen off.", validate=check), done)

    def session(self, key: str) -> None:
        name = next(n for k, _i, n, _c in SESSION if k == key)
        confirm = next(c for k, _i, _n, c in SESSION if k == key)

        def go() -> None:
            if key == "lock":
                run(["loginctl", "lock-session"])
            elif key == "suspend":
                run(["systemctl", "suspend"])
            elif key == "logout":
                run(["hyprctl", "dispatch", "exit"] if HYPRLAND else ["qtile", "cmd-obj", "-o", "cmd", "-f", "shutdown"])
            else:
                r = run(["systemctl", key])
                if r.returncode != 0:
                    # polkit no lo dejó: con sudo en la terminal (como el menú de rofi)
                    with self.app.suspend():
                        os.system("clear")
                        subprocess.run(["sudo", "systemctl", key])

        if not confirm:
            return go()
        self.app.push_screen(ConfirmModal(name, f"{name} now? Unsaved work in open apps will be lost."),
                             lambda yes: yes and go())
