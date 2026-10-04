"""Snapshots — Timeshift. La lista se lee sin root de
/timeshift/snapshots/*/info.json (modo rsync en el disco del sistema; en
modo btrfs o en otro disco no es legible sin montar y queda vacía); crear, restaurar y borrar necesitan sudo,
así que corren en la misma ventana (Settings se suspende, como Update).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from common import run
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, Table, css
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

SNAP_DIR = Path("/timeshift/snapshots")


def snapshots() -> list[dict]:
    out = []
    for d in sorted(SNAP_DIR.iterdir(), reverse=True) if SNAP_DIR.is_dir() else []:
        info = {}
        try:
            info = json.loads((d / "info.json").read_text())
        except (OSError, ValueError):
            pass
        out.append({"name": d.name, "tags": info.get("tags", ""), "comment": info.get("comments", ""),
                    "sys": info.get("sys-distributor", "")})
    return out


class SnapshotsView(DView):
    FOCUS = "#snaps"
    BINDINGS = [Binding("n", "create", "new snapshot"), Binding("d", "delete", "delete")]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="snaps"), title="󰄄  Snapshots (Timeshift)", id="snaps-panel")

    def on_mount(self) -> None:
        t = self.query_one("#snaps", Table)
        t.add_column("Snapshot", key="name", width=24)
        t.add_column("Type", key="tags", width=12)
        t.add_column("Comment", key="comment", width=60)
        self.reload()

    def on_show(self) -> None:
        if self.is_mounted:
            self.reload()

    def reload(self) -> None:
        t = self.query_one("#snaps", Table)
        t.clear()
        self.items = snapshots()
        tag_name = {"O": "on demand", "B": "boot", "H": "hourly", "D": "daily", "W": "weekly", "M": "monthly"}
        for s in self.items:
            tags = " ".join(tag_name.get(c, c) for c in s["tags"])
            t.add_row(s["name"], Text(tags, style=THEME["muted"]), s["comment"] or Text("—", style=THEME["muted"]),
                      key=s["name"])
        self.query_one("#snaps-panel").border_subtitle = (
            f" {len(self.items)} snapshots · create/restore/delete ask for sudo " if self.items
            else " no snapshots yet · n to create one " if shutil.which("timeshift")
            else " timeshift is not installed ")

    def hints(self) -> list[tuple[str, str]]:
        return [("n", "new"), ("enter", "restore"), ("d", "delete"), ("q", "quit")]

    def sudo_run(self, args: list[str]) -> None:
        with self.app.suspend():
            os.system("clear")
            print("$ sudo timeshift " + " ".join(args) + "\n")
            subprocess.run(["sudo", "timeshift", *args])
            input("\nPress enter to go back to Settings...")
        self.reload()

    def action_create(self) -> None:
        if not shutil.which("timeshift"):
            return self.app.notify_err("timeshift is not installed")

        def done(v: Optional[dict]) -> None:
            if v:
                self.sudo_run(["--create", "--comments", v["comment"] or "from Settings"])

        self.app.push_screen(FormModal("New snapshot", [Field("comment", "Comment (optional)",
                                                              placeholder="e.g. before kernel update")]), done)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "snaps":
            return
        name = str(event.row_key.value)

        def done(yes: bool) -> None:
            if yes:
                self.sudo_run(["--restore", "--snapshot", name])

        self.app.push_screen(ConfirmModal("Restore snapshot",
                                          f"Restore the system to {name}?\nTimeshift will ask for the target "
                                          "and reboot. Files in /home are not touched."), done)

    def action_delete(self) -> None:
        name = self.query_one("#snaps", Table).selected_key()
        if not name:
            return

        def done(yes: bool) -> None:
            if yes:
                self.sudo_run(["--delete", "--snapshot", name])

        self.app.push_screen(ConfirmModal("Delete snapshot", f"Delete snapshot {name}?"), done)
