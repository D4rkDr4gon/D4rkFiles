#!/usr/bin/env python3
"""
settings_tui.py — Settings del entorno (Mod+Shift+Space, logo de waybar).

Reemplaza al menú rofi de Settings. A la izquierda el perfil (logo de
waybar + USER_DISPLAY_NAME de user.conf, o el nombre de la cuenta) y el menú
de secciones; a la derecha la sección elegida. Modes, Webapps, Shortcuts,
VPN, Clipboard y AI Agents son las mismas vistas que las TUIs sueltas
(tools/*_tui.py), montadas acá; Displays corre hyprmon en la misma ventana y
Update corre dotfiles-update.sh igual.

Nada de lo que se cambia acá toca archivos versionados: los overrides van a
~/.config/dotfiles (ver sections/common.py).

Teclas: el menú cambia la sección al moverse; enter/tab entra a la sección,
esc vuelve al menú (en el menú, sale), q sale.

`--section <id>` abre directo en una sección (lo usa el reinicio después de
aplicar un tema, para releer los colores nuevos).

Estilo común de las TUIs: tools/dtui.py. Textos visibles en inglés.
"""

from __future__ import annotations

import functools
import html
import importlib
import json
import re
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))                                    # dtui y las TUIs sueltas
sys.path.insert(0, str(Path(__file__).resolve().parent / "sections"))   # secciones en archivos propios
from dtui import (THEME, ConfirmModal, DApp, DView, Field, FormModal, ImagePreview, KeyHints, bar, charge10, meter10,  # noqa: E402
                  Panel, PickModal, Table, TextModal, css, load_theme, swatches)

from battery import BatteryView  # noqa: E402
from common import (CURRENT_THEME, DOTFILES, HYPRLAND, THEME_SWITCH, active_theme_dir, current_theme,  # noqa: E402
                    detach, display_name, editable_theme_dir, is_user_theme, resolve_wallpaper, run, theme_dirs,
                    tilde, user_conf, wallpaper_dirs)
from colorpicker import ColorPickerView  # noqa: E402
from defaultapps import DefaultAppsView  # noqa: E402
from fonts import FontsView  # noqa: E402
from inputdev import InputView  # noqa: E402
from logs import LogsView  # noqa: E402
from nettools import NetToolsView  # noqa: E402
from phone import PhoneView  # noqa: E402
from screenshots import ScreenshotsView  # noqa: E402
from snapshots import SnapshotsView  # noqa: E402
from startup import StartupView  # noqa: E402
from storage import StorageView  # noqa: E402
from themeeditor import ThemeEditorView  # noqa: E402
from rich.text import Text  # noqa: E402
from textual import work  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.widgets import ContentSwitcher, DataTable, Static  # noqa: E402

# Perfil: el mismo logo que waybar; el nombre, de user.conf (o la cuenta)
LOGO = DOTFILES / "config" / "waybar" / "logo.png"
WALLPAPER_SET = DOTFILES / "scripts" / "wallpaper-set.sh"
UPDATE_SH = DOTFILES / "scripts" / "dotfiles-update.sh"
DND = DOTFILES / "config" / "rofi" / "scripts" / "dnd-menu.sh"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


def load_view(module: str, attr: str):
    """Importa la vista de una TUI suelta (tools/<module>.py)."""
    return getattr(importlib.import_module(module), attr)


def goto_workspace(ws: int) -> None:
    if HYPRLAND:
        run(["hyprctl", "dispatch", "workspace", str(ws)])
    else:
        run(["qtile", "cmd-obj", "-o", "group", str(ws), "-f", "toscreen"])


# ── Themes ────────────────────────────────────────────────

class ThemesView(DView):
    """Temas (~/.config/dotfiles/themes y themes/ del repo) con preview; enter aplica."""

    FOCUS = "#themes"
    DEFAULT_CSS = css("""
    #themes-panel { width: 42; }
    #theme-preview-panel { width: 1fr; }
    #theme-preview { height: 1fr; }
    #theme-info { height: auto; margin-top: 1; }
    """)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Panel(Table(id="themes", show_header=False), title="󰏘  Themes", id="themes-panel")
            yield Panel(ImagePreview(id="theme-preview"), Static(id="theme-info"),
                        title="Preview", id="theme-preview-panel")

    def on_mount(self) -> None:
        t = self.query_one("#themes", Table)
        t.add_column("Theme", key="name", width=36)
        self.themes = [(d, load_theme(d / "theme.json") | json.loads((d / "theme.json").read_text()))
                       for d in theme_dirs()]
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#themes", Table)
        act = active_theme_dir()
        active = current_theme().get("name")
        row = t.cursor_row or 0
        t.clear()
        for i, (d, th) in enumerate(self.themes):
            label = Text(f"{th.get('icon', '')}  {th.get('name', d.name)}")
            if is_user_theme(d):
                label.append("  · yours", style=THEME["muted"])
            if act is not None and d == act:
                label.append("  ● active", style=THEME["status_ok"])
                row = row or i
            t.add_row(label, key=d.name)
        t.move_cursor(row=row)
        self.query_one("#themes-panel").border_subtitle = f" active: {active} " if active else ""
        self.show_preview()

    def on_data_table_row_highlighted(self, _event) -> None:
        self.show_preview()

    def selected(self):
        key = self.query_one("#themes", Table).selected_key()
        return next(((d, th) for d, th in self.themes if d.name == key), None)

    def show_preview(self) -> None:
        sel = self.selected()
        if not sel:
            return
        d, th = sel
        preview = d / "preview.png"
        self.query_one(ImagePreview).set_image(preview if preview.exists() else None)
        info = Text()
        info.append(f"{th.get('name', d.name)}\n", style=f"bold {th['primary']}")
        info.append_text(swatches(th))
        if not preview.exists():
            info.append("\nno preview image", style=THEME["muted"])
        self.query_one("#theme-info", Static).update(info)

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "apply"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "themes" and (sel := self.selected()):
            self.query_one("#themes-panel").border_subtitle = f" applying {sel[1].get('name')}… "
            self.apply(sel[0].name)

    @work(thread=True, exclusive=True)
    def apply(self, theme_dir: str) -> None:
        subprocess.run(["bash", str(THEME_SWITCH), theme_dir], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)
        # Settings se reabre para tomar los colores nuevos (THEME se lee al importar)
        self.app.call_from_thread(self.app.restart, "themes")


# ── Workspaces ────────────────────────────────────────────

class WorkspacesView(DView):
    """Ir a un workspace (1-9 en Hyprland, 1-6 en Qtile)."""

    FOCUS = "#workspaces"

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="workspaces"), title="  Workspaces", id="ws-panel")

    def on_mount(self) -> None:
        t = self.query_one("#workspaces", Table)
        t.add_column("Workspace", key="ws", width=16)
        t.add_column("Windows", key="n", width=10)
        t.add_column("", key="extra", width=60)
        info, active = {}, None
        if HYPRLAND:
            try:
                info = {w["id"]: w for w in json.loads(run(["hyprctl", "workspaces", "-j"]).stdout)}
                active = json.loads(run(["hyprctl", "activeworkspace", "-j"]).stdout).get("id")
            except ValueError:
                pass
        for ws in range(1, 10 if HYPRLAND else 7):
            w = info.get(ws, {})
            extra = Text(w.get("lastwindowtitle", ""), style=THEME["muted"])
            label = Text(f"  Workspace {ws}")
            if ws == active:
                label.append("  ●", style=THEME["status_ok"])
            t.add_row(label, str(w.get("windows", 0)) if w else Text("—", style=THEME["muted"]), extra, key=str(ws))
        if active:
            t.move_cursor(row=active - 1)

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "go"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "workspaces":
            goto_workspace(int(event.row_key.value))
            self.app.exit()


# ── Backgrounds ───────────────────────────────────────────

class BackgroundsView(DView):
    """Wallpapers de las carpetas de WALLPAPER_DIRS (EXTRA_WALLPAPER_DIRS de
    user.conf, ~/.local/share/backgrounds y assets/wallpapers) con preview."""

    FOCUS = "#walls"
    DEFAULT_CSS = css("""
    #walls-panel { width: 42; }
    #wall-preview-panel { width: 1fr; }
    #wall-preview { height: 1fr; }
    """)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Panel(Table(id="walls", show_header=False), title="  Backgrounds", id="walls-panel")
            yield Panel(ImagePreview(id="wall-preview"), title="Preview", id="wall-preview-panel")

    def on_mount(self) -> None:
        t = self.query_one("#walls", Table)
        t.add_column("Wallpaper", key="name", width=36)
        seen, self.walls = set(), []
        for d in wallpaper_dirs():
            for p in sorted(d.iterdir()) if d.is_dir() else []:
                if p.suffix.lower() in IMAGE_EXT and p.name not in seen:
                    seen.add(p.name)
                    self.walls.append(p)
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#walls", Table)
        cur = resolve_wallpaper(current_theme().get("wallpaper", "") or "")
        active = str(cur.resolve()) if cur else ""
        t.clear()
        row = 0
        for i, p in enumerate(self.walls):
            label = Text(p.stem)
            if str(p.resolve()) == active:
                label.append("  ● active", style=THEME["status_ok"])
                row = i
            t.add_row(label, key=str(p))
        t.move_cursor(row=row)
        self.query_one("#walls-panel").border_subtitle = (f" {len(self.walls)} wallpapers " if self.walls else
                                                          " none: add images to ~/.local/share/backgrounds ")
        self.show_preview()

    def on_data_table_row_highlighted(self, _event) -> None:
        self.show_preview()

    def show_preview(self) -> None:
        key = self.query_one("#walls", Table).selected_key()
        if key:
            self.query_one(ImagePreview).set_image(Path(key))
            self.query_one("#wall-preview-panel").border_subtitle = f" {Path(key).name} "

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "apply"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "walls":
            detach(["bash", str(WALLPAPER_SET), event.row_key.value])
            self.app.notify_ok(f"Background: {Path(event.row_key.value).stem}")
            self.set_timer(1.5, self.reload)


