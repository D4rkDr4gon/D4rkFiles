#!/usr/bin/env python3
"""
modes_tui.py — gestor de modos de escritorio (Settings → MODES → Gestionar).

Un modo es un conjunto de apps, cada una en un workspace; lo aplica
scripts/mode-switch.sh. Arriba la lista de modos, abajo las apps del modo
seleccionado (tab cambia de panel). Para agregar una app se elige una
ventana abierta (toma la clase exacta y el comando de su .desktop) o se
carga a mano. Los modos viven en ~/.config/dotfiles/modes.conf (fuera del
repo; se crea desde modes.conf.example al guardar el primer cambio).

Estilo común de las TUIs: tools/dtui.py. Requiere Hyprland.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, PickModal, Table, ViewApp, css  # noqa: E402

from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.widgets import DataTable  # noqa: E402

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de tools/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
CONF = Path(os.environ.get("MODES_CONF") or CONFIG_HOME / "dotfiles" / "modes.conf")
EXAMPLE = DOTFILES / "modes.conf.example"
MODE_SWITCH = DOTFILES / "scripts" / "mode-switch.sh"
STATE = STATE_HOME / "dotfiles" / "desktop-mode"   # último modo aplicado (lo escribe mode-switch.sh)
MANAGER_CLASS = "modes"                             # clase de la kitty flotante de esta TUI
DEFAULT_ICON = "󰕮"
# Terminales: todas comparten clase, así que se identifican por título
TERMINALS = re.compile(r"^(kitty|foot|Alacritty|org\.wezfurlong\.wezterm|com\.mitchellh\.ghostty)$")


# ── modes.conf: modo|ícono|workspace|match|comando|nombre ──
# Una línea sin workspace es la cabecera del modo (existe aunque no tenga apps).

@dataclass
class App_:
    line: int          # índice en el archivo (para editar/borrar en su lugar)
    mode: str
    ws: str
    match: str
    cmd: str
    name: str


class Conf:
    def __init__(self) -> None:
        try:
            # Sin modes.conf propio se parte del ejemplo (y se crea al guardar)
            self.lines = (CONF if CONF.exists() else EXAMPLE).read_text().splitlines()
        except OSError:
            self.lines = []

    def save(self) -> None:
        CONF.parent.mkdir(parents=True, exist_ok=True)
        CONF.write_text("\n".join(self.lines) + "\n")

    def rows(self):
        for i, l in enumerate(self.lines):
            if l.strip() and not l.lstrip().startswith("#"):
                yield i, (l.split("|") + [""] * 6)[:6]

    def modes(self) -> list[str]:
        out = []
        for _, f in self.rows():
            if f[0] not in out:
                out.append(f[0])
        return out

    def icon(self, mode: str) -> str:
        return next((f[1] for _, f in self.rows() if f[0] == mode and f[1]), DEFAULT_ICON)

    def apps(self, mode: str) -> list[App_]:
        apps = [App_(i, f[0], f[2], f[3], f[4], f[5]) for i, f in self.rows() if f[0] == mode and f[2]]
        return sorted(apps, key=lambda a: (int(a.ws) if a.ws.isdigit() else 99, a.line))

    def last_line(self, mode: str) -> int:
        return max((i for i, f in self.rows() if f[0] == mode), default=len(self.lines) - 1)

    def add_mode(self, name: str, icon: str) -> None:
        if self.lines and self.lines[-1].strip():
            self.lines.append("")
        self.lines.append(f"{name}|{icon}||||")

    def rename(self, old: str, new: str, icon: str) -> None:
        first = True
        for i, f in list(self.rows()):
            if f[0] == old:
                f[0], f[1] = new, (icon if first else "")
                first = False
                self.lines[i] = "|".join(f)

    def delete_mode(self, mode: str) -> None:
        drop = {i for i, f in self.rows() if f[0] == mode}
        self.lines = [l for i, l in enumerate(self.lines) if i not in drop]

    def add_app(self, mode: str, ws: str, match: str, cmd: str, name: str) -> None:
        # Junto a las demás líneas del modo, no al final del archivo
        self.lines.insert(self.last_line(mode) + 1, "|".join([mode, "", ws, match, cmd, name]))

    def set_app(self, line: int, ws: str, match: str, cmd: str, name: str) -> None:
        f = (self.lines[line].split("|") + [""] * 6)[:6]
        f[2:6] = [ws, match, cmd, name]
        self.lines[line] = "|".join(f)

    def remove_line(self, line: int) -> None:
        del self.lines[line]


def clean(s: str) -> str:
    return s.replace("|", "").strip()


def desktop_for_class(cls: str) -> Optional[tuple[str, str]]:
    """Exec y Name del .desktop de una clase (por StartupWMClass o nombre de
    archivo), sin los códigos %u/%F/... ni el flag que los precede."""
    cls = cls.lower()
    dirs = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications",
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"), Path("/usr/share/applications")]
    for d in dirs:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            wm = re.search(r"^StartupWMClass=(.*)$", text, re.M)
            if (wm and wm.group(1).strip().lower() == cls) or f.stem.lower() == cls:
                main = text.split("\n[", 1)[0]          # solo [Desktop Entry]
                ex = re.search(r"^Exec=(.*)$", main, re.M)
                nm = re.search(r"^Name=(.*)$", main, re.M)
                cmd = re.sub(r" (--?[a-zA-Z-]+ )?(-- )?%[a-zA-Z]", "", ex.group(1)) if ex else ""
                return cmd, (nm.group(1) if nm else "")
    return None


def windows() -> list[dict]:
    try:
        out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=3).stdout
        return [w for w in json.loads(out) if w.get("class") and w["class"] != MANAGER_CLASS]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


class ModesView(DView):
    """Modos arriba, apps del modo abajo. Se usa sola (ModesApp) o en Settings."""

    FOCUS = "#modes"
    DEFAULT_CSS = css("""
    #modes-panel { height: auto; max-height: 45%%; }
    #modes { height: auto; max-height: 100%%; }
    #apps-panel { height: 1fr; }
    """)

    BINDINGS = [
        Binding("tab", "switch", "switch panel", show=False),
        Binding("shift+tab", "switch", show=False),
        Binding("n", "new_mode", "new mode"),
        Binding("r", "rename", "rename"),
        Binding("a", "add_app", "add app"),
        Binding("e", "edit", "edit"),
        Binding("d", "delete", "delete"),
        Binding("j", "down", show=False),
        Binding("k", "up", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="modes"), title="󰕮  Modes", id="modes-panel")
        yield Panel(Table(id="apps"), title="Apps", id="apps-panel")

    def on_mount(self) -> None:
        m = self.query_one("#modes", DataTable)
        m.add_column("Mode", key="name", width=24)
        m.add_column("Apps", key="count", width=6)
        m.add_column("Workspaces", key="sum", width=60)
        a = self.query_one("#apps", DataTable)
        a.add_column("WS", key="ws", width=4)
        a.add_column("App", key="name", width=20)
        a.add_column("Match", key="match", width=34)
        a.add_column("Command", key="cmd", width=40)
        self.reload()

    # ── datos ──

    def reload(self, select_mode: Optional[str] = None, select_line: Optional[int] = None) -> None:
        self.conf = Conf()
        m = self.query_one("#modes", DataTable)
        cur = select_mode or self.current_mode()
        active = STATE.read_text().strip() if STATE.exists() else ""
        m.clear()
        self.mode_names = self.conf.modes()
        for mode in self.mode_names:
            apps = self.conf.apps(mode)
            name = Text(f"{self.conf.icon(mode)}  {mode}")
            if mode == active:
                name.append("  active", style=THEME["status_ok"])
            summary = "  ".join(f"{a.ws}:{a.name or Path(a.cmd.split()[0]).name}" for a in apps) if apps else ""
            m.add_row(name, str(len(apps)), Text(summary or "no apps", style=THEME["muted"]), key=mode)
        if cur in self.mode_names:
            m.move_cursor(row=self.mode_names.index(cur))
        self.query_one("#modes-panel").border_subtitle = "" if self.mode_names else " no modes: press n to create one "
        self.fill_apps(select_line)

    def current_mode(self) -> Optional[str]:
        m = self.query_one("#modes", DataTable)
        names = getattr(self, "mode_names", [])
        if not names or m.cursor_row is None or m.cursor_row >= len(names):
            return None
        return names[m.cursor_row]

    def fill_apps(self, select_line: Optional[int] = None) -> None:
        a = self.query_one("#apps", DataTable)
        a.clear()
        mode = self.current_mode()
        self.app_rows = self.conf.apps(mode) if mode else []
        for app in self.app_rows:
            a.add_row(app.ws, app.name, Text(app.match, style=THEME["muted"]),
                      Text(app.cmd, style=THEME["muted"]), key=str(app.line))
        panel = self.query_one("#apps-panel")
        panel.border_title = f" {mode} apps " if mode else " Apps "
        panel.border_subtitle = "" if self.app_rows else " no apps: press a to add one "
        if select_line is not None:
            for i, app in enumerate(self.app_rows):
                if app.line == select_line:
                    a.move_cursor(row=i)
        self.update_hints()

    def current_app(self) -> Optional[App_]:
        a = self.query_one("#apps", DataTable)
        if not self.app_rows or a.cursor_row is None or a.cursor_row >= len(self.app_rows):
            return None
        return self.app_rows[a.cursor_row]

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "modes":
            self.fill_apps()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "modes":
            self.apply()
        elif event.data_table.id == "apps":
            self.action_edit()

    def in_apps(self) -> bool:
        return self.app.focused is self.query_one("#apps", DataTable)

    def hints(self) -> list[tuple[str, str]]:
        if self.in_apps():
            return [("enter", "edit"), ("a", "add app"), ("d", "remove"), ("tab", "modes"), ("q", "quit")]
        return [("enter", "apply"), ("n", "new"), ("r", "rename"), ("a", "add app"),
                ("d", "delete"), ("tab", "apps"), ("q", "quit")]

    # ── acciones ──

    def action_switch(self) -> None:
        target = "#modes" if self.in_apps() else "#apps"
        self.query_one(target, DataTable).focus()

    def action_down(self) -> None:
        if isinstance(self.app.focused, DataTable):
            self.app.focused.action_cursor_down()

    def action_up(self) -> None:
        if isinstance(self.app.focused, DataTable):
            self.app.focused.action_cursor_up()

    def apply(self) -> None:
        mode = self.current_mode()
        if not mode:
            return
        subprocess.Popen(["bash", str(MODE_SWITCH), mode], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.app.exit()

    def mode_validator(self, orig: str = ""):
        def check(v: dict) -> Optional[str]:
            name = clean(v["name"])
            if not name:
                return "The name is missing"
            if name != orig and name in self.conf.modes():
                return f"There is already a mode called {name}"
            return None
        return check

    def action_new_mode(self) -> None:
        def done(v: Optional[dict]) -> None:
            if not v:
                return
            name = clean(v["name"])
            self.conf.add_mode(name, clean(v["icon"]) or DEFAULT_ICON)
            self.conf.save()
            self.reload(select_mode=name)
            self.app.notify_ok(f"Mode {name} created: press a to add apps")

        self.app.push_screen(FormModal("New mode", [Field("name", "Name"),
                                                    Field("icon", "Icon (Nerd Font)", DEFAULT_ICON)],
                                   validate=self.mode_validator()), done)

    def action_rename(self) -> None:
        mode = self.current_mode()
        if not mode or self.in_apps():
            return

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            name = clean(v["name"])
            self.conf.rename(mode, name, clean(v["icon"]))
            self.conf.save()
            if STATE.exists() and STATE.read_text().strip() == mode:
                STATE.write_text(name + "\n")
            self.reload(select_mode=name)

        self.app.push_screen(FormModal(f"Rename {mode}", [Field("name", "Name", mode),
                                                          Field("icon", "Icon (Nerd Font)", self.conf.icon(mode))],
                                   validate=self.mode_validator(mode)), done)

    def app_fields(self, ws: str = "", match: str = "", cmd: str = "", name: str = "") -> list[Field]:
        return [Field("name", "Name", name), Field("cmd", "Command", cmd),
                Field("match", "Match (class:<regex> or title:<regex>, see hyprctl clients)", match),
                Field("ws", "Workspace (1-9)", ws)]

    @staticmethod
    def app_check(v: dict) -> Optional[str]:
        if not clean(v["name"]) or not clean(v["cmd"]):
            return "The name or the command is missing"
        if not re.match(r"^(class|title):.+", v["match"]):
            return "The match starts with class: or title:"
        if not re.fullmatch(r"[1-9]", v["ws"]):
            return "The workspace is a number from 1 to 9"
        return None

    def action_add_app(self) -> None:
        mode = self.current_mode()
        if not mode:
            return
        wins = windows()
        rows = [("-", [Text("✎", style=THEME["primary"]), Text("Enter manually", style="bold"), "", ""])]
        for w in wins:
            rows.append((w["address"], [f"WS {w['workspace']['id']}", w["class"], w["title"][:50], ""]))
        by_addr = {w["address"]: w for w in wins}

        def picked(key: Optional[str]) -> None:
            if key is None:
                return
            if key == "-":
                return self.app_form(mode, self.app_fields())
            w = by_addr[key]
            cls, title = w["class"], w["title"]
            if TERMINALS.match(cls):
                match, name = f"title:^{re.escape(title)}$", title
            else:
                match, name = f"class:^{re.escape(cls)}$", cls
            info = None if TERMINALS.match(cls) else desktop_for_class(cls)
            if info:
                cmd, nm = info
                name = nm or name
            else:
                # Sin .desktop (o terminal): la línea de comando del proceso
                try:
                    cmd = Path(f"/proc/{w['pid']}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
                except OSError:
                    cmd = ""
            self.app_form(mode, self.app_fields(match=match.replace("|", "."), cmd=cmd, name=name))

        self.app.push_screen(PickModal(f"Add app to {mode}", ["", "Class", "Title", ""], rows,
                                       hint="pick an open window · enter select · esc cancel"), picked)

    def app_form(self, mode: str, fields: list[Field], line: Optional[int] = None) -> None:
        def done(v: Optional[dict]) -> None:
            if not v:
                return
            vals = (v["ws"], v["match"].replace("|", "."), clean(v["cmd"]), clean(v["name"]))
            if line is None:
                self.conf.add_app(mode, *vals)
                sel = self.conf.last_line(mode)
            else:
                self.conf.set_app(line, *vals)
                sel = line
            self.conf.save()
            self.reload(select_mode=mode, select_line=sel)
            self.app.notify_ok(f"{vals[3]} → workspace {vals[0]}")

        title = f"Add app to {mode}" if line is None else f"Edit {fields[0].value}"
        self.app.push_screen(FormModal(title, fields, validate=self.app_check), done)

    def action_edit(self) -> None:
        if not self.in_apps():
            return self.action_rename()
        app = self.current_app()
        if app:
            self.app_form(app.mode, self.app_fields(app.ws, app.match, app.cmd, app.name), line=app.line)

    def action_delete(self) -> None:
        mode = self.current_mode()
        if not mode:
            return
        if self.in_apps():
            app = self.current_app()
            if not app:
                return

            def done_app(yes: bool) -> None:
                if yes:
                    self.conf.remove_line(app.line)
                    self.conf.save()
                    self.reload(select_mode=mode)

            return self.app.push_screen(ConfirmModal("Remove app", f"Remove {app.name} from mode {mode}?"), done_app)

        def done(yes: bool) -> None:
            if yes:
                self.conf.delete_mode(mode)
                self.conf.save()
                self.reload()
                self.app.notify_ok(f"{mode} deleted")

        self.app.push_screen(ConfirmModal("Delete mode", f"Delete mode {mode}? Open apps are not closed."), done)


def ModesApp() -> ViewApp:
    return ViewApp(ModesView, title="Modes")


if __name__ == "__main__":
    if not shutil.which("hyprctl"):
        sys.exit("Modes require Hyprland")
    ModesApp().run()
