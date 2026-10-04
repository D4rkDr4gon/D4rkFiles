"""Workspaces — cuántos hay habilitados y a cuál ir.

config/hypr/hyprland.conf (del repo, solo lectura) trae Super+1..9 (traer y
enfocar) y Super+Shift+1..9 (mover la ventana). La cantidad elegida (1–10) se
guarda en ~/.config/dotfiles/hypr/workspaces.conf, que hyprland.conf incluye
al final (`source = ~/.config/dotfiles/hypr/*.conf`): `unbind` de los atajos
que sobran, el bind del 10 (tecla 0) si hace falta, y la línea `# count: N`
que leen el indicador de waybar (config/hypr/scripts/hypr-workspaces.py),
Ctrl+Tab y la rueda sobre waybar (config/hypr/scripts/workspace-cycle.sh, dan
la vuelta en 1..N) y el switcher de rofi. Sin el archivo rigen los 9 de siempre.

Al bajar la cantidad, si quedan ventanas en workspaces que se deshabilitan, se
ofrece moverlas al último habilitado. En Qtile los grupos siguen fijos (1–6).
"""

from __future__ import annotations

import json
import re
from typing import Optional

from common import HYPR_USER_DIR, HYPRLAND, atomic_write, run
from dtui import THEME, Card, ConfirmModal, DView, Panel, Table, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

WS_CONF = HYPR_USER_DIR / "workspaces.conf"
MIN_WS, MAX_WS, DEFAULT_WS = 1, 10, 9
QTILE_WS = 6


def ws_count() -> int:
    try:
        m = re.search(r"^# count: *(\d+)", WS_CONF.read_text(), re.M)
        return max(MIN_WS, min(MAX_WS, int(m.group(1)))) if m else DEFAULT_WS
    except OSError:
        return DEFAULT_WS


def write_ws_conf(n: int) -> None:
    """Genera ~/.config/dotfiles/hypr/workspaces.conf para n workspaces: los
    atajos 1..9 vienen de hyprland.conf; acá se sacan los que sobran (unbind) y
    se agrega el 10 (tecla 0)."""
    lines = ["# workspaces.conf — generado por Settings → Workspaces (tools/settings/sections/workspaces.py).",
             "# No editar a mano: se reescribe al cambiar la cantidad. Lo incluye hyprland.conf",
             "# (source = ~/.config/dotfiles/hypr/*.conf). La línea count la leen el indicador de",
             "# waybar, workspace-cycle.sh y el switcher de rofi.",
             f"# count: {n}", ""]
    for i in range(n + 1, DEFAULT_WS + 1):
        lines += [f"unbind = $mainMod, {i}", f"unbind = $mainMod SHIFT, {i}"]
    if n >= 10:
        lines += ["bind = $mainMod, 0, exec, $SCRIPTS_DIR/move-and-focus-workspace.sh 10",
                  "bind = $mainMod SHIFT, 0, exec, $SCRIPTS_DIR/move-window-to-workspace.sh 10"]
    atomic_write(WS_CONF, "\n".join(lines) + "\n")


def hypr_state() -> tuple[dict[int, dict], Optional[int], list[dict]]:
    """({id: workspace}, id activo, clientes) de hyprctl."""
    try:
        info = {w["id"]: w for w in json.loads(run(["hyprctl", "workspaces", "-j"]).stdout or "[]")}
        active = json.loads(run(["hyprctl", "activeworkspace", "-j"]).stdout or "{}").get("id")
        clients = json.loads(run(["hyprctl", "clients", "-j"]).stdout or "[]")
    except ValueError:
        return {}, None, []
    return info, active, clients


def goto_workspace(ws: int) -> None:
    if HYPRLAND:
        run(["hyprctl", "dispatch", "workspace", str(ws)])
    else:
        run(["qtile", "cmd-obj", "-o", "group", str(ws), "-f", "toscreen"])


