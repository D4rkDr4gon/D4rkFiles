"""Battery — salud y estado de la batería (upower) y de los periféricos que
informan batería (mouse, teclado, auriculares por upower).

Tope de carga (`l`): si el driver lo permite (charge_control_end_threshold,
ThinkPad y otros), la batería deja de cargar en ese porcentaje y retoma 5 puntos
abajo. Cargar siempre hasta el 100 % desgasta la batería de una notebook que vive
enchufada. Se aplica en el momento y queda fijo con una regla de udev
(/etc/udev/rules.d/90-battery-charge-limit.rules); 100 % borra la regla y vuelve a
los valores de fábrica. Ambas cosas con sudo en la terminal."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from common import root_file, run, sudo_run
from dtui import THEME, DView, Panel, PickModal, Table, charge10, css
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static


def upower_info(path: str) -> dict:
    out = run(["upower", "-i", path]).stdout
    get = lambda k: (m.group(1).strip() if (m := re.search(rf"^\s+{k}:\s+(.*)$", out, re.M)) else "")  # noqa: E731
    num = lambda k: float(re.sub(r"[^\d.]", "", get(k)) or 0)  # noqa: E731
    return {"model": get("model"), "vendor": get("vendor"), "state": get("state"), "pct": num("percentage"),
            "capacity": num("capacity"), "cycles": get("charge-cycles"), "rate": num("energy-rate"),
            "full": num("energy-full"), "design": num("energy-full-design"), "to_empty": get("time to empty"),
            "to_full": get("time to full"), "kind": path.rsplit("/", 1)[-1]}


LIMIT_RULE = Path("/etc/udev/rules.d/90-battery-charge-limit.rules")
LIMITS = [(100, "Full", "always charge to 100 % (factory default)"),
          (90, "Balanced", "a little less wear, almost full range"),
          (80, "Recommended", "much less wear; best if it is usually plugged in"),
          (60, "Always plugged", "lowest wear; for a laptop that never leaves the desk")]


def battery_dir() -> Optional[Path]:
    """La primera batería con tope de carga configurable."""
    for d in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        if (d / "charge_control_end_threshold").exists():
            return d
    return None


def read_int(f: Path) -> Optional[int]:
    try:
        return int(f.read_text().strip())
    except (OSError, ValueError):
        return None


def charge_limit() -> Optional[tuple[int, Optional[int], bool]]:
    """(tope, inicio, persistente) o None si la batería no lo permite."""
    d = battery_dir()
    if not d:
        return None
    end = read_int(d / "charge_control_end_threshold")
    if end is None:
        return None
    return end, read_int(d / "charge_control_start_threshold"), LIMIT_RULE.exists()


def limit_cmds(bat: Path, end: int) -> list[list[str]]:
    """Comandos (con sudo) para fijar el tope ahora y al arrancar."""
    start_f, end_f = bat / "charge_control_start_threshold", bat / "charge_control_end_threshold"
    has_start = start_f.exists()
    start = 95 if end == 100 else end - 5
    # El inicio tiene que quedar por debajo del tope en todo momento: al bajar se
    # escribe primero el inicio, al subir primero el tope
    writes = [(start_f, start), (end_f, end)] if has_start else [(end_f, end)]
    if has_start and end > (read_int(end_f) or 100):
        writes.reverse()
    sh = "; ".join(f"echo {v} > {f}" for f, v in writes)
    cmds = [["sh", "-c", sh]]
    if end == 100:
        cmds.append(["rm", "-f", str(LIMIT_RULE)])
    else:
        attrs = (f'ATTR{{charge_control_start_threshold}}="{start}", ' if has_start else "") + \
            f'ATTR{{charge_control_end_threshold}}="{end}"'
        rule = ("# Generado por Settings → Battery (dotfiles): tope de carga de la batería.\n"
                "# Se borra eligiendo 100 % en Settings.\n"
                f'ACTION=="add", SUBSYSTEM=="power_supply", KERNEL=="{bat.name}", {attrs}\n')
        cmds.append(["install", "-m644", root_file(rule), str(LIMIT_RULE)])
    return cmds


class BatteryView(DView):
    FOCUS = "#bat-devices"
    DEFAULT_CSS = css("""
    #bat-main-panel { height: auto; }
    #bat-main { height: auto; }
    #bat-devices-panel { height: 1fr; }
    """)
    BINDINGS = [Binding("l", "limit", "charge limit")]

    def compose(self) -> ComposeResult:
        yield Panel(Static(id="bat-main"), title="󰁹  Battery", id="bat-main-panel")
        yield Panel(Table(id="bat-devices"), title="Devices", id="bat-devices-panel")

    def on_mount(self) -> None:
        t = self.query_one("#bat-devices", Table)
        t.add_column("Device", key="name", width=36)
        t.add_column("Charge", key="pct", width=18)
        t.add_column("State", key="state", width=20)
        self.reload()
        self.set_interval(30, self.tick)

    def tick(self) -> None:
        if self.visible_now:
            self.reload()

    def hints(self) -> list[tuple[str, str]]:
        return [("l", "charge limit"), ("q", "quit")]

    def action_limit(self) -> None:
        bat, cur = battery_dir(), charge_limit()
        if not bat or not cur:
            return self.app.notify_err("This battery has no configurable charge limit")
        muted = THEME["muted"]
        rows = [(str(v), [f"{'●' if v == cur[0] else '○'}  {v} %", name, Text(desc, style=muted)])
                for v, name, desc in LIMITS]

        def picked(key: Optional[str]) -> None:
            if not key:
                return
            end = int(key)
            if sudo_run(self.app, limit_cmds(bat, end), f"Battery charge limit → {end} %"):
                self.app.notify_ok(f"Charge limit: {end} %" + ("" if end == 100 else " (kept after reboot)"))
            self.reload()

        self.app.push_screen(PickModal("Charge limit", ["Limit", "", ""], rows), picked)

    def reload(self) -> None:
        paths = [p for p in run(["upower", "-e"]).stdout.split() if "DisplayDevice" not in p]
        devs = [upower_info(p) for p in paths]
        main = next((d for d in devs if d["kind"].startswith("battery_BAT")), None)
        muted, ok = THEME["muted"], THEME["status_ok"]
        t = Text()
        if not main:
            t.append("No laptop battery found", style=muted)
        else:
            def row(label: str, value: Text | str) -> None:
                t.append(f"{label:<14}", style=f"bold {muted}")
                t.append(value if isinstance(value, Text) else Text(value))
                t.append("\n")

            charge = charge10(main["pct"])
            charge.append(f"  {main['state']}", style=ok if main["state"] in ("charging", "fully-charged") else muted)
            row("Charge", charge)
            # Salud: al revés que el uso, 100 % es lo bueno (verde arriba de 80)
            health = Text()
            full = min(10, int(main["capacity"] // 10))
            c = THEME["status_ok"] if main["capacity"] >= 80 else THEME["status_warn"] if main["capacity"] >= 60 \
                else THEME["status_error"]
            health.append("▓" * full, style=c)
            health.append("░" * (10 - full), style=THEME["border"])
            health.append(f" {main['capacity']:.0f}%", style=f"bold {c}")
            health.append(f"  {main['full']:.1f} of {main['design']:.1f} Wh when new", style=muted)
            row("Health", health)
            row("Cycles", main["cycles"] or "—")
            lim = charge_limit()
            if lim:
                end, start, kept = lim
                v = Text(f"{end} %", style=f"bold {ok}" if end < 100 else "")
                if end < 100:
                    v.append(f"  charges again below {start} %" if start else "", style=muted)
                    v.append("  · kept after reboot" if kept else "  · until reboot (l to keep it)",
                             style=muted if kept else THEME["status_warn"])
                else:
                    v.append("  full charge · l to limit it and reduce wear", style=muted)
                row("Charge limit", v)
            row("Power draw", f"{main['rate']:.1f} W" if main["rate"] else "— (on AC / idle)")
            if main["to_empty"]:
                row("Time left", main["to_empty"])
            if main["to_full"]:
                row("Until full", main["to_full"])
            row("Model", f"{main['vendor']} {main['model']}".strip() or "—")
        self.query_one("#bat-main", Static).update(t)

        tb = self.query_one("#bat-devices", Table)
        tb.clear()
        for d in devs:
            if d is main:
                continue
            tb.add_row(d["model"] or d["kind"], charge10(d["pct"]) if d["pct"] else Text("—", style=muted),
                       Text(d["state"] or "—", style=muted))
        self.query_one("#bat-devices-panel").border_subtitle = "" if tb.row_count else " no other devices "
