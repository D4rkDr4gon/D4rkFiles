"""Input — teclado, mouse y touchpad de Hyprland.

Cada cambio se aplica en vivo (`hyprctl keyword input:…`) y se guarda como
línea plana en ~/.config/dotfiles/hypr/settings.conf (common.hypr_set), así
sobrevive al reinicio sin tocar el repo. La distribución y la variante de
teclado además van a KB_LAYOUT / KB_VARIANT de user.conf (de ahí salen
config/hypr/env.conf y la sesión de X11). enter edita (o alterna los on/off).
"""

from __future__ import annotations

from typing import Optional

from common import hypr_get, hypr_set, run, user_conf_set
from dtui import THEME, DView, Field, FormModal, Panel, Table, css
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import DataTable

# (bloque, clave, nombre, tipo, default, descripción)
SETTINGS = [
    ("input", "kb_layout", "Keyboard layout", "text", "us", "xkb layout(s), comma separated (e.g. latam,us)"),
    ("input", "kb_variant", "Layout variant", "text", "", "e.g. intl, deadtilde"),
    ("input", "kb_options", "Keyboard options", "text", "", "e.g. grp:alt_shift_toggle, caps:escape"),
    ("input", "repeat_rate", "Key repeat rate", "int:10:80", "25", "repeats per second"),
    ("input", "repeat_delay", "Key repeat delay", "int:150:1000", "600", "ms before repeating"),
    ("input", "sensitivity", "Pointer sensitivity", "float:-1:1", "0", "-1 slow … 0 default … 1 fast"),
    ("input", "follow_mouse", "Focus follows mouse", "int:0:3", "1", "0 click to focus · 1 hover"),
    ("input:touchpad", "natural_scroll", "Natural scroll", "bool", "false", "touchpad scrolls like a phone"),
    ("input:touchpad", "tap-to-click", "Tap to click", "bool", "true", "tap the touchpad to click"),
    ("input:touchpad", "disable_while_typing", "Disable while typing", "bool", "true", "avoid touchpad touches"),
    ("input:touchpad", "scroll_factor", "Touchpad scroll speed", "float:0.1:3", "1.0", "1 = default"),
    ("input:touchpad", "drag_lock", "Drag lock", "bool", "false", "lift the finger without dropping"),
]


class InputView(DView):
    FOCUS = "#input"

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="input"), title="󰌌  Input", id="input-panel")

    def on_mount(self) -> None:
        t = self.query_one("#input", Table)
        t.add_column("Setting", key="name", width=26)
        t.add_column("Value", key="value", width=22)
        t.add_column("", key="desc", width=60)
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#input", Table)
        row = t.cursor_row or 0
        t.clear()
        last = None
        for block, key, name, kind, default, desc in SETTINGS:
            if block != last:
                t.add_row(Text("KEYBOARD & MOUSE" if block == "input" else "TOUCHPAD",
                               style=f"bold {THEME['primary']}"), "", "", key=f"hdr:{block}")
                last = block
            val = hypr_get(f"{block}:{key}")
            shown = val if val not in (None, "") else default
            if kind == "bool":
                on = shown in ("true", "1", "yes")
                v = Text("● on" if on else "○ off", style=THEME["status_ok"] if on else THEME["muted"])
            else:
                v = Text(shown or "—", style="bold" if val not in (None, "") else THEME["muted"])
            t.add_row(f"  {name}", v, Text(desc, style=THEME["muted"]), key=f"{block}|{key}")
        t.first_selectable(row or 1)
        self.query_one("#input-panel").border_subtitle = " applied live · saved in ~/.config/dotfiles/hypr/settings.conf "

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "edit / toggle"), ("q", "quit")]

    def apply(self, block: str, key: str, value: str) -> None:
        r = run(["hyprctl", "keyword", f"{block}:{key}", value])
        if r.returncode != 0 or "error" in r.stdout.lower():
            return self.app.notify_err(r.stdout.strip() or "hyprctl rejected the value")
        hypr_set(f"{block}:{key}", value)
        if key in ("kb_layout", "kb_variant"):
            user_conf_set(key.upper(), value)
        self.app.notify_ok(f"{key} = {value or '(empty)'}")
        self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "input":
            return
        block, key = str(event.row_key.value).split("|")
        _b, _k, name, kind, default, desc = next(s for s in SETTINGS if s[0] == block and s[1] == key)
        cur = hypr_get(f"{block}:{key}")
        cur = cur if cur not in (None, "") else default
        if kind == "bool":
            return self.apply(block, key, "false" if cur in ("true", "1", "yes") else "true")

        def check(v: dict) -> Optional[str]:
            if kind == "text":
                return None
            typ, lo, hi = kind.split(":")
            try:
                n = (int if typ == "int" else float)(v["value"])
            except ValueError:
                return f"Must be a {'whole ' if typ == 'int' else ''}number"
            return None if float(lo) <= n <= float(hi) else f"Between {lo} and {hi}"

        def done(v: Optional[dict]) -> None:
            if v is not None:
                self.apply(block, key, v["value"])

        self.app.push_screen(FormModal(name, [Field("value", desc, cur)], validate=check), done)