class WorkspacesView(DView):
    FOCUS = "#ws-count"
    DEFAULT_CSS = css("""
    #ws-count-panel { height: auto; }
    #ws-count { padding: 1 2; }
    #ws-panel { height: 1fr; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False),
        Binding("shift+tab", "cycle(-1)", show=False),
        Binding("left,minus", "change(-1)", "fewer workspaces", show=False),
        Binding("right,plus,equals_sign", "change(1)", "more workspaces", show=False),
        Binding("enter", "apply", "apply workspace count", show=False),
    ]
    FOCUSABLE = ["ws-count", "workspaces"]

    def compose(self) -> ComposeResult:
        yield Panel(Card(id="ws-count"), title="  Workspaces", id="ws-count-panel")
        yield Panel(Table(id="workspaces"), title="Windows", id="ws-panel")

    def on_mount(self) -> None:
        t = self.query_one("#workspaces", Table)
        t.add_column("Workspace", key="ws", width=16)
        t.add_column("Keys", key="keys", width=12)
        t.add_column("Windows", key="n", width=9)
        t.add_column("Last window", key="extra", width=60)
        self.saved = self.draft = ws_count() if HYPRLAND else QTILE_WS
        self.info: dict[int, dict] = {}
        self.active: Optional[int] = None
        self.clients: list[dict] = []
        self.paint()
        self.reload()

    def on_show(self) -> None:
        if self.is_mounted:
            self.reload()

    @work(thread=True, exclusive=True, group="workspaces")
    def reload(self) -> None:
        state = hypr_state() if HYPRLAND else ({}, None, [])
        self.app.call_from_thread(self.show_state, *state)

    def show_state(self, info: dict, active: Optional[int], clients: list[dict]) -> None:
        self.info, self.active, self.clients = info, active, clients
        self.paint()

    # ── dibujo ──

    def paint(self) -> None:
        primary, muted, ok = THEME["primary"], THEME["muted"], THEME["status_ok"]
        t = Text()
        for i in range(1, MAX_WS + 1):
            on = i <= self.draft
            busy = self.info.get(i, {}).get("windows", 0) > 0
            style = (f"bold {THEME['background']} on {primary}" if i == self.active and on
                     else f"bold {THEME['foreground']} on {THEME['chip_wlan']}" if on and busy
                     else f"{THEME['foreground']} on {THEME['chip_battery']}" if on
                     else f"{muted}")
            t.append(f" {i % 10 if i == 10 else i} " if on else " · ", style=style)
            t.append(" ")
        t.append("\n\n")
        if not HYPRLAND:
            t.append(f"Qtile: {QTILE_WS} fixed groups (the count is configured for Hyprland)", style=muted)
        else:
            t.append(f"{self.draft} enabled", style="bold")
            t.append(f" · Super+1…{self.draft % 10 if self.draft == 10 else self.draft} go, "
                     f"Super+Shift+N move window, Ctrl+Tab cycles 1–{self.draft}", style=muted)
            if self.draft != self.saved:
                t.append(f"\nchanged from {self.saved} · enter to apply", style=f"bold {THEME['status_warn']}")
        self.query_one("#ws-count", Card).update(t)
        self.query_one("#ws-count-panel").border_subtitle = (" ←/→ how many · enter apply " if HYPRLAND else "")

        rows = []
        for i in range(1, self.draft + 1):
            w = self.info.get(i, {})
            label = Text(f"  Workspace {i}")
            if i == self.active:
                label.append("  ●", style=ok)
            key = i % 10
            rows.append((str(i), [label, Text(f"Super+{key}", style=muted),
                                  str(w.get("windows", 0)) if w else Text("—", style=muted),
                                  Text(w.get("lastwindowtitle", ""), style=muted)]))
        orphans = sorted({w for w in self.info if w > self.draft})
        for i in orphans:
            w = self.info[i]
            rows.append((str(i), [Text(f"  Workspace {i}", style=THEME["status_warn"]),
                                  Text("disabled", style=THEME["status_warn"]), str(w.get("windows", 0)),
                                  Text(w.get("lastwindowtitle", ""), style=muted)]))
        self.query_one("#workspaces", Table).set_rows(rows)
        self.query_one("#ws-panel").border_subtitle = (
            " enter to go · in yellow: windows left on disabled workspaces " if orphans else " enter to go ")

    # ── navegación ──

    def focused(self) -> str:
        f = self.app.focused
        return f.id if f is not None and f.id in self.FOCUSABLE else "ws-count"

    def action_cycle(self, step: int) -> None:
        i = self.FOCUSABLE.index(self.focused())
        self.query_one(f"#{self.FOCUSABLE[(i + step) % len(self.FOCUSABLE)]}").focus()

    def hints(self) -> list[tuple[str, str]]:
        if self.focused() == "ws-count" and HYPRLAND:
            return [("←/→", "how many"), ("enter", "apply"), ("tab", "windows"), ("q", "quit")]
        return [("enter", "go"), ("tab", "panel"), ("q", "quit")]

    # ── acciones ──

    def action_change(self, step: int) -> None:
        if self.focused() != "ws-count" or not HYPRLAND:
            return
        self.draft = max(MIN_WS, min(MAX_WS, self.draft + step))
        self.paint()

    def action_apply(self) -> None:
        if self.focused() != "ws-count" or not HYPRLAND:
            return
        if self.draft == self.saved:
            return self.app.notify_ok(f"{self.saved} workspaces (unchanged)")
        n = self.draft
        stranded = [c for c in self.clients if c.get("workspace", {}).get("id", 0) > n]
        if not stranded:
            return self.save(n)
        names = "\n".join(f"  {c.get('class', '?')} — {c.get('title', '')[:50]} (ws {c['workspace']['id']})"
                          for c in stranded[:8]) + (f"\n  … +{len(stranded) - 8}" if len(stranded) > 8 else "")

        def done(yes: bool) -> None:
            if yes:
                for c in stranded:
                    run(["hyprctl", "dispatch", "movetoworkspacesilent", f"{n},address:{c['address']}"])
            self.save(n)

        self.app.push_screen(ConfirmModal(f"Use {n} workspaces",
                                          f"{len(stranded)} window(s) are on workspaces above {n}:\n{names}\n\n"
                                          f"Move them to workspace {n}? (no = leave them there; "
                                          "they stay reachable from the overview)"), done)

    def save(self, n: int) -> None:
        write_ws_conf(n)
        run(["hyprctl", "reload"])
        errors = run(["hyprctl", "configerrors"]).stdout.strip()
        self.saved = self.draft = n
        if errors and "no errors" not in errors.lower():
            self.app.notify_err(f"Hyprland reported config errors: {errors.splitlines()[0]}")
        else:
            self.app.notify_ok(f"{n} workspaces enabled · keybinds and waybar updated")
        self.reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "workspaces":
            goto_workspace(int(event.row_key.value))
            self.app.exit()
