"""Battery — salud y estado de la batería (upower) y de los periféricos que
informan batería (mouse, teclado, auriculares por upower)."""

from __future__ import annotations

import re

from common import run
from dtui import THEME, DView, Panel, Table, charge10, css
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static


def upower_info(path: str) -> dict:
    out = run(["upower", "-i", path]).stdout
    get = lambda k: (m.group(1).strip() if (m := re.search(rf"^\s+{k}:\s+(.*)$", out, re.M)) else "")  # noqa: E731
    num = lambda k: float(re.sub(r"[^\d.]", "", get(k)) or 0)  # noqa: E731
    return {"model": get("model"), "vendor": get("vendor"), "state": get("state"), "pct": num("percentage"),
            "capacity": num("capacity"), "cycles": get("charge-cycles"), "rate": num("energy-rate"),
            "full": num("energy-full"), "design": num("energy-full-design"), "to_empty": get("time to empty"),
            "to_full": get("time to full"), "kind": path.rsplit("/", 1)[-1]}


class BatteryView(DView):
    FOCUS = "#bat-devices"
    DEFAULT_CSS = css("""
    #bat-main-panel { height: auto; }
    #bat-main { height: auto; }
    #bat-devices-panel { height: 1fr; }
    """)

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
        return [("q", "quit")]

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
