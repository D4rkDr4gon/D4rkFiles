"""Storage — discos y pendrives (lsblk + udisksctl, sin root para lo
removible). enter monta/desmonta una partición, e expulsa (apaga) el
dispositivo, o abre el punto de montaje en el gestor de archivos."""

from __future__ import annotations

import json
import shutil
from typing import Optional

from common import detach, run, tilde
from dtui import THEME, ConfirmModal, DView, Panel, Table, css, meter10
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable


def disks() -> list[dict]:
    r = run(["lsblk", "-J", "-b", "-o", "NAME,PATH,LABEL,SIZE,FSTYPE,MOUNTPOINTS,RM,HOTPLUG,TRAN,MODEL,TYPE"])
    try:
        return json.loads(r.stdout).get("blockdevices", [])
    except ValueError:
        return []


def gb(n) -> str:
    n = float(n or 0)
    return f"{n / 2**30:.0f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"


class StorageView(DView):
    FOCUS = "#storage"
    BINDINGS = [Binding("e", "eject", "eject"), Binding("o", "open", "open")]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="storage"), title="󰋊  Storage", id="storage-panel")

    def on_mount(self) -> None:
        t = self.query_one("#storage", Table)
        t.add_column("Device", key="name", width=34)
        t.add_column("Size", key="size", width=9)
        t.add_column("Type", key="fs", width=8)
        t.add_column("Mounted at", key="mnt", width=26)
        t.add_column("Usage", key="use", width=16)
        self.reload()
        self.set_interval(5, self.tick)

    def on_show(self) -> None:
        if self.is_mounted:
            self.reload()

    def tick(self) -> None:
        if self.visible_now:
            self.reload()

    def reload(self) -> None:
        t = self.query_one("#storage", Table)
        prev = t.selected_key()
        t.clear()
        self.parts: dict[str, dict] = {}
        devs = disks()
        groups = [("Removable", [d for d in devs if d.get("rm") or d.get("hotplug") or d.get("tran") == "usb"]),
                  ("Internal", [d for d in devs if not (d.get("rm") or d.get("hotplug") or d.get("tran") == "usb")
                                and d.get("type") == "disk" and not d["name"].startswith(("zram", "loop"))])]
        muted = THEME["muted"]
        for label, ds in groups:
            t.add_row(Text(label.upper(), style=f"bold {THEME['primary']}"), "", "", "", "", key=f"hdr:{label}")
            if not ds:
                t.add_row(Text("  none connected", style=muted), "", "", "", "", key=f"gap:{label}")
            for d in ds:
                t.add_row(Text(f"󰋊  {d.get('model') or d['name']}", style="bold"), gb(d.get("size")), "", "", "",
                          key=f"disk:{d['path']}")
                for p in d.get("children") or []:
                    mounts = [m for m in (p.get("mountpoints") or []) if m]
                    use = Text("—", style=muted)
                    if mounts and mounts[0] != "[SWAP]":
                        du = shutil.disk_usage(mounts[0])
                        use = meter10(du.used * 100 / du.total)
                    name = p.get("label") or p["name"]
                    t.add_row(f"   └ {name}", gb(p.get("size")), Text(p.get("fstype") or "—", style=muted),
                              Text(tilde(mounts[0]) if mounts else "not mounted",
                                   style="" if mounts else muted), use, key=f"part:{p['path']}")
                    self.parts[p["path"]] = {"mount": mounts[0] if mounts else None, "disk": d["path"],
                                             "removable": label == "Removable", "fstype": p.get("fstype")}
        rows = [str(r.key.value) for r in t.ordered_rows]
        t.first_selectable(rows.index(prev) if prev in rows else 0)

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "mount/unmount"), ("o", "open"), ("e", "eject"), ("q", "quit")]

    def selected_part(self) -> Optional[tuple[str, dict]]:
        key = self.query_one("#storage", Table).selected_key() or ""
        if key.startswith("part:"):
            return key[5:], self.parts[key[5:]]
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "storage" or not (sel := self.selected_part()):
            return
        path, p = sel
        if not p["removable"]:
            return self.app.notify_err("Internal partitions are managed by fstab, not from here")
        if not p["fstype"]:
            return self.app.notify_err("No filesystem on that partition")
        r = run(["udisksctl", "unmount" if p["mount"] else "mount", "-b", path], timeout=30)
        if r.returncode == 0:
            self.app.notify_ok(r.stdout.strip() or "Done")
        else:
            self.app.notify_err((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout)
                                else "udisksctl failed")
        self.reload()

    def action_open(self) -> None:
        if (sel := self.selected_part()) and sel[1]["mount"]:
            detach(["xdg-open", sel[1]["mount"]])

    def action_eject(self) -> None:
        key = self.query_one("#storage", Table).selected_key() or ""
        disk = key[5:] if key.startswith("disk:") else (self.selected_part() or ("", {}))[1].get("disk")
        if not disk or not any(p["disk"] == disk and p["removable"] for p in self.parts.values()):
            return self.app.notify_err("Select a removable drive")

        def done(yes: bool) -> None:
            if not yes:
                return
            for path, p in self.parts.items():
                if p["disk"] == disk and p["mount"]:
                    run(["udisksctl", "unmount", "-b", path], timeout=30)
            r = run(["udisksctl", "power-off", "-b", disk], timeout=30)
            if r.returncode == 0:
                self.app.notify_ok("Safe to remove")
            else:
                self.app.notify_err((r.stderr or r.stdout).strip() or "could not eject")
            self.reload()

        self.app.push_screen(ConfirmModal("Eject drive", f"Unmount and power off {disk}?"), done)