# ── Notifications ─────────────────────────────────────────

class NotificationsView(DView):
    """Historial de dunst + No Molestar (config/rofi/scripts/dnd-menu.sh)."""

    FOCUS = "#history"
    DEFAULT_CSS = css("""
    #history-panel { height: 1fr; }
    #dnd-panel { height: auto; max-height: 60%%; }
    #dnd { height: auto; max-height: 100%%; }
    """)
    BINDINGS = [
        Binding("tab", "switch", show=False),
        Binding("shift+tab", "switch", show=False),
        Binding("c", "clear", "clear all"),
        Binding("j", "down", show=False),
        Binding("k", "up", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="history"), title="  Notifications", id="history-panel")
        yield Panel(Table(id="dnd", show_header=False), title="󰂛  Do Not Disturb", id="dnd-panel")

    def on_mount(self) -> None:
        h = self.query_one("#history", Table)
        h.add_column("App", key="app", width=18)
        h.add_column("Summary", key="summary", width=40)
        h.add_column("Body", key="body", width=50)
        d = self.query_one("#dnd", Table)
        d.add_column("", key="label", width=50)
        d.add_column("", key="extra", width=30)
        self.reload()

    def reload(self) -> None:
        self.items = []
        try:
            data = json.loads(run(["dunstctl", "history"]).stdout or "{}")
            self.items = [{k: n.get(k, {}).get("data", "") for k in ("id", "appname", "summary", "body")}
                          for n in data.get("data", [[]])[0]]
            # dunst guarda el markup tal cual (&lt;b&gt;, <i>…): texto plano para mostrar
            for n in self.items:
                for k in ("summary", "body"):
                    n[k] = re.sub(r"<[^>]+>", "", html.unescape(html.unescape(str(n[k]))))
        except ValueError:
            pass
        h = self.query_one("#history", Table)
        row = h.cursor_row or 0
        h.clear()
        for n in self.items:
            h.add_row(n["appname"], n["summary"], Text(" ".join(n["body"].split()), style=THEME["muted"]),
                      key=str(n["id"]))
        if self.items:
            h.move_cursor(row=min(row, len(self.items) - 1))
        self.query_one("#history-panel").border_subtitle = (f" {len(self.items)} in history " if self.items
                                                            else " history is empty ")
        self.reload_dnd()

    def reload_dnd(self) -> None:
        try:
            st = json.loads(run(["bash", str(DND), "--status"]).stdout)
        except ValueError:
            st = {"active": False, "remaining": "", "apps": []}
        self.dnd = st
        d = self.query_one("#dnd", Table)
        row = d.cursor_row or 0
        d.clear()
        muted, ok = THEME["muted"], THEME["status_ok"]
        if st["active"]:
            d.add_row(Text("●  Do Not Disturb is on", style=f"bold {ok}"),
                      Text(f"turns off in {st['remaining']}" if st["remaining"] else "until turned off",
                           style=muted), key="toggle")
        else:
            d.add_row(Text("○  Do Not Disturb is off", style=muted), Text("enter to turn on", style=muted),
                      key="toggle")
        for key, label in (("t3600", "On for 1 hour"), ("t7200", "On for 2 hours"),
                           ("tmorning", "On until tomorrow 08:00"), ("tcustom", "On for a custom time…")):
            d.add_row(f"⏱  {label}", "", key=key)
        for a in st["apps"]:
            d.add_row(Text(f"{'✓' if a['enabled'] else '○'}  Silence {a['app']}"),
                      Text("silenced" if a["enabled"] else "allowed", style=ok if a["enabled"] else muted),
                      key=f"app:{a['app']}")
        d.add_row(Text("+  Silence an app…", style=THEME["primary"]), "", key="add")
        d.move_cursor(row=min(row, d.row_count - 1))
        self.query_one("#dnd-panel").border_subtitle = " on " if st["active"] else " off "

    def in_dnd(self) -> bool:
        return self.app.focused is self.query_one("#dnd", Table)

    def hints(self) -> list[tuple[str, str]]:
        if self.in_dnd():
            return [("enter", "select"), ("tab", "history"), ("q", "quit")]
        return [("enter", "read"), ("c", "clear all"), ("tab", "do not disturb"), ("q", "quit")]

    def action_switch(self) -> None:
        self.query_one("#history" if self.in_dnd() else "#dnd", Table).focus()

    def action_down(self) -> None:
        if isinstance(self.app.focused, Table):
            self.app.focused.action_cursor_down()

    def action_up(self) -> None:
        if isinstance(self.app.focused, Table):
            self.app.focused.action_cursor_up()

    def action_clear(self) -> None:
        run(["dunstctl", "history-clear"])
        self.app.notify_ok("History cleared")
        self.reload()

    def dnd_cmd(self, *args: str, msg: str = "") -> None:
        run(["bash", str(DND), *args])
        if msg:
            self.app.notify_ok(msg)
        self.reload_dnd()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value
        if event.data_table.id == "history":
            n = next((n for n in self.items if str(n["id"]) == key), None)
            if n:
                self.app.push_screen(TextModal(n["appname"] or "Notification",
                                               f"{n['summary']}\n\n{n['body']}".strip(), end=False))
            return
        if event.data_table.id != "dnd":
            return
        if key == "toggle":
            on = not self.dnd["active"]
            self.dnd_cmd("--on" if on else "--off", msg="Do Not Disturb on" if on else "Do Not Disturb off")
        elif key in ("t3600", "t7200"):
            self.dnd_cmd("--timer", key[1:], msg=f"Do Not Disturb for {int(key[1:]) // 3600} h")
        elif key == "tmorning":
            now = datetime.now()
            target = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            self.dnd_cmd("--timer", str(int((target - now).total_seconds())),
                         msg="Do Not Disturb until 08:00")
        elif key == "tcustom":
            def done(v: Optional[dict]) -> None:
                if v:
                    secs = int(float(v["hours"]) * 3600)
                    self.dnd_cmd("--timer", str(secs), msg=f"Do Not Disturb for {v['hours']} h")

            def check(v: dict) -> Optional[str]:
                try:
                    return None if float(v["hours"]) > 0 else "Must be greater than 0"
                except ValueError:
                    return "Hours must be a number (e.g. 3 or 1.5)"

            self.app.push_screen(FormModal("Do Not Disturb for…", [Field("hours", "Hours", placeholder="e.g. 3")],
                                           validate=check), done)
        elif key.startswith("app:"):
            self.dnd_cmd("--app-toggle", key[4:])
        elif key == "add":
            seen = sorted({n["appname"] for n in self.items if n["appname"]})
            silenced = {a["app"] for a in self.dnd["apps"]}
            rows = [("-", [Text("✎  Type a name…", style="bold")])] + [
                (a, [a]) for a in seen if a not in silenced]

            def picked(app: Optional[str]) -> None:
                if app == "-":
                    self.app.push_screen(FormModal("Silence an app", [Field("app", "App name",
                                                                             placeholder="e.g. Discord")],
                                                   validate=lambda v: None if v["app"] else "The name is missing"),
                                         lambda v: v and self.dnd_cmd("--app-add", v["app"],
                                                                      msg=f"{v['app']} silenced"))
                elif app:
                    self.dnd_cmd("--app-add", app, msg=f"{app} silenced")

            self.app.push_screen(PickModal("Silence an app", ["App (from history)"], rows), picked)


# ── Displays ──────────────────────────────────────────────

WAYVNC = DOTFILES / "scripts" / "wayland" / "wayvnc-toggle.sh"


class DisplaysView(DView):
    """Monitores conectados, la tablet como monitor (wayvnc) y hyprmon (de
    terceros) en la misma ventana."""

    FOCUS = "#displays"

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="displays", show_header=False), title="󰍹  Displays", id="displays-panel")

    def on_mount(self) -> None:
        t = self.query_one("#displays", Table)
        t.add_column("", key="name", width=36)
        t.add_column("", key="info", width=70)
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#displays", Table)
        t.clear()
        muted, ok = THEME["muted"], THEME["status_ok"]
        if HYPRLAND:
            try:
                for m in json.loads(run(["hyprctl", "monitors", "-j"]).stdout):
                    t.add_row(Text(f"󰍹  {m['name']}"), Text(
                        f"{m['width']}x{m['height']}@{m['refreshRate']:.0f}Hz · scale {m['scale']:g} · "
                        f"{m.get('description', '')}", style=muted), key=f"mon:{m['name']}")
            except (ValueError, KeyError):
                pass
        st = run(["bash", str(WAYVNC), "status"])
        tablet = st.returncode == 0
        m = re.search(r"([\d.]+:\d+)\s*$", st.stdout.strip())   # "wayvnc activo (PID n) en <ip>:<puerto>"
        ip = m.group(1) if m else "<your IP>:5900"
        t.add_row(Text(f"{'●' if tablet else '○'}  Tablet as monitor", style=f"bold {ok}" if tablet else ""),
                  Text(f"on · connect the tablet's VNC app to {ip}" if tablet else
                       "off · enter to extend the desktop to a tablet over VNC (first time: "
                       "scripts/wayland/wayvnc-toggle.sh init)", style=muted),
                  key="tablet")
        t.add_row(Text("󰍹  Open display manager (hyprmon)", style=f"bold {THEME['primary']}"), "", key="open")
        t.move_cursor(row=t.row_count - 1)

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "select"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "displays":
            return
        key = event.row_key.value
        if key == "tablet":
            on = run(["bash", str(WAYVNC), "status"]).returncode == 0
            r = run(["bash", str(WAYVNC), "off" if on else "on"])
            if r.returncode == 0:
                self.app.notify_ok("Tablet monitor off" if on else "Tablet monitor on: connect from the tablet")
            else:
                self.app.notify_err((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout)
                                    else "wayvnc failed")
            self.reload()
        elif key == "open":
            if not shutil.which("hyprmon"):
                return self.app.notify_err("hyprmon is not installed")
            with self.app.suspend():
                subprocess.run(["hyprmon"])
            self.reload()


