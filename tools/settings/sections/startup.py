"""Startup apps — lo que arranca con la sesión de Hyprland (`exec-once`).

Dos grupos:
- Del repo (config/hypr/hyprland.conf): solo lectura; x las corre ahora.
- Propias (~/.config/dotfiles/hypr/autostart.conf, fuera del repo): a agrega,
  enter prende/apaga (comenta la línea con el marcador `#off#`), d borra.

Los cambios aplican en el próximo inicio de sesión: apagar no mata lo que ya
está corriendo.
"""

from __future__ import annotations

import re
from typing import Optional

from common import AUTOSTART_CONF, HYPR_CONF, atomic_write, run, tilde
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, Table, css
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

LINE = re.compile(r"^(?P<off>#off#\s*)?exec-once\s*=\s*(?P<cmd>.*?)(?:\s+#\s*(?P<note>.*))?$")
HEADER = ["# autostart.conf — apps de inicio propias (Settings → Startup apps).",
          "# Se incluye desde config/hypr/hyprland.conf. `#off#` = apagada desde Settings.", ""]


def entries(path, user: bool) -> list[dict]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for i, line in enumerate(lines):
        m = LINE.match(line.strip())
        if m and (user or not m.group("off")):
            out.append({"line": i, "user": user, "on": not m.group("off"), "cmd": m.group("cmd").strip(),
                        "note": (m.group("note") or "").strip()})
    return out


def user_lines() -> list[str]:
    try:
        return AUTOSTART_CONF.read_text().splitlines()
    except OSError:
        return list(HEADER)


class StartupView(DView):
    FOCUS = "#startup"
    BINDINGS = [Binding("x", "run_now", "run now"), Binding("a", "add", "add"), Binding("d", "delete", "delete")]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="startup"), title="󰒲  Startup apps", id="startup-panel")

    def on_mount(self) -> None:
        t = self.query_one("#startup", Table)
        t.add_column("", key="state", width=4)
        t.add_column("Command", key="cmd", width=62)
        t.add_column("Note", key="note", width=50)
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#startup", Table)
        prev = t.selected_key()
        t.clear()
        mine, repo = entries(AUTOSTART_CONF, True), entries(HYPR_CONF, False)
        self.items = {f"user:{e['line']}": e for e in mine} | {f"repo:{e['line']}": e for e in repo}
        primary, muted = THEME["primary"], THEME["muted"]
        t.add_row("", Text("YOURS", style=f"bold {primary}"), Text("~/.config/dotfiles/hypr/autostart.conf",
                                                                   style=muted), key="hdr:user")
        for e in mine:
            st = Text("●", style=THEME["status_ok"]) if e["on"] else Text("○", style=muted)
            t.add_row(st, Text(tilde(e["cmd"].replace("$HOME", "~")), style="" if e["on"] else muted),
                      Text(e["note"], style=muted), key=f"user:{e['line']}")
        t.add_row("", Text("+  Add a startup app…", style=primary), "", key="add")
        t.add_row("", Text("FROM THE REPO", style=f"bold {primary}"),
                  Text("read only · config/hypr/hyprland.conf", style=muted), key="hdr:repo")
        for e in repo:
            t.add_row(Text("●", style=muted), Text(e["cmd"].replace("$HOME", "~"), style=muted),
                      Text(e["note"], style=muted), key=f"repo:{e['line']}")
        rows = [str(r.key.value) for r in t.ordered_rows]
        t.first_selectable(rows.index(prev) if prev in rows else 0)
        on = sum(e["on"] for e in mine)
        self.query_one("#startup-panel").border_subtitle = (f" {on} of {len(mine)} of yours on · "
                                                            "changes apply at next login ")

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "on/off"), ("a", "add"), ("d", "delete"), ("x", "run now"), ("q", "quit")]

    def current(self) -> Optional[dict]:
        return self.items.get(self.query_one("#startup", Table).selected_key() or "")

    def set_line(self, line: int, on: Optional[bool]) -> None:
        """Prende/apaga una línea de autostart.conf (on=None la borra)."""
        lines = user_lines()
        body = re.sub(r"^#off#\s*", "", lines[line].strip())
        if on is None:
            del lines[line]
        else:
            lines[line] = body if on else f"#off# {body}"
        atomic_write(AUTOSTART_CONF, "\n".join(lines) + "\n")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "startup":
            return
        if event.row_key.value == "add":
            return self.action_add()
        e = self.current()
        if not e:
            return
        if not e["user"]:
            return self.app.notify_err("Repo entries are read only: edit config/hypr/hyprland.conf")
        self.set_line(e["line"], not e["on"])
        self.app.notify_ok(f"{'Off' if e['on'] else 'On'} at next login: {e['cmd'].split()[0]}")
        self.reload()

    def action_add(self) -> None:
        def done(v: Optional[dict]) -> None:
            if not v:
                return
            lines = user_lines()
            note = f"   # {v['note']}" if v["note"] else ""
            lines.append(f"exec-once = {v['cmd']}{note}")
            atomic_write(AUTOSTART_CONF, "\n".join(lines) + "\n")
            self.app.notify_ok(f"Added: {v['cmd'].split()[0]} (starts at next login)")
            self.reload()

        self.app.push_screen(FormModal("Add a startup app", [Field("cmd", "Command", placeholder="e.g. nm-applet"),
                                                             Field("note", "Note (optional)")],
                                       hint="Runs once when Hyprland starts. x runs it now.",
                                       validate=lambda v: None if v["cmd"] else "The command is missing"), done)

    def action_delete(self) -> None:
        e = self.current()
        if not e or not e["user"]:
            return self.app.notify_err("Select one of your startup apps")

        def done(yes: bool) -> None:
            if yes:
                self.set_line(e["line"], None)
                self.app.notify_ok("Removed")
                self.reload()

        self.app.push_screen(ConfirmModal("Remove startup app", f"Remove\n{e['cmd']}\nfrom autostart.conf?"), done)

    def action_run_now(self) -> None:
        if e := self.current():
            run(["hyprctl", "dispatch", "exec", e["cmd"].replace("$dotfiles", str(HYPR_CONF.parents[2]))])
            self.app.notify_ok(f"Started: {e['cmd'].split()[0]}")
