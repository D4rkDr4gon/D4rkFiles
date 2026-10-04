"""Color picker — tomar el color de un píxel de la pantalla (slurp -p + grim,
sin depender de hyprpicker) y guardar un historial. enter sobre un color
copia su hex; c cambia el formato que se copia (hex / rgb / hsl).
Historial: ~/.local/state/dotfiles/settings/colors.json (últimos 50).
"""

from __future__ import annotations

import colorsys
import json
import subprocess
from typing import Optional

from common import STATE, run, settings_hidden
from dtui import THEME, DView, Panel, Table, css
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

HISTORY = STATE / "colors.json"


def load() -> list[str]:
    try:
        return json.loads(HISTORY.read_text())
    except (OSError, ValueError):
        return []


def save(colors: list[str]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(colors[:50]))


def pick() -> Optional[str]:
    """Hex del píxel que se clickea (None si se cancela)."""
    geom = run(["slurp", "-p"], timeout=60).stdout.strip()
    if not geom:
        return None
    try:
        ppm = subprocess.run(["grim", "-g", geom, "-t", "ppm", "-"], capture_output=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    # PPM binario: "P6\n<w> <h>\n<max>\n" + RGB
    parts = ppm.split(b"\n", 3)
    if len(parts) < 4 or len(parts[3]) < 3:
        return None
    r, g, b = parts[3][:3]
    return f"#{r:02x}{g:02x}{b:02x}"


def formats(hexc: str) -> dict[str, str]:
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {"hex": hexc, "rgb": f"rgb({r}, {g}, {b})", "hsl": f"hsl({h * 360:.0f}, {s * 100:.0f}%, {l * 100:.0f}%)"}


class ColorPickerView(DView):
    FOCUS = "#colors"
    BINDINGS = [Binding("p", "pick", "pick"), Binding("c", "cycle_format", "format"), Binding("d", "delete", "delete")]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="colors"), title="󰏘  Color picker", id="colors-panel")

    def on_mount(self) -> None:
        t = self.query_one("#colors", Table)
        t.add_column("", key="sw", width=8)
        t.add_column("Hex", key="hex", width=10)
        t.add_column("RGB", key="rgb", width=20)
        t.add_column("HSL", key="hsl", width=24)
        self.fmt = "hex"
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#colors", Table)
        t.clear()
        t.add_row(Text("󰴱  Pick a color from the screen", style=f"bold {THEME['primary']}"), "", "", "", key="pick")
        for i, c in enumerate(load()):
            f = formats(c)
            t.add_row(Text("██████", style=c), f["hex"], Text(f["rgb"], style=THEME["muted"]),
                      Text(f["hsl"], style=THEME["muted"]), key=f"c:{i}")
        self.query_one("#colors-panel").border_subtitle = f" enter copies as {self.fmt} · c changes the format "

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", f"copy {self.fmt}"), ("p", "pick"), ("c", "format"), ("d", "delete"), ("q", "quit")]

    def action_pick(self) -> None:
        with settings_hidden(self.app):
            c = pick()
        if not c:
            return self.app.notify_err("Pick cancelled")
        colors = [c] + [x for x in load() if x != c]
        save(colors)
        subprocess.run(["wl-copy"], input=formats(c)[self.fmt].encode())
        self.app.notify_ok(f"{formats(c)[self.fmt]} copied")
        self.reload()
        self.query_one("#colors", Table).move_cursor(row=1)

    def action_cycle_format(self) -> None:
        self.fmt = {"hex": "rgb", "rgb": "hsl", "hsl": "hex"}[self.fmt]
        self.reload()
        self.update_hints()

    def action_delete(self) -> None:
        key = self.query_one("#colors", Table).selected_key()
        if key and key.startswith("c:"):
            colors = load()
            colors.pop(int(key[2:]))
            save(colors)
            self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "colors":
            return
        key = str(event.row_key.value)
        if key == "pick":
            return self.action_pick()
        c = load()[int(key[2:])]
        subprocess.run(["wl-copy"], input=formats(c)[self.fmt].encode())
        self.app.notify_ok(f"{formats(c)[self.fmt]} copied")