# ── Appearance ────────────────────────────────────────────

SHAPE_DEFAULTS = {"radius": 10, "opacity": 0.80, "blur_enabled": True, "blur_size": 6, "blur_passes": 2}


class AppearanceView(DView):
    """Forma del tema activo (radius, opacity, blur): se guarda en su copia de
    ~/.config/dotfiles/themes/ y se reaplica con theme-switch.sh, así llega a
    todas las apps sin tocar themes/ del repo."""

    FOCUS = "#shape"

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="shape"), title="󰉼  Appearance", id="shape-panel")

    def on_mount(self) -> None:
        t = self.query_one("#shape", Table)
        t.add_column("Setting", key="name", width=22)
        t.add_column("Value", key="value", width=14)
        t.add_column("", key="desc", width=70)
        self.reload()

    def shape(self) -> dict:
        d = active_theme_dir()
        data = json.loads((d / "theme.json").read_text()) if d else {}
        return {k: data.get(k, v) for k, v in SHAPE_DEFAULTS.items()} | {"_custom": [k for k in SHAPE_DEFAULTS
                                                                                      if k in data]}

    def reload(self) -> None:
        t = self.query_one("#shape", Table)
        sh = self.shape()
        rows = [
            ("radius", "Corner radius", f"{sh['radius']} px", "windows, waybar, rofi, dunst, gtklock, OSDs"),
            ("opacity", "Opacity", f"{float(sh['opacity']):.2f}",
             "kitty base; rofi −0.05, other apps +0.05 (≥ 0.98 = fully opaque)"),
            ("blur_enabled", "Blur", "on" if sh["blur_enabled"] in (True, "true") else "off",
             "Hyprland background blur"),
            ("blur_size", "Blur size", str(sh["blur_size"]), "blur radius"),
            ("blur_passes", "Blur passes", str(sh["blur_passes"]), "more passes = smoother, heavier"),
        ]
        row = t.cursor_row or 0
        t.clear()
        for key, name, value, desc in rows:
            v = Text(value, style="bold" if key in sh["_custom"] else THEME["muted"])
            t.add_row(name, v, Text(desc, style=THEME["muted"]), key=key)
        t.move_cursor(row=row)
        d = active_theme_dir()
        self.query_one("#shape-panel").border_subtitle = (f" theme: {d.name}{' (yours)' if is_user_theme(d) else ''}"
                                                          " · bold = set by the theme, dim = default "
                                                          if d else " no active theme ")

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "edit"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "shape":
            return
        key, sh = event.row_key.value, self.shape()
        d = active_theme_dir()
        if not d:
            return self.app.notify_err("No active theme found")
        if key == "blur_enabled":
            return self.save(d, key, not (sh[key] in (True, "true")))
        limits = {"radius": (0, 30, int), "opacity": (0.5, 1.0, float), "blur_size": (1, 20, int),
                  "blur_passes": (1, 6, int)}
        lo, hi, kind = limits[key]

        def check(v: dict) -> Optional[str]:
            try:
                n = kind(v["value"])
            except ValueError:
                return f"Must be a {'whole ' if kind is int else ''}number"
            return None if lo <= n <= hi else f"Must be between {lo} and {hi}"

        def done(v: Optional[dict]) -> None:
            if v:
                self.save(d, key, kind(v["value"]))

        self.app.push_screen(FormModal(f"{key.replace('_', ' ').capitalize()} · {d.name}",
                                       [Field("value", f"Value ({lo}–{hi})", str(sh[key]))],
                                       hint="Saved in your copy of the theme (~/.config/dotfiles/themes) "
                                            "and applied to every app.",
                                       validate=check), done)

    def save(self, d: Path, key: str, value) -> None:
        d = editable_theme_dir(d)
        f = d / "theme.json"
        data = json.loads(f.read_text())
        data[key] = value
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        self.query_one("#shape-panel").border_subtitle = " applying… "
        self.apply(d.name)

    @work(thread=True, exclusive=True)
    def apply(self, theme_dir: str) -> None:
        subprocess.run(["bash", str(THEME_SWITCH), theme_dir], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)
        self.app.call_from_thread(self.app.restart, "appearance")


# ── Audio ─────────────────────────────────────────────────

def audio_nodes() -> list[dict]:
    """Salidas y entradas de PipeWire: [{id, kind (sink|source), desc}]."""
    try:
        dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    out = []
    for n in dump:
        props = (n.get("info") or {}).get("props") or {}
        cls = props.get("media.class")
        if n.get("type") == "PipeWire:Interface:Node" and cls in ("Audio/Sink", "Audio/Source"):
            out.append({"id": n["id"], "kind": "sink" if cls == "Audio/Sink" else "source",
                        "desc": props.get("node.description") or props.get("node.name", "?")})
    return out


def default_id(kind: str) -> Optional[int]:
    r = run(["wpctl", "inspect", f"@DEFAULT_AUDIO_{kind.upper()}@"])
    m = re.match(r"id (\d+),", r.stdout)
    return int(m.group(1)) if m else None


def volume(target: str) -> tuple[float, bool]:
    """(volumen 0-1.5, silenciado) de un nodo o @DEFAULT_AUDIO_SINK@."""
    r = run(["wpctl", "get-volume", str(target)])
    m = re.search(r"Volume: ([\d.]+)", r.stdout)
    return (float(m.group(1)) if m else 0.0), "MUTED" in r.stdout


class AudioView(DView):
    """Salidas y entradas (wpctl): enter la hace la predeterminada, ←/→ o -/+
    cambian el volumen, m silencia."""

    FOCUS = "#outputs"
    DEFAULT_CSS = css("""
    #outputs-panel, #inputs-panel { height: auto; max-height: 50%%; }
    AudioView DataTable { height: auto; max-height: 100%%; }
    """)
    BINDINGS = [
        Binding("tab", "switch", show=False),
        Binding("shift+tab", "switch", show=False),
        Binding("left,minus", "vol(-5)", "volume -"),
        Binding("right,plus,equals_sign", "vol(5)", "volume +"),
        Binding("m", "mute", "mute"),
        Binding("j", "down", show=False),
        Binding("k", "up", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="outputs"), title="󰓃  Outputs", id="outputs-panel")
        yield Panel(Table(id="inputs"), title="󰍬  Inputs", id="inputs-panel")

    def on_mount(self) -> None:
        for tid in ("outputs", "inputs"):
            t = self.query_one(f"#{tid}", Table)
            t.add_column("Device", key="name", width=52)
            t.add_column("Volume", key="vol", width=28)
        self.reload()

    def reload(self) -> None:
        nodes = audio_nodes()
        for kind, tid in (("sink", "outputs"), ("source", "inputs")):
            t = self.query_one(f"#{tid}", Table)
            row = t.cursor_row or 0
            t.clear()
            dflt = default_id(kind)
            for n in (n for n in nodes if n["kind"] == kind):
                vol, muted = volume(n["id"])
                name = Text(f"{'●' if n['id'] == dflt else '○'}  {n['desc']}",
                            style=f"bold {THEME['status_ok']}" if n["id"] == dflt else "")
                v = bar(min(vol, 1.0) * 100, 14)
                v.append(f" {vol * 100:3.0f}%", style="bold")
                if muted:
                    v = Text("󰝟  muted", style=THEME["status_warn"])
                t.add_row(name, v, key=str(n["id"]))
            if t.row_count:
                t.move_cursor(row=min(row, t.row_count - 1))
            self.query_one(f"#{tid}-panel").border_subtitle = "" if t.row_count else " no devices "

    def table(self) -> Table:
        f = self.app.focused
        return f if isinstance(f, Table) and f.id in ("outputs", "inputs") else self.query_one("#outputs", Table)

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "set default"), ("←/→", "volume"), ("m", "mute"), ("tab", "inputs/outputs"),
                ("q", "quit")]

    def action_switch(self) -> None:
        self.query_one("#inputs" if self.table().id == "outputs" else "#outputs", Table).focus()

    def action_down(self) -> None:
        self.table().action_cursor_down()

    def action_up(self) -> None:
        self.table().action_cursor_up()

    def action_vol(self, step: int) -> None:
        if key := self.table().selected_key():
            run(["wpctl", "set-volume", "-l", "1.5", key, f"{abs(step)}%{'+' if step > 0 else '-'}"])
            self.reload()

    def action_mute(self) -> None:
        if key := self.table().selected_key():
            run(["wpctl", "set-mute", key, "toggle"])
            self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id in ("outputs", "inputs"):
            run(["wpctl", "set-default", event.row_key.value])
            self.app.notify_ok("Default device changed")
            self.reload()


