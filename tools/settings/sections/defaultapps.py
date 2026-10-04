"""Default apps — aplicaciones predeterminadas (xdg-mime). enter lista las apps
instaladas que declaran soportar ese tipo (MimeType de su .desktop) y la
elegida queda como default para todos los tipos de su categoría (ej. el
navegador para http, https y text/html)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from common import run
from dtui import THEME, DView, Panel, PickModal, Table, css
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import DataTable

CATEGORIES = [
    ("browser", "󰖟  Web browser", ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]),
    ("files", "󰉋  File manager", ["inode/directory"]),
    ("text", "󰈙  Text editor", ["text/plain", "text/markdown", "application/x-shellscript"]),
    ("pdf", "󰈦  PDF viewer", ["application/pdf"]),
    ("image", "󰋩  Image viewer", ["image/png", "image/jpeg", "image/webp", "image/gif"]),
    ("video", "󰕧  Video player", ["video/mp4", "video/x-matroska", "video/webm"]),
    ("audio", "󰎆  Music player", ["audio/mpeg", "audio/flac", "audio/ogg"]),
    ("mail", "󰇮  Email", ["x-scheme-handler/mailto"]),
]
APP_DIRS = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications",
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"), Path("/usr/share/applications")]


def desktop_apps() -> dict[str, dict]:
    """desktop-id → {name, mimes} de las apps visibles."""
    apps: dict[str, dict] = {}
    for d in APP_DIRS:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            if f.name in apps:
                continue
            try:
                main = f.read_text(errors="ignore").split("\n[", 1)[0]
            except OSError:
                continue
            if re.search(r"^NoDisplay=true", main, re.M) or re.search(r"^Hidden=true", main, re.M):
                continue
            name = re.search(r"^Name=(.*)$", main, re.M)
            mimes = re.search(r"^MimeType=(.*)$", main, re.M)
            apps[f.name] = {"name": name.group(1) if name else f.stem,
                            "mimes": set(filter(None, mimes.group(1).split(";"))) if mimes else set()}
    return apps


def current_default(mime: str) -> str:
    return run(["xdg-mime", "query", "default", mime]).stdout.strip()


class DefaultAppsView(DView):
    FOCUS = "#defaults"

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="defaults"), title="󰀻  Default apps", id="defaults-panel")

    def on_mount(self) -> None:
        t = self.query_one("#defaults", Table)
        t.add_column("Category", key="cat", width=24)
        t.add_column("App", key="app", width=34)
        t.add_column("Types", key="mimes", width=60)
        self.apps = desktop_apps()
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#defaults", Table)
        row = t.cursor_row or 0
        t.clear()
        for key, label, mimes in CATEGORIES:
            cur = current_default(mimes[0])
            name = self.apps.get(cur, {}).get("name", cur) if cur else ""
            t.add_row(label, Text(name or "not set", style="bold" if name else THEME["muted"]),
                      Text(", ".join(mimes), style=THEME["muted"]), key=key)
        t.move_cursor(row=row)
        self.query_one("#defaults-panel").border_subtitle = " xdg-mime · ~/.config/mimeapps.list "

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "choose app"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "defaults":
            return
        key = str(event.row_key.value)
        _k, label, mimes = next(c for c in CATEGORIES if c[0] == key)
        cands = sorted(((did, a) for did, a in self.apps.items() if a["mimes"] & set(mimes)),
                       key=lambda x: x[1]["name"].lower())
        if not cands:
            return self.app.notify_err("No installed app declares support for these types")
        cur = current_default(mimes[0])
        rows = [(did, [Text(("● " if did == cur else "  ") + a["name"], style="bold" if did == cur else ""),
                       Text(did, style=THEME["muted"])]) for did, a in cands]

        def picked(did: Optional[str]) -> None:
            if not did:
                return
            run(["xdg-mime", "default", did, *mimes])
            if key == "browser":
                run(["xdg-settings", "set", "default-web-browser", did])
            self.app.notify_ok(f"{label.split('  ', 1)[-1]}: {self.apps[did]['name']}")
            self.reload()

        self.app.push_screen(PickModal(f"Default {label.split('  ', 1)[-1].lower()}", ["App", "Desktop file"],
                                       rows), picked)
