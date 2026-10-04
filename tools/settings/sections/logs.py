"""Logs — errores del journal (este arranque o el anterior) y unidades fallidas.

Lee `journalctl -o json` (el usuario está en wheel, puede leer el journal
del sistema). Escribir filtra; w alterna errores / errores + warnings;
b alterna este arranque / el anterior; enter muestra el mensaje completo.
"""

from __future__ import annotations

import json
import time

from common import run
from dtui import THEME, DView, Panel, Table, TextModal, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Input, Static


class LogsView(DView):
    FOCUS = "#logs"
    DEFAULT_CSS = css("""
    #logs-filter-panel { height: 3; }
    #logs-filter { background: %(background)s; padding: 0; }
    #logs-failed-panel { height: auto; }
    #logs-failed { height: auto; }
    #logs-panel { height: 1fr; }
    """)
    BINDINGS = [Binding("w", "toggle_level", "warnings"), Binding("b", "toggle_boot", "previous boot"),
                Binding("slash", "focus_filter", "filter"), Binding("r", "reload", "reload")]

    def compose(self) -> ComposeResult:
        yield Panel(Input(placeholder="filter by unit or text…", id="logs-filter"), title="\uf002  Filter",
                    id="logs-filter-panel")
        yield Panel(Static(id="logs-failed"), title="Failed units", id="logs-failed-panel")
        yield Panel(Table(id="logs"), title="󰌱  Journal", id="logs-panel")

    def on_mount(self) -> None:
        t = self.query_one("#logs", Table)
        t.add_column("Time", key="time", width=15)
        t.add_column("Unit", key="unit", width=28)
        t.add_column("Message", key="msg", width=90)
        self.level, self.boot, self.entries = 3, 0, []
        self.action_reload()

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "details"), ("/", "filter"), ("w", "errors/warnings"), ("b", "this/previous boot"),
                ("r", "reload"), ("q", "quit")]

    @work(thread=True, exclusive=True, group="logs")
    def action_reload(self) -> None:
        r = run(["journalctl", "-b", str(-self.boot) if self.boot else "0", "-p", str(self.level),
                 "-o", "json", "--no-pager", "-n", "500"], timeout=20)
        entries = []
        for line in r.stdout.splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            msg = e.get("MESSAGE", "")
            if isinstance(msg, list):   # mensajes binarios vienen como lista de bytes
                msg = bytes(msg).decode(errors="replace")
            ts = int(e.get("__REALTIME_TIMESTAMP", 0)) / 1e6
            entries.append({"time": time.strftime("%d/%m %H:%M:%S", time.localtime(ts)),
                            "unit": e.get("_SYSTEMD_UNIT") or e.get("SYSLOG_IDENTIFIER") or e.get("_COMM", "?"),
                            "prio": int(e.get("PRIORITY", 6)), "msg": msg})
        failed = run(["systemctl", "--failed", "--no-legend", "--plain"]).stdout.split("\n")
        failed_user = run(["systemctl", "--user", "--failed", "--no-legend", "--plain"]).stdout.split("\n")
        self.app.call_from_thread(self.show, list(reversed(entries)),
                                  [l.split()[0] for l in failed if l.strip()],
                                  [l.split()[0] for l in failed_user if l.strip()])

    def show(self, entries: list, failed: list, failed_user: list) -> None:
        self.entries = entries
        f = Text()
        if failed or failed_user:
            for u in failed:
                f.append(f"✗ {u}  ", style=THEME["status_error"])
            for u in failed_user:
                f.append(f"✗ {u} (user)  ", style=THEME["status_error"])
        else:
            f.append("✓ no failed units", style=THEME["status_ok"])
        self.query_one("#logs-failed", Static).update(f)
        self.filter()

    def filter(self) -> None:
        q = self.query_one("#logs-filter", Input).value.strip().lower()
        t = self.query_one("#logs", Table)
        t.clear()
        shown = [(i, e) for i, e in enumerate(self.entries)
                 if not q or q in e["unit"].lower() or q in e["msg"].lower()]
        for i, e in shown:
            c = THEME["status_error"] if e["prio"] <= 3 else THEME["status_warn"]
            t.add_row(Text(e["time"], style=THEME["muted"]), Text(e["unit"][:28], style=c),
                      " ".join(e["msg"].split())[:200], key=str(i))
        self.query_one("#logs-panel").border_subtitle = (
            f" {len(shown)} {'errors' if self.level == 3 else 'errors + warnings'} · "
            f"{'this boot' if not self.boot else 'previous boot'} ")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "logs-filter":
            self.filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "logs-filter":
            event.stop()
            self.query_one("#logs", Table).focus()

    def action_focus_filter(self) -> None:
        self.query_one("#logs-filter", Input).focus()

    def action_toggle_level(self) -> None:
        self.level = 4 if self.level == 3 else 3
        self.action_reload()

    def action_toggle_boot(self) -> None:
        self.boot = 0 if self.boot else 1
        self.action_reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "logs":
            e = self.entries[int(event.row_key.value)]
            self.app.push_screen(TextModal(f"{e['unit']} · {e['time']}", e["msg"], end=False))