# ── Wi-Fi ─────────────────────────────────────────────────

def signal_bars(pct: int) -> Text:
    """▂▄▆█ según la señal (cuatro escalones), coloreado por calidad."""
    n = 4 if pct >= 75 else 3 if pct >= 50 else 2 if pct >= 25 else 1
    c = THEME["status_ok"] if pct >= 50 else THEME["status_warn"] if pct >= 25 else THEME["status_error"]
    t = Text()
    for i, ch in enumerate("▂▄▆█"):
        t.append(ch, style=c if i < n else THEME["border"])
    return t


def split_terse(line: str) -> list[str]:
    """`nmcli -t` separa con ':' y escapa los ':' internos como '\\:'."""
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


def wifi_device() -> Optional[str]:
    for line in run(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"]).stdout.splitlines():
        dev, _, kind = line.partition(":")
        if kind == "wifi":
            return dev
    return None


class WifiView(DView):
    """Estado de la conexión + redes (la actual, las guardadas, el resto por
    señal). enter conecta (pide contraseña si hace falta) o desconecta."""

    FOCUS = "#wifi-list"
    DEFAULT_CSS = css("""
    #wifi-status-panel { height: auto; }
    #wifi-status { height: auto; }
    #wifi-list-panel { height: 1fr; }
    """)
    BINDINGS = [
        Binding("d", "disconnect", "disconnect"),
        Binding("f", "forget", "forget"),
        Binding("r", "rescan", "rescan"),
        Binding("w", "radio", "wi-fi on/off"),
        Binding("o", "impala", "impala"),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Static(id="wifi-status"), title="󰖩  Wi-Fi", id="wifi-status-panel")
        yield Panel(Table(id="wifi-list"), title="Networks", id="wifi-list-panel")

    def on_mount(self) -> None:
        t = self.query_one("#wifi-list", Table)
        t.add_column("", key="sig", width=6)
        t.add_column("Network", key="ssid", width=36)
        t.add_column("Security", key="sec", width=14)
        t.add_column("Band", key="band", width=8)
        t.add_column("", key="state", width=30)
        self.nets: dict[str, dict] = {}
        self.reload()
        self.set_interval(10, self.tick)

    def tick(self) -> None:
        if self.visible_now and not self.busy:
            self.reload()

    busy = ""

    def reload(self, rescan: bool = False) -> None:
        self.load(rescan)

    @work(thread=True, exclusive=True, group="wifi")
    def load(self, rescan: bool = False) -> None:
        dev = wifi_device()
        radio = run(["nmcli", "radio", "wifi"]).stdout.strip() == "enabled"
        nets: dict[str, dict] = {}
        if radio:
            args = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,CHAN,RATE", "dev", "wifi", "list"]
            if rescan:
                args += ["--rescan", "yes"]
            for line in subprocess.run(args, capture_output=True, text=True, timeout=30).stdout.splitlines():
                f = split_terse(line)
                if len(f) < 6 or not f[1]:
                    continue
                n = {"active": f[0] == "*", "ssid": f[1], "signal": int(f[2] or 0), "sec": f[3],
                     "chan": int(f[4] or 0), "rate": f[5]}
                old = nets.get(n["ssid"])
                if not old or n["active"] or (n["signal"] > old["signal"] and not old["active"]):
                    nets[n["ssid"]] = n
        saved = {split_terse(l)[0] for l in run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"]).stdout.splitlines()
                 if l.endswith(":802-11-wireless")}
        ip = ""
        if dev:
            for l in run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", dev]).stdout.splitlines():
                ip = l.partition(":")[2].split("/")[0]
                break
        self.app.call_from_thread(self.show, dev, radio, nets, saved, ip)

    def show(self, dev: Optional[str], radio: bool, nets: dict, saved: set, ip: str) -> None:
        self.nets, self.saved = nets, saved
        ok, muted = THEME["status_ok"], THEME["muted"]
        cur = next((n for n in nets.values() if n["active"]), None)
        st = Text()
        if not dev:
            st.append("○  no Wi-Fi adapter found", style=muted)
        elif not radio:
            st.append("○  Wi-Fi is off", style=muted)
            st.append("   press w to turn it on", style=muted)
        elif cur:
            st.append(f"●  Connected to {cur['ssid']}   ", style=f"bold {ok}")
            st.append_text(signal_bars(cur["signal"]))
            st.append(f" {cur['signal']}%\n", style=ok)
            band = "5 GHz" if cur["chan"] > 14 else "2.4 GHz"
            st.append(f"   {ip or 'no IP yet'} · {dev} · channel {cur['chan']} ({band}) · {cur['rate']}",
                      style=muted)
        else:
            st.append("○  Not connected", style=muted)
            st.append(f"   {dev}", style=muted)
        if self.busy:
            st.append(f"\n   {self.busy}", style=THEME["status_warn"])
        self.query_one("#wifi-status", Static).update(st)

        t = self.query_one("#wifi-list", Table)
        prev = t.selected_key()
        t.clear()
        order = sorted(nets.values(), key=lambda n: (not n["active"], n["ssid"] not in saved, -n["signal"]))
        for n in order:
            secure = n["sec"] not in ("", "--")
            sec = Text(f" {n['sec']}" if secure else "open", style=muted if secure else THEME["status_warn"])
            if n["active"]:
                state = Text("● connected", style=f"bold {ok}")
            elif n["ssid"] in saved:
                state = Text("saved", style=ok)
            else:
                state = Text("")
            name = Text(n["ssid"], style=f"bold {ok}" if n["active"] else "")
            t.add_row(signal_bars(n["signal"]), name, sec, Text("5G" if n["chan"] > 14 else "2.4G", style=muted),
                      state, key=n["ssid"])
        keys = [n["ssid"] for n in order]
        t.move_cursor(row=keys.index(prev) if prev in keys else 0)
        self.query_one("#wifi-list-panel").border_subtitle = (f" {len(nets)} networks · {len(saved)} saved "
                                                              if radio else " wi-fi off ")
        self.update_hints()

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "connect"), ("d", "disconnect"), ("f", "forget"), ("r", "rescan"), ("w", "on/off"),
                ("o", "impala"), ("q", "quit")]

    # ── acciones ──

    def set_busy(self, msg: str) -> None:
        self.busy = msg
        self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "wifi-list":
            return
        n = self.nets.get(str(event.row_key.value))
        if not n:
            return
        if n["active"]:
            return self.app.notify_ok(f"Already connected to {n['ssid']}")
        if n["ssid"] in self.saved or n["sec"] in ("", "--"):
            return self.connect(n["ssid"])

        def done(v: Optional[dict]) -> None:
            if v:
                self.connect(n["ssid"], v["password"])

        self.app.push_screen(FormModal(f"Connect to {n['ssid']}",
                                       [Field("password", f"Password ({n['sec']})", password=True)],
                                       validate=lambda v: None if len(v["password"]) >= 8 else
                                       "WPA passwords have at least 8 characters"), done)

    @work(thread=True, exclusive=True, group="wifi-action")
    def connect(self, ssid: str, password: str = "") -> None:
        self.app.call_from_thread(self.set_busy, f"connecting to {ssid}…")
        if ssid in self.saved and not password:
            args = ["nmcli", "con", "up", "id", ssid]
        else:
            args = ["nmcli", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
        r = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            self.app.call_from_thread(self.app.notify_ok, f"Connected to {ssid}")
        else:
            err = (r.stderr or r.stdout).strip().splitlines()
            self.app.call_from_thread(self.app.notify_err, err[-1] if err else "connection failed")
        self.app.call_from_thread(self.set_busy, "")

    def action_disconnect(self) -> None:
        dev = wifi_device()
        if dev:
            r = run(["nmcli", "dev", "disconnect", dev])
            self.app.notify_ok("Wi-Fi disconnected") if r.returncode == 0 else self.app.notify_err(r.stderr.strip())
            self.reload()

    def action_forget(self) -> None:
        ssid = self.query_one("#wifi-list", Table).selected_key()
        if not ssid or ssid not in self.saved:
            return self.app.notify_err("That network is not saved")

        def done(yes: bool) -> None:
            if yes:
                run(["nmcli", "con", "delete", "id", ssid])
                self.app.notify_ok(f"{ssid} forgotten")
                self.reload()

        self.app.push_screen(ConfirmModal("Forget network", f"Forget {ssid} and its saved password?"), done)

    def action_rescan(self) -> None:
        self.busy = "scanning…"
        self.reload(rescan=True)
        self.set_timer(6, lambda: setattr(self, "busy", ""))

    def action_radio(self) -> None:
        on = run(["nmcli", "radio", "wifi"]).stdout.strip() == "enabled"
        run(["nmcli", "radio", "wifi", "off" if on else "on"])
        self.app.notify_ok("Wi-Fi off" if on else "Wi-Fi on")
        self.set_timer(1.5, self.reload)

    def action_impala(self) -> None:
        if not shutil.which("impala"):
            return self.app.notify_err("impala is not installed")
        with self.app.suspend():
            subprocess.run(["impala"])
        self.reload()


# ── Bluetooth ─────────────────────────────────────────────

BT_ICONS = {"audio-headset": "󰋋", "audio-headphones": "󰋋", "audio-card": "󰓃", "input-keyboard": "󰌌",
            "input-mouse": "󰍽", "input-gaming": "󰊴", "input-tablet": "󰓶", "phone": "󰏲", "computer": "󰟀",
            "video-display": "󰔂", "multimedia-player": "󰐌", "printer": "󰐪", "camera-photo": "󰄀"}


def bt_info(mac: str) -> dict:
    """Datos de `bluetoothctl info` que se muestran."""
    out = run(["bluetoothctl", "info", mac]).stdout
    get = lambda k: (m.group(1).strip() if (m := re.search(rf"^\s*{k}: (.*)$", out, re.M)) else "")  # noqa: E731
    battery = re.search(r"Battery Percentage: 0x[0-9a-f]+ \((\d+)\)", out)
    return {"mac": mac, "name": get("Name") or get("Alias") or mac, "icon": get("Icon"),
            "paired": get("Paired") == "yes", "trusted": get("Trusted") == "yes",
            "connected": get("Connected") == "yes", "battery": int(battery.group(1)) if battery else None}


class BluetoothView(DView):
    """Estado del adaptador + dispositivos agrupados (conectados, emparejados,
    disponibles). enter conecta/desconecta y empareja si hace falta."""

    FOCUS = "#bt-list"
    DEFAULT_CSS = css("""
    #bt-status-panel { height: auto; }
    #bt-status { height: auto; }
    #bt-list-panel { height: 1fr; }
    """)
    BINDINGS = [
        Binding("s", "scan", "scan"),
        Binding("t", "trust", "trust"),
        Binding("x", "remove", "forget"),
        Binding("b", "power", "bluetooth on/off"),
        Binding("o", "bluetui", "bluetui"),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Static(id="bt-status"), title="󰂯  Bluetooth", id="bt-status-panel")
        yield Panel(Table(id="bt-list"), title="Devices", id="bt-list-panel")

    def on_mount(self) -> None:
        t = self.query_one("#bt-list", Table)
        t.add_column("Device", key="name", width=38)
        t.add_column("State", key="state", width=22)
        t.add_column("Battery", key="bat", width=16)
        t.add_column("Address", key="mac", width=20)
        self.devices: list[dict] = []
        self.busy = ""
        self.reload()
        self.set_interval(10, self.tick)

    def tick(self) -> None:
        if self.visible_now and not self.busy:
            self.reload()

    def reload(self) -> None:
        self.load()

    @work(thread=True, exclusive=True, group="bt")
    def load(self) -> None:
        show = run(["bluetoothctl", "show"]).stdout
        get = lambda k: (m.group(1).strip() if (m := re.search(rf"^\s*{k}: (.*)$", show, re.M)) else "")  # noqa: E731
        ctrl = {"name": get("Name") or get("Alias"), "powered": get("Powered") == "yes",
                "discoverable": get("Discoverable") == "yes", "scanning": get("Discovering") == "yes",
                "present": bool(show.strip())}
        macs = [l.split()[1] for l in run(["bluetoothctl", "devices"]).stdout.splitlines()
                if l.startswith("Device ")]
        devices = [bt_info(m) for m in macs]
        self.app.call_from_thread(self.show, ctrl, devices)

    def show(self, ctrl: dict, devices: list[dict]) -> None:
        self.devices = devices
        ok, muted, warn = THEME["status_ok"], THEME["muted"], THEME["status_warn"]
        st = Text()
        if not ctrl["present"]:
            st.append("○  no Bluetooth adapter found", style=muted)
        elif not ctrl["powered"]:
            st.append("○  Bluetooth is off", style=muted)
            st.append("   press b to turn it on", style=muted)
        else:
            conn = [d["name"] for d in devices if d["connected"]]
            st.append("●  On", style=f"bold {ok}")
            st.append(f"   {ctrl['name']}", style="bold")
            st.append(f" · {'visible to others' if ctrl['discoverable'] else 'hidden'}", style=muted)
            st.append(f" · {len(conn)} connected", style=ok if conn else muted)
            if ctrl["scanning"]:
                st.append(" · scanning…", style=warn)
        if self.busy:
            st.append(f"\n   {self.busy}", style=warn)
        self.query_one("#bt-status", Static).update(st)

        t = self.query_one("#bt-list", Table)
        prev = t.selected_key()
        t.clear()
        groups = [("Connected", [d for d in devices if d["connected"]]),
                  ("Paired", [d for d in devices if d["paired"] and not d["connected"]]),
                  ("Available", [d for d in devices if not d["paired"] and not d["connected"]])]
        for label, devs in groups:
            if not devs:
                continue
            t.add_row(Text(label.upper(), style=f"bold {THEME['primary']}"), "", "", "", key=f"hdr:{label}")
            for d in sorted(devs, key=lambda d: d["name"].lower()):
                icon = BT_ICONS.get(d["icon"], "󰂯")
                name = Text(f"{icon}  {d['name']}", style=f"bold {ok}" if d["connected"] else "")
                if d["connected"]:
                    state = Text("● connected", style=ok)
                elif d["paired"]:
                    state = Text("○ paired", style=muted)
                else:
                    state = Text("not paired", style=muted)
                if d["trusted"]:
                    state.append(" · trusted", style=muted)
                bat = charge10(d["battery"]) if d["battery"] is not None else Text("—", style=muted)
                t.add_row(name, state, bat, Text(d["mac"], style=muted), key=d["mac"])
        rows = [str(r.key.value) for r in t.ordered_rows]
        t.first_selectable(rows.index(prev) if prev in rows else 0)
        self.query_one("#bt-list-panel").border_subtitle = (f" {len(devices)} known · s to scan for new ones "
                                                            if ctrl["powered"] else " bluetooth off ")
        self.update_hints()

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "connect/disconnect"), ("s", "scan"), ("t", "trust"), ("x", "forget"),
                ("b", "on/off"), ("o", "bluetui"), ("q", "quit")]

    def device(self) -> Optional[dict]:
        mac = self.query_one("#bt-list", Table).selected_key()
        return next((d for d in self.devices if d["mac"] == mac), None)

    def set_busy(self, msg: str) -> None:
        self.busy = msg
        self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "bt-list" and (d := self.device()):
            self.toggle(d)

    @work(thread=True, exclusive=True, group="bt-action")
    def toggle(self, d: dict) -> None:
        call = self.app.call_from_thread
        if d["connected"]:
            call(self.set_busy, f"disconnecting {d['name']}…")
            r = run(["bluetoothctl", "disconnect", d["mac"]])
            ok_msg = f"{d['name']} disconnected"
        else:
            if not d["paired"]:
                call(self.set_busy, f"pairing {d['name']}…")
                r = subprocess.run(["bluetoothctl", "--timeout", "20", "pair", d["mac"]],
                                   capture_output=True, text=True, timeout=30)
                if "Pairing successful" not in r.stdout and "AlreadyExists" not in r.stdout:
                    call(self.app.notify_err, f"Could not pair {d['name']}")
                    return call(self.set_busy, "")
                run(["bluetoothctl", "trust", d["mac"]])
            call(self.set_busy, f"connecting {d['name']}…")
            r = subprocess.run(["bluetoothctl", "--timeout", "15", "connect", d["mac"]],
                               capture_output=True, text=True, timeout=25)
            ok_msg = f"{d['name']} connected"
        if r.returncode == 0 and "Failed" not in r.stdout:
            call(self.app.notify_ok, ok_msg)
        else:
            err = (r.stdout or r.stderr).strip().splitlines()
            call(self.app.notify_err, f"{d['name']}: {err[-1] if err else 'failed'}")
        call(self.set_busy, "")

    @work(thread=True, exclusive=True, group="bt-action")
    def action_scan(self) -> None:
        self.app.call_from_thread(self.set_busy, "scanning for 12 s… put the device in pairing mode")
        subprocess.run(["bluetoothctl", "--timeout", "12", "scan", "on"], capture_output=True, timeout=20)
        self.app.call_from_thread(self.set_busy, "")

    def action_trust(self) -> None:
        if d := self.device():
            run(["bluetoothctl", "untrust" if d["trusted"] else "trust", d["mac"]])
            self.app.notify_ok(f"{d['name']} {'untrusted' if d['trusted'] else 'trusted'}")
            self.reload()

    def action_remove(self) -> None:
        d = self.device()
        if not d:
            return

        def done(yes: bool) -> None:
            if yes:
                run(["bluetoothctl", "remove", d["mac"]])
                self.app.notify_ok(f"{d['name']} forgotten")
                self.reload()

        self.app.push_screen(ConfirmModal("Forget device", f"Forget {d['name']}? You'll have to pair it again."),
                             done)

    def action_power(self) -> None:
        on = "Powered: yes" in run(["bluetoothctl", "show"]).stdout
        run(["bluetoothctl", "power", "off" if on else "on"])
        self.app.notify_ok("Bluetooth off" if on else "Bluetooth on")
        self.set_timer(1, self.reload)

    def action_bluetui(self) -> None:
        if not shutil.which("bluetui"):
            return self.app.notify_err("bluetui is not installed")
        with self.app.suspend():
            subprocess.run(["bluetui"])
        self.reload()


