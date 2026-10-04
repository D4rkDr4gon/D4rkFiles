"""Fonts & cursor — fuente mono y tema de íconos (campos font_mono / icon_theme
del tema activo, guardados en su copia de ~/.config/dotfiles/themes/ y
reaplicados con theme-switch.sh) y cursor (tema y tamaño: en vivo con
hyprctl setcursor + gsettings, y guardado como `env = XCURSOR_THEME/
XCURSOR_SIZE` en ~/.config/dotfiles/hypr/settings.conf)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from common import THEME_SWITCH, active_theme_dir, editable_theme_dir, env_get, env_set, run
from dtui import THEME, DView, Field, FormModal, Panel, PickModal, Table, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.widgets import DataTable

ICON_DIRS = [Path.home() / ".local/share/icons", Path.home() / ".icons", Path("/usr/share/icons")]


def mono_fonts() -> list[str]:
    fams = run(["fc-list", ":spacing=100", "family"]).stdout.splitlines()
    names = {f.split(",")[0].strip() for f in fams if f.strip()}
    nerd = sorted(n for n in names if "Nerd Font" in n and not re.search(r"Ita\b|Italic|Propo", n))
    return nerd or sorted(names)


def icon_themes(cursors: bool) -> list[str]:
    """Temas de íconos (cursors=False) o de cursor (cursors=True) instalados."""
    out = set()
    for base in ICON_DIRS:
        for d in base.iterdir() if base.is_dir() else []:
            has_cursors = (d / "cursors").is_dir()
            if cursors and has_cursors:
                out.add(d.name)
            elif not cursors and (d / "index.theme").is_file() and d.name not in ("default", "hicolor", "locolor") \
                    and not (has_cursors and len(list(d.iterdir())) <= 3):
                out.add(d.name)
    return sorted(out)


class FontsView(DView):
    FOCUS = "#fonts"

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="fonts"), title="󰛖  Fonts & cursor", id="fonts-panel")

    def on_mount(self) -> None:
        t = self.query_one("#fonts", Table)
        t.add_column("Setting", key="name", width=22)
        t.add_column("Value", key="value", width=34)
        t.add_column("", key="desc", width=60)
        self.reload()

    def theme_data(self) -> tuple[Optional[Path], dict]:
        d = active_theme_dir()
        return d, (json.loads((d / "theme.json").read_text()) if d else {})

    def reload(self) -> None:
        t = self.query_one("#fonts", Table)
        row = t.cursor_row or 0
        t.clear()
        d, th = self.theme_data()
        muted = THEME["muted"]
        rows = [("font", "Monospace font", th.get("font_mono") or "Hack Nerd Font",
                 "kitty, rofi, dunst, waybar, gtklock (and every TUI inside kitty)"),
                ("icons", "Icon theme", th.get("icon_theme") or "Papirus-Dark", "Thunar and GTK apps"),
                ("cursor", "Cursor theme", env_get("XCURSOR_THEME") or "Adwaita", "applied live + saved in settings.conf"),
                ("size", "Cursor size", env_get("XCURSOR_SIZE") or "24", "pixels (16–64)")]
        for key, name, value, desc in rows:
            t.add_row(name, Text(value, style="bold"), Text(desc, style=muted), key=key)
        t.move_cursor(row=min(row, t.row_count - 1))
        self.query_one("#fonts-panel").border_subtitle = (f" font and icons are saved in theme {d.name} "
                                                          if d else "")

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "change"), ("q", "quit")]

    def set_cursor(self, theme: str, size: str) -> None:
        run(["hyprctl", "setcursor", theme, size])
        run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", theme])
        run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", size])
        env_set("XCURSOR_THEME", theme)
        env_set("XCURSOR_SIZE", size)
        self.app.notify_ok(f"Cursor: {theme} {size}px")
        self.reload()

    def set_theme_field(self, key: str, value: str) -> None:
        d = editable_theme_dir()
        if not d:
            return self.app.notify_err("No active theme found")
        th = json.loads((d / "theme.json").read_text())
        th[key] = value
        (d / "theme.json").write_text(json.dumps(th, indent=2, ensure_ascii=False) + "\n")
        self.query_one("#fonts-panel").border_subtitle = " applying… "
        self.apply(d.name)

    @work(thread=True, exclusive=True)
    def apply(self, theme_dir: str) -> None:
        subprocess.run(["bash", str(THEME_SWITCH), theme_dir], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)
        self.app.call_from_thread(self.app.restart, "fonts")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "fonts":
            return
        key = str(event.row_key.value)
        if key == "size":
            def done(v: Optional[dict]) -> None:
                if v:
                    self.set_cursor(env_get("XCURSOR_THEME") or "Adwaita", v["value"])
            return self.app.push_screen(FormModal("Cursor size", [Field("value", "Pixels", env_get("XCURSOR_SIZE")
                                                                       or "24")],
                                                  validate=lambda v: None if v["value"].isdigit()
                                                  and 16 <= int(v["value"]) <= 64 else "From 16 to 64"), done)
        options = {"font": mono_fonts(), "icons": icon_themes(False), "cursor": icon_themes(True)}[key]
        title = {"font": "Monospace font", "icons": "Icon theme", "cursor": "Cursor theme"}[key]
        rows = [(o, [Text(o, style=f"bold" if key != "font" else "")]) for o in options]

        def picked(v: Optional[str]) -> None:
            if not v:
                return
            if key == "cursor":
                self.set_cursor(v, env_get("XCURSOR_SIZE") or "24")
            else:
                self.set_theme_field("font_mono" if key == "font" else "icon_theme", v)

        self.app.push_screen(PickModal(title, [title], rows), picked)