# ── Power ─────────────────────────────────────────────────

# hypridle lee ~/.config/hypr/hypridle.conf, que es config/hypr del repo:
# el archivo es generado y está en .gitignore.
IDLE_CONF = DOTFILES / "config" / "hypr" / "hypridle.conf"
IDLE_DEFAULTS = {"lock": 10, "screen": 15, "suspend": 0}   # minutos (0 = nunca)
PROFILE_DESC = {"power-saver": "less heat and noise, longer battery", "balanced": "default",
                "performance": "maximum speed, more power"}


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
        "# hypridle.conf — generado por Settings → Power (tools/settings/settings_tui.py).",
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
    IDLE_CONF.write_text("\n".join(lines) + "\n")


def unit_state(unit: str) -> tuple[bool, bool]:
    """(activo, habilitado) de una unit de systemd --user."""
    active = run(["systemctl", "--user", "is-active", unit]).stdout.strip() == "active"
    enabled = run(["systemctl", "--user", "is-enabled", unit]).stdout.strip() in ("enabled", "linked", "static")
    return active, enabled


class PowerView(DView):
    """Perfil de energía, brillo y bloqueo/apagado/suspensión por inactividad."""

    FOCUS = "#power"
    BINDINGS = [
        Binding("left,minus", "bright(-5)", "brightness -"),
        Binding("right,plus,equals_sign", "bright(5)", "brightness +"),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="power", show_header=False), title="󰂄  Power", id="power-panel")

    def on_mount(self) -> None:
        t = self.query_one("#power", Table)
        t.add_column("", key="name", width=34)
        t.add_column("", key="value", width=30)
        t.add_column("", key="desc", width=44)
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#power", Table)
        row = t.cursor_row or 0
        t.clear()
        ok, muted = THEME["status_ok"], THEME["muted"]
        cur = run(["powerprofilesctl", "get"]).stdout.strip()
        for p in ("power-saver", "balanced", "performance") if cur else ():
            t.add_row(Text(f"{'●' if p == cur else '○'}  Profile: {p}", style=f"bold {ok}" if p == cur else ""),
                      "", Text(PROFILE_DESC[p], style=muted), key=f"profile:{p}")
        b = run(["brightnessctl", "-m"]).stdout.split(",")
        if len(b) >= 4:
            pct = int(b[3].rstrip("%"))
            v = bar(pct, 14)
            v.append(f" {pct:3d}%", style="bold")
            t.add_row("󰃠  Brightness", v, Text("←/→ to change", style=muted), key="brightness")
        st, (active, _en) = idle_settings(), unit_state("hypridle.service")
        if not shutil.which("hypridle"):
            t.add_row(Text("○  Idle actions", style=muted), Text("not available", style=muted),
                      Text("install hypridle to lock / suspend when idle", style=muted), key="noidle")
            t.move_cursor(row=min(row, t.row_count - 1))
            return
        t.add_row(Text(f"{'●' if active else '○'}  Idle actions", style=f"bold {ok}" if active else ""),
                  Text("on" if active else "off", style=ok if active else muted),
                  Text("hypridle: lock, screen off and suspend when idle", style=muted), key="idle")
        for k, label in (("lock", "Lock screen after"), ("screen", "Turn screen off after"),
                         ("suspend", "Suspend after")):
            t.add_row(f"   {label}", f"{st[k]} min" if st[k] else Text("never", style=muted), "", key=f"idle:{k}")
        t.move_cursor(row=min(row, t.row_count - 1))

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "select / edit"), ("←/→", "brightness"), ("q", "quit")]

    def action_bright(self, step: int) -> None:
        run(["brightnessctl", "set", f"{abs(step)}%{'+' if step > 0 else '-'}"])
        self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "power":
            return
        key = event.row_key.value
        if key.startswith("profile:"):
            r = run(["powerprofilesctl", "set", key[8:]])
            self.app.notify_ok(f"Profile: {key[8:]}") if r.returncode == 0 else self.app.notify_err(r.stderr.strip())
        elif key == "idle":
            active, _ = unit_state("hypridle.service")
            if not active:
                if not IDLE_CONF.exists():
                    write_idle_conf(idle_settings())
                run(["systemctl", "--user", "enable", "--now", "hypridle.service"])
                self.app.notify_ok("Idle actions on")
            else:
                run(["systemctl", "--user", "disable", "--now", "hypridle.service"])
                self.app.notify_ok("Idle actions off")
        elif key.startswith("idle:"):
            k, st = key[5:], idle_settings()

            def check(v: dict) -> Optional[str]:
                return None if v["min"].isdigit() and int(v["min"]) <= 600 else "Minutes from 0 to 600 (0 = never)"

            def done(v: Optional[dict]) -> None:
                if not v:
                    return
                st[k] = int(v["min"])
                write_idle_conf(st)
                if unit_state("hypridle.service")[0]:
                    run(["systemctl", "--user", "restart", "hypridle.service"])
                self.reload()

            return self.app.push_screen(FormModal("Idle time", [Field("min", "Minutes (0 = never)", str(st[k]))],
                                                  validate=check), done)
        elif key in ("brightness", "noidle"):
            return
        self.reload()


# ── Services ──────────────────────────────────────────────

# Servicios de usuario que se muestran si están instalados (unit file presente)
KNOWN_SERVICES = [
    ("elephant.service", "Walker backend (apps, calculator, web search)"),
    ("hypridle.service", "Idle lock / screen off / suspend (see Power)"),
    ("battery-watch.timer", "Low battery notifications"),
    ("wayvnc.service", "VNC server (tablet as a monitor, see Displays)"),
    ("hyprland-session-init.service", "Starts graphical-session.target for portals"),
    ("cliphist.service", "Clipboard history daemon"),
    ("hyprshell.service", "Window switcher and workspace overview"),
    ("kdeconnect.service", "KDE Connect (phone integration)"),
    ("mpris-proxy.service", "Bluetooth media buttons"),
    ("ydotool.service", "Input automation daemon"),
    ("syncthing.service", "File synchronization"),
    ("onedrive.service", "OneDrive sync"),
]


def user_services() -> list[tuple[str, str]]:
    """Los de KNOWN_SERVICES que estén instalados (sin los de audio ni los del
    sistema base, que no conviene parar desde acá)."""
    out = run(["systemctl", "--user", "list-unit-files", "--no-legend", "--plain",
               "--type=service,timer"]).stdout.splitlines()
    files = {l.split()[0] for l in out if l.strip()}
    return [(u, d) for u, d in KNOWN_SERVICES if u in files]


class ServicesView(DView):
    """systemd --user: enter arranca/para, e habilita/deshabilita al inicio."""

    FOCUS = "#services"
    BINDINGS = [Binding("e", "enable", "enable at login"), Binding("l", "logs", "logs")]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="services"), title="\uf013  Services", id="services-panel")

    def on_mount(self) -> None:
        t = self.query_one("#services", Table)
        t.add_column("Service", key="name", width=24)
        t.add_column("State", key="state", width=14)
        t.add_column("At login", key="boot", width=10)
        t.add_column("", key="desc", width=60)
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#services", Table)
        row = t.cursor_row or 0
        t.clear()
        ok, muted = THEME["status_ok"], THEME["muted"]
        for unit, desc in user_services():
            active, enabled = unit_state(unit)
            t.add_row(unit.rsplit(".", 1)[0], Text("●  running", style=ok) if active else Text("○  stopped", style=muted),
                      Text("yes", style=ok) if enabled else Text("no", style=muted), Text(desc, style=muted), key=unit)
        t.move_cursor(row=min(row, t.row_count - 1))
        self.query_one("#services-panel").border_subtitle = " systemctl --user "

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "start/stop"), ("e", "at login on/off"), ("l", "logs"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "services":
            return
        unit = event.row_key.value
        active, _ = unit_state(unit)
        r = run(["systemctl", "--user", "stop" if active else "start", unit])
        if r.returncode == 0:
            self.app.notify_ok(f"{unit} {'stopped' if active else 'started'}")
        else:
            self.app.notify_err(r.stderr.strip() or f"could not {'stop' if active else 'start'} {unit}")
        self.reload()

    def action_enable(self) -> None:
        unit = self.query_one("#services", Table).selected_key()
        if not unit:
            return
        _, enabled = unit_state(unit)
        r = run(["systemctl", "--user", "disable" if enabled else "enable", unit])
        if r.returncode == 0:
            self.app.notify_ok(f"{unit}: {'not started' if enabled else 'started'} at login")
        else:
            self.app.notify_err(r.stderr.strip() or "systemctl failed")
        self.reload()

    def action_logs(self) -> None:
        unit = self.query_one("#services", Table).selected_key()
        if unit:
            r = run(["journalctl", "--user", "-u", unit, "-n", "200", "--no-pager"])
            self.app.push_screen(TextModal(f"Logs · {unit}", r.stdout or r.stderr or "(empty)"))


# ── System ────────────────────────────────────────────────

# Dónde buscar clones de git (y qué saltear para que el escaneo sea instantáneo)
def repo_roots() -> list[Path]:
    """$HOME + EXTRA_REPO_DIRS de user.conf (separadas por ':')."""
    extra = user_conf().get("EXTRA_REPO_DIRS", "")
    return [Path.home()] + [Path(os.path.expandvars(d)).expanduser() for d in extra.split(":") if d]



REPO_SKIP = ("node_modules", ".cache", "SteamLibrary", "VMs", ".local", ".cargo", ".rustup", "go")


def scan_repos() -> list[dict]:
    """Clones locales con remoto en GitHub: [{path, slug (owner/name), url}]."""
    args = ["find", *map(str, (r for r in repo_roots() if r.exists())), "-maxdepth", "5", "("]
    for i, name in enumerate(REPO_SKIP):
        args += (["-o"] if i else []) + ["-name", name]
    args += [")", "-prune", "-o", "-name", ".git", "-print", "-prune"]
    try:
        found = subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        found = []
    out = []
    for g in found:
        path = Path(g).parent
        url = run(["git", "-C", str(path), "remote", "get-url", "origin"]).stdout.strip()
        m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", url)
        if m:
            out.append({"path": path, "slug": f"{m.group(1)}/{m.group(2)}", "url": url})
    return out


def repo_state(path: Path) -> dict:
    """Branch, cambios sin commitear y ahead/behind respecto del último fetch."""
    head = run(["git", "-C", str(path), "status", "--porcelain=v1", "--branch"]).stdout.splitlines()
    first = head[0][3:] if head else ""
    return {"branch": first.split("...")[0] or "?", "changes": max(0, len(head) - 1),
            "ahead": int(m.group(1)) if (m := re.search(r"ahead (\d+)", first)) else 0,
            "behind": int(m.group(1)) if (m := re.search(r"behind (\d+)", first)) else 0}


def disk_mounts() -> list[str]:
    """Puntos de montaje de discos reales (uno por dispositivo, sin /boot)."""
    seen, out = set(), []
    try:
        lines = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return ["/"]
    for l in lines:
        dev, mnt = l.split()[:2]
        mnt = mnt.replace("\\040", " ")
        if not dev.startswith("/dev/") or dev.startswith("/dev/loop") or mnt.startswith(("/boot", "/efi")) \
                or dev in seen:
            continue
        seen.add(dev)
        out.append(mnt)
    return sorted(out, key=lambda m: (m != "/", m))[:4] or ["/"]


class SystemView(DView):
    """Recursos del sistema (barras estilo statusline), repos de GitHub
    (clones locales + los de tu cuenta sin clonar, vía gh) y dotfiles-doctor."""

    FOCUS = "#repos"
    DEFAULT_CSS = css("""
    #sysinfo-panel { height: auto; }
    #sysinfo { height: auto; }
    #repos-panel { height: 1fr; }
    """)
    BINDINGS = [Binding("f", "fetch", "fetch all"), Binding("r", "rescan", "rescan")]

    def compose(self) -> ComposeResult:
        yield Panel(Static(id="sysinfo"), title="󰌢  System", id="sysinfo-panel")
        yield Panel(Table(id="repos"), title="  GitHub repositories", id="repos-panel")

    def on_mount(self) -> None:
        t = self.query_one("#repos", Table)
        t.add_column("Repository", key="name", width=34)
        t.add_column("State", key="state", width=44)
        t.add_column("Path", key="path", width=40)
        self.repos: list[dict] = []
        self.remote: list[dict] = []
        self.me = ""
        self.update_sysinfo()
        self.action_rescan()

    def on_show(self) -> None:
        if hasattr(self, "repos"):
            self.update_sysinfo()

    def update_sysinfo(self) -> None:
        import platform
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
        for mount in disk_mounts():
            if Path(mount).exists():
                du = shutil.disk_usage(mount)
                m = meter10(du.used * 100 / du.total)
                m.append(f"  {du.used / 2**30:.0f} of {du.total / 2**30:.0f} GB · {du.free / 2**30:.0f} GB free",
                         style=THEME["muted"])
                row(f"Disk {mount}", m)
        self.query_one("#sysinfo", Static).update(info)

    # ── repos ──

    def action_rescan(self) -> None:
        self.query_one("#repos-panel").border_subtitle = " scanning… "
        self.scan()

    @work(thread=True, exclusive=True, group="repos")
    def scan(self) -> None:
        repos = scan_repos()
        for r in repos:
            r.update(repo_state(r["path"]))
        me = run(["gh", "api", "user", "-q", ".login"]).stdout.strip() if shutil.which("gh") else ""
        remote = []
        if me:
            try:
                remote = json.loads(run(["gh", "repo", "list", "--limit", "200", "--json",
                                         "nameWithOwner,url,isPrivate,description,pushedAt"]).stdout or "[]")
            except ValueError:
                remote = []
        self.app.call_from_thread(self.show_repos, repos, remote, me)

    def show_repos(self, repos: list[dict], remote: list[dict], me: str) -> None:
        self.repos, self.remote, self.me = repos, remote, me
        t = self.query_one("#repos", Table)
        row = t.cursor_row or 0
        t.clear()
        ok, warn, muted = THEME["status_ok"], THEME["status_warn"], THEME["muted"]
        home = str(Path.home())
        mine = sorted((r for r in repos if r["slug"].split("/")[0].lower() == me.lower()),
                      key=lambda r: r["slug"].lower())
        others = sorted((r for r in repos if r not in mine), key=lambda r: r["slug"].lower())
        cloned = {r["slug"].lower() for r in repos}
        missing = sorted((g for g in remote if g["nameWithOwner"].lower() not in cloned),
                         key=lambda g: g["nameWithOwner"].lower())

        def header(label: str) -> None:
            t.add_row(Text(label, style=f"bold {THEME['primary']}"), "", "", key=f"hdr:{label}")

        def local(r: dict) -> None:
            st = Text()
            if r["changes"]:
                st.append(f"{r['changes']} uncommitted", style=warn)
            if r["ahead"]:
                st.append(("" if not st else " · ") + f"{r['ahead']} to push", style=warn)
            if r["behind"]:
                st.append(("" if not st else " · ") + f"{r['behind']} to pull", style=THEME["status_error"])
            if not st:
                st.append("✓ clean", style=ok)
            st.append(f"  ({r['branch']})", style=muted)
            t.add_row(Text(f"  {r['slug'].split('/', 1)[1] if r in mine else r['slug']}"), st,
                      Text(str(r["path"]).replace(home, "~"), style=muted), key=f"local:{r['path']}")

        if mine:
            header(f"Mine · {me}")
            for r in mine:
                local(r)
        if missing:
            header("On GitHub, not cloned")
            for g in missing:
                t.add_row(Text(f"  {g['nameWithOwner'].split('/', 1)[1]}", style=muted),
                          Text(("private · " if g.get("isPrivate") else "") + "not cloned · enter opens it",
                               style=muted),
                          Text((g.get("description") or "")[:40], style=muted), key=f"remote:{g['url']}")
        if others:
            header("Third-party clones")
            for r in others:
                local(r)
        t.add_row(Text("󰓙  Run dotfiles doctor", style=f"bold {THEME['primary']}"),
                  Text("links, packages, services, configs and repo checks", style=muted), "", key="doctor")
        t.move_cursor(row=min(max(row, 1), t.row_count - 1))
        self.query_one("#repos-panel").border_subtitle = (
            f" {len(mine)} mine · {len(missing)} not cloned · {len(others)} third-party · "
            f"ahead/behind as of the last fetch ")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Los encabezados de grupo no se seleccionan
        if event.data_table.id == "repos" and str(event.row_key.value).startswith("hdr:"):
            t = event.data_table
            nxt = event.cursor_row + (1 if event.cursor_row >= getattr(self, "_last_row", 0) else -1)
            if 0 <= nxt < t.row_count:
                t.move_cursor(row=nxt)
            elif t.row_count > 1:
                t.move_cursor(row=1)
        self._last_row = event.cursor_row

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "details / open"), ("f", "fetch all"), ("r", "rescan"), ("q", "quit")]

    def action_fetch(self) -> None:
        if not self.repos:
            return
        self.query_one("#repos-panel").border_subtitle = f" fetching {len(self.repos)} repos… "
        self.fetch_all()

    @work(thread=True, exclusive=True, group="repos")
    def fetch_all(self) -> None:
        for r in self.repos:
            subprocess.run(["git", "-C", str(r["path"]), "fetch", "--quiet", "--all"],
                           capture_output=True, timeout=60)
        self.app.call_from_thread(self.app.notify_ok, "Fetched all repositories")
        self.app.call_from_thread(self.action_rescan)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "repos":
            return
        key = str(event.row_key.value)
        if key == "doctor":
            with self.app.suspend():
                os.system("clear")
                subprocess.run(["bash", str(DOTFILES / "scripts" / "dotfiles-doctor.sh")])
                input("\nPress enter to go back to Settings...")
            self.update_sysinfo()
        elif key.startswith("remote:"):
            detach(["xdg-open", key[7:].removesuffix(".git")])
            self.app.notify_ok("Opened in the browser")
        elif key.startswith("local:"):
            path = key[6:]
            r = run(["git", "-C", path, "status", "--short", "--branch"])
            log = run(["git", "-C", path, "log", "--oneline", "-10"])
            self.app.push_screen(TextModal(f"{Path(path).name} · git status",
                                           f"{path}\n\n{r.stdout}\nRecent commits:\n{log.stdout}", end=False))


# ── Update ────────────────────────────────────────────────

UPDATE_ACTIONS = [
    ("check", "󰍉  Check", "List pending updates (pacman + AUR)"),
    ("all", "󰚰  Full update", "Snapshot, then update pacman and AUR"),
    ("snapshot", "󰄄  Snapshot", "Create a system snapshot"),
    ("rollback", "󰑗  Rollback", "List snapshots to restore one"),
    ("pacman", "󰣇  Pacman", "Update official repositories"),
    ("aur", "󰏗  AUR (yay)", "Update AUR packages"),
    ("clean", "󰃢  Clean", "Clean the package cache"),
    ("orphans", "󰆴  Orphans", "Remove orphan packages"),
]


class UpdateView(DView):
    """scripts/dotfiles-update.sh en la misma ventana (necesita terminal para sudo)."""

    FOCUS = "#update"

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="update", show_header=False), title="󰚰  Update", id="update-panel")

    def on_mount(self) -> None:
        t = self.query_one("#update", Table)
        t.add_column("", key="name", width=20)
        t.add_column("", key="desc", width=60)
        for mode, name, desc in UPDATE_ACTIONS:
            t.add_row(name, Text(desc, style=THEME["muted"]), key=mode)
        self.query_one("#update-panel").border_subtitle = " runs here; sudo may ask for your fingerprint "

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "run"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "update":
            return
        with self.app.suspend():
            os.system("clear")
            subprocess.run([str(UPDATE_SH), event.row_key.value])
            input("\nPress enter to go back to Settings...")
        self.app.refresh(layout=True)


# ── App ───────────────────────────────────────────────────

# Menú agrupado por categoría: (categoría, [(id, ícono, nombre)])
CATEGORIES = [
    ("Connectivity", [("wifi", "󰖩", "Wi-Fi"), ("bluetooth", "󰂯", "Bluetooth"), ("vpn", "󰦝", "VPN"),
                      ("phone", "󰏲", "Phone"), ("nettools", "󰛳", "Network tools")]),
    ("System", [("services", "\uf013", "Services"), ("startup", "󰒲", "Startup apps"), ("logs", "󰌱", "Logs"),
                ("snapshots", "󰄄", "Snapshots"), ("system", "󰌢", "System"),
                ("update", "󰚰", "Update")]),
    ("Tools", [("notifications", "\uf0f3", "Notifications"), ("clipboard", "󰅌", "Clipboard"),
               ("screenshots", "󰄀", "Screenshots"), ("colorpicker", "󰴱", "Color picker"),
               ("agents", "󰚩", "AI Agents")]),
    ("Hardware", [("displays", "󰍹", "Displays"), ("audio", "󰕾", "Audio"), ("input", "󰌌", "Input"),
                  ("power", "󰂄", "Power"), ("battery", "󰁹", "Battery"), ("storage", "󰋊", "Storage")]),
    ("Desktop", [("modes", "󰕮", "Modes"), ("workspaces", "\uf009", "Workspaces"), ("webapps", "󰖟", "Webapps"),
                 ("defaultapps", "󰀻", "Default apps"), ("shortcuts", "\uf11c", "Shortcuts")]),
    ("Look & feel", [("themes", "󰏘", "Themes"), ("themeeditor", "󰏘", "Theme editor"),
                     ("appearance", "󰉼", "Appearance"), ("fonts", "󰛖", "Fonts & cursor"),
                     ("backgrounds", "\uf03e", "Backgrounds")]),
]
SECTIONS = [sec for _cat, secs in CATEGORIES for sec in secs]


class SettingsApp(DApp):
    TITLE = "Settings"
    CSS = DApp.CSS + css("""
    #left { width: 30; }
    #profile { height: auto; align: center top; }
    #logo { height: 9; width: 100%%; align: center top; }
    #logo Image { width: 18; height: 9; }
    #name { width: 100%%; text-align: center; text-style: bold; color: %(primary)s; }
    #menu-panel { height: 1fr; }
    #sections { width: 1fr; }
    """)

    BINDINGS = [
        Binding("q", "quit", "quit", show=False),
        Binding("escape", "leave", "back", show=False),
        Binding("tab", "toggle_focus", show=False),
        Binding("j", "menu_move(1)", show=False),
        Binding("k", "menu_move(-1)", show=False),
    ]

    def __init__(self, section: str = "") -> None:
        super().__init__()
        # Sin sección pedida (o una que no existe): la primera del menú
        self.start = section if section in {s[0] for s in SECTIONS} else SECTIONS[0][0]

    def compose(self) -> ComposeResult:
        vpn_view = load_view("vpn_tui", "view_class")()
        views = {
            "themes": ThemesView, "modes": load_view("modes_tui", "ModesView"),
            "workspaces": WorkspacesView, "webapps": load_view("webapps_tui", "WebappsView"),
            "backgrounds": BackgroundsView, "notifications": NotificationsView,
            "shortcuts": load_view("shortcuts_tui", "ShortcutsView"), "vpn": vpn_view,
            "displays": DisplaysView,
            "update": UpdateView, "appearance": AppearanceView, "audio": AudioView, "wifi": WifiView,
            "bluetooth": BluetoothView, "power": PowerView, "clipboard": load_view("clipboard_tui", "ClipboardView"),
            "services": ServicesView, "system": SystemView,
            # En Settings, AI Agents suma el panel Providers (mostrar/ocultar cada uno)
            "phone": PhoneView, "nettools": NetToolsView, "startup": StartupView, "logs": LogsView,
            "snapshots": SnapshotsView, "screenshots": ScreenshotsView, "colorpicker": ColorPickerView,
            "input": InputView, "battery": BatteryView, "storage": StorageView, "defaultapps": DefaultAppsView,
            "themeeditor": ThemeEditorView, "fonts": FontsView,
            "agents": functools.partial(load_view("agents_tui", "AgentsView"), manage=True),
        }
        with Horizontal():
            with Vertical(id="left"):
                yield Panel(ImagePreview(LOGO, id="logo"), Static(display_name(), id="name"), id="profile")
                yield Panel(Table(id="menu", show_header=False), title="󰒓  Settings", id="menu-panel")
            with ContentSwitcher(initial=self.start, id="sections"):
                for sid, _icon, _name in SECTIONS:
                    yield views[sid](id=sid)
        yield KeyHints(id="hints")

    def on_mount(self) -> None:
        menu = self.query_one("#menu", Table)
        menu.add_column("", key="name", width=24)
        self.menu_keys: list[str] = []
        for cat, secs in CATEGORIES:
            menu.add_row(Text(cat.upper(), style=f"bold {THEME['muted']}"), key=f"hdr:{cat}")
            self.menu_keys.append(f"hdr:{cat}")
            for sid, icon, name in secs:
                menu.add_row(f" {icon}  {name}", key=sid)
                self.menu_keys.append(sid)
        self._menu_row = self.menu_keys.index(self.start)
        menu.move_cursor(row=self._menu_row)
        if self.start != SECTIONS[0][0]:
            # Volviendo de aplicar un tema: directo a la sección
            self.call_after_refresh(self.enter_section)
        else:
            menu.focus()
        self.call_after_refresh(self.update_menu_hints)

    # ── menú ↔ sección ──

    def section(self) -> DView:
        sw = self.query_one(ContentSwitcher)
        return sw.get_child_by_id(sw.current)

    def in_menu(self) -> bool:
        return self.focused is self.query_one("#menu", Table)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "menu" or not event.row_key.value:
            return
        key, row = str(event.row_key.value), event.cursor_row
        if key.startswith(("hdr:", "gap:")):
            # Encabezados y separadores no se seleccionan: seguir en la misma dirección
            step = 1 if row >= self._menu_row else -1
            nxt = row + step
            while 0 <= nxt < len(self.menu_keys) and self.menu_keys[nxt].startswith(("hdr:", "gap:")):
                nxt += step
            if not 0 <= nxt < len(self.menu_keys):
                nxt = self._menu_row
            event.data_table.move_cursor(row=nxt)
            return
        self._menu_row = row
        self.query_one(ContentSwitcher).current = key

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "menu":
            event.stop()
            if not str(event.row_key.value).startswith(("hdr:", "gap:")):
                self.enter_section()

    def enter_section(self) -> None:
        self.section().focus_first()

    def action_menu_move(self, step: int) -> None:
        # j/k en el menú (las secciones tienen sus propios j/k)
        if self.in_menu():
            menu = self.query_one("#menu", Table)
            menu.action_cursor_down() if step > 0 else menu.action_cursor_up()

    def action_toggle_focus(self) -> None:
        if self.in_menu():
            self.enter_section()
        else:
            self.query_one("#menu", Table).focus()

    def action_leave(self) -> None:
        if self.in_menu():
            self.exit()
        else:
            self.query_one("#menu", Table).focus()

    def on_descendant_focus(self, _event) -> None:
        if self.in_menu():
            self.update_menu_hints()

    def update_menu_hints(self) -> None:
        if self.in_menu():
            super().set_hints([("enter", "open"), ("tab", "section"), ("j/k", "move"), ("q", "quit")])

    def set_hints(self, hints: list[tuple[str, str]]) -> None:
        # Dentro de una sección: sus atajos + cómo volver al menú
        if not self.in_menu() and not any(k == "esc" for k, _ in hints):
            hints = [h for h in hints if h[0] != "q"] + [("esc", "menu"), ("q", "quit")]
        super().set_hints(hints)

    def restart(self, section: str) -> None:
        """Reabre Settings en la misma ventana (para releer el tema)."""
        self.exit(("restart", section))


if __name__ == "__main__":
    start = sys.argv[sys.argv.index("--section") + 1] if "--section" in sys.argv[:-1] else ""
    result = SettingsApp(start).run()
    if isinstance(result, tuple) and result[0] == "restart":
        os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), "--section", result[1]])
    elif isinstance(result, tuple) and result[0] == "exec":
        # AI Agents → c/o: el agente reemplaza a Settings en la misma ventana
        os.execvp(result[1], [result[1]])
