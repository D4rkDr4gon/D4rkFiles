#!/usr/bin/env python3
"""
backup_tui.py — TUI del backup en Proton Drive (Settings → BACKUP).

Muestra cada carpeta de ~/.config/dotfiles/proton-backup.conf con su estado en vivo
(barra de avance, velocidad, tiempo restante, última subida) y permite
lanzar/cancelar la subida, agregar/editar/quitar carpetas e iniciar sesión
en Proton. La subida la hace scripts/proton-backup.sh en segundo plano
(sigue aunque se cierre la ventana); esta TUI solo lee su estado en
~/.local/state/proton-backup y lo llama con start/cancel.

Estilo común de las TUIs: tools/dtui.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import (THEME, ConfirmModal, DView, Field, FormModal, Panel, Table, TextModal, ViewApp,  # noqa: E402
                  ago, bar, css, duration, human)

from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.widgets import DataTable, Static  # noqa: E402

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de tools/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
CONF = Path(os.environ.get("PROTON_BACKUP_CONF") or CONFIG_HOME / "dotfiles" / "proton-backup.conf")
EXAMPLE = DOTFILES / "proton-backup.conf.example"
STATE = Path(os.environ.get("PROTON_BACKUP_STATE") or STATE_HOME / "dotfiles" / "proton-backup")
BACKUP = DOTFILES / "scripts" / "proton-backup.sh"
DEFAULT_ICON = "󰉋"
DEFAULT_EXCL = ".git node_modules"
REMOTE_BASE = "/my-files/Backups"
ACTIVE = {"scanning", "staging", "uploading", "cleaning"}


@dataclass
class Folder:
    id: str
    icon: str
    name: str
    local: str
    remote: str
    excl: str

    def line(self) -> str:
        return "|".join([self.id, self.icon, self.name, self.local, self.remote, self.excl])


# ── proton-backup.conf (id|ícono|nombre|local|remota|exclusiones) ──

def read_conf() -> list[Folder]:
    out = []
    try:
        for raw in CONF.read_text().splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            parts = (raw.split("|") + [""] * 6)[:6]
            out.append(Folder(*parts))
    except OSError:
        pass
    return out


def write_conf(folders: list[Folder]) -> None:
    """Reescribe las líneas de carpetas conservando los comentarios."""
    try:
        comments = [l for l in (CONF if CONF.exists() else EXAMPLE).read_text().splitlines()
                    if l.lstrip().startswith("#")]
    except OSError:
        comments = []
    CONF.parent.mkdir(parents=True, exist_ok=True)
    CONF.write_text("\n".join(comments + [f.line() for f in folders]) + "\n")


def kv(path: Path) -> dict:
    d = {}
    try:
        for l in path.read_text().splitlines():
            if "=" in l:
                k, v = l.split("=", 1)
                d[k] = v
    except OSError:
        pass
    return d


def running() -> bool:
    """Igual que `proton-backup.sh running`, sin lanzar un proceso por segundo."""
    try:
        pid = int((STATE / "runner.pid").read_text().strip())
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        return b"proton-backup.sh run" in cmd
    except (OSError, ValueError):
        return False


def backup(*args: str) -> None:
    subprocess.run(["bash", str(BACKUP), *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "folder"


# ── Vista ─────────────────────────────────────────────────

class BackupView(DView):
    """Carpetas + detalle + actividad. Se usa sola (BackupApp) o en Settings."""

    FOCUS = "#table"
    DEFAULT_CSS = css("""
    #folders { height: auto; max-height: 50%%; }
    #table { height: auto; max-height: 100%%; }
    #detail { height: auto; }
    #detail Static { height: auto; }
    #activity { height: 1fr; }
    #activity Static { height: auto; }
    """)

    BINDINGS = [
        Binding("u", "upload_all", "update all"),
        Binding("x", "cancel", "cancel"),
        Binding("a", "add", "add"),
        Binding("e", "edit", "edit"),
        Binding("d", "remove", "remove"),
        Binding("l", "log", "log"),
        Binding("L", "login", "login"),
        Binding("j", "down", show=False),
        Binding("k", "up", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="table"), title="󰅧  Proton Drive", id="folders")
        yield Panel(Static(id="info"), title="Details", id="detail")
        yield Panel(Static(id="log"), title="Activity", id="activity")

    def on_mount(self) -> None:
        t = self.query_one("#table", DataTable)
        t.add_column("Folder", key="name", width=20)
        t.add_column("State", key="state", width=17)
        t.add_column("", key="extra", width=38)
        t.add_column("Last", key="last", width=11)
        t.add_column("Files", key="files", width=8)
        t.add_column("Size", key="size", width=8)
        self.folders: list[Folder] = []
        self.refresh_data()
        self.set_interval(1, self.tick)

    def tick(self) -> None:
        # En Settings, sin refrescar mientras la sección no se ve
        if self.visible_now:
            self.refresh_data()

    # ── datos en vivo ──

    def status(self, fid: str) -> tuple[dict, dict]:
        return kv(STATE / f"{fid}.status"), kv(STATE / f"{fid}.progress")

    def row_cells(self, f: Folder) -> list:
        st, pr = self.status(f.id)
        state, msg = st.get("state", ""), st.get("msg", "")
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]
        name = Text(f"{f.icon or DEFAULT_ICON}  {f.name}")
        extra = Text("")
        if state == "uploading" and pr.get("pct"):
            pct = int(pr.get("pct", 0))
            s = bar(pct, 12)
            s.append(f" {pct:3d}%", style="bold")
            extra = Text(f"{human(pr.get('done'))} of {human(pr.get('total'))} · "
                         f"{human(pr.get('speed'))}/s · {duration(pr.get('eta'))}", style=muted)
        elif state in ACTIVE:
            s = Text(f"󰑐  {msg}", style=warn)
        elif state == "queued":
            s = Text("⋯  queued", style=muted)
        elif state == "ok":
            s = Text("✓  up to date", style=ok)
            extra = Text(msg, style=muted)
        elif state == "error":
            s = Text("✗  error", style=err)
            extra = Text(msg, style=err)
        elif state == "cancelled":
            s = Text("■  cancelled", style=warn)
        else:
            s = Text("·  never uploaded" if not st.get("last_ok") else "✓  up to date", style=muted)
        last = ago(st["last_ok"]) if st.get("last_ok") else "never"
        files = st.get("last_files", "")
        size = human(st["last_bytes"]) if st.get("last_bytes") else ""
        return [name, s, extra, last, files, size]

    def refresh_data(self) -> None:
        t = self.query_one("#table", DataTable)
        folders = read_conf()
        ids = [f.id for f in folders]
        if ids != [f.id for f in self.folders]:
            cur = self.current()
            t.clear()
            for f in folders:
                t.add_row(*self.row_cells(f), key=f.id)
            if cur and cur.id in ids:
                t.move_cursor(row=ids.index(cur.id))
        else:
            for f in folders:
                for col, val in zip(("name", "state", "extra", "last", "files", "size"), self.row_cells(f)):
                    t.update_cell(f.id, col, val)
        self.folders = folders
        self.update_header()
        self.update_detail()
        self.update_activity()
        self.update_hints()

    def update_activity(self) -> None:
        """Últimas líneas de runner.log (las que entran en el panel)."""
        panel = self.query_one("#activity")
        n = max(1, panel.size.height - 2)
        try:
            lines = (STATE / "runner.log").read_text().splitlines()
        except OSError:
            lines = []
        names = {f.id: f.name for f in self.folders}
        t = Text()
        for l in lines[-n:]:
            m = re.match(r"\d{4}-(\d\d)-(\d\d) (\d\d:\d\d):\d\d (.*)", l)
            if not m:
                continue
            msg = re.sub(r"\((\d+) bytes\)", lambda b: f"({human(b.group(1))})", m.group(4))
            m2 = re.match(r"\[([^\]]+)\] (.*)", msg)
            t.append(f"{m.group(2)}/{m.group(1)} {m.group(3)}  ", style=THEME["muted"])
            if m2:
                t.append(f"{names.get(m2.group(1), m2.group(1))}  ", style=f"bold {THEME['foreground']}")
                msg = m2.group(2)
            style = THEME["status_error"] if re.search(r"fail|error|falló|fallidos", msg) else (
                THEME["status_ok"] if msg.startswith("ok") else THEME["foreground"])
            t.append(msg + "\n", style=style)
        self.query_one("#log", Static).update(t or Text("No activity yet.", style=THEME["muted"]))

    def update_header(self) -> None:
        panel = self.query_one("#folders")
        if running():
            n = len(self.folders)
            cur = next(((i, f) for i, f in enumerate(self.folders, 1)
                        if self.status(f.id)[0].get("state") in ACTIVE), None)
            panel.border_subtitle = f" uploading {cur[1].name} ({cur[0]}/{n}) " if cur else " preparing "
        else:
            lasts = [self.status(f.id)[0].get("last_ok") for f in self.folders]
            if not self.folders:
                panel.border_subtitle = " no folders: press a to add one "
            elif not all(lasts):
                panel.border_subtitle = " some folders are not backed up "
            else:
                panel.border_subtitle = f" all backed up · oldest {ago(min(int(x) for x in lasts))} "

    def current(self) -> Optional[Folder]:
        t = self.query_one("#table", DataTable)
        if not self.folders or t.cursor_row is None or t.cursor_row >= len(self.folders):
            return None
        return self.folders[t.cursor_row]

    def on_data_table_row_highlighted(self, _event) -> None:
        self.update_detail()

    def update_detail(self) -> None:
        info = self.query_one("#info", Static)
        f = self.current()
        if not f:
            info.update(Text("Add a folder with a.", style=THEME["muted"]))
            return
        st, pr = self.status(f.id)
        t = Text()

        def row(label: str, value: str | Text, style: str = "") -> None:
            t.append(f"{label:<11}", style=f"bold {THEME['muted']}")
            t.append(value if isinstance(value, Text) else Text(value, style=style))
            t.append("\n")

        row("Local", f.local)
        row("Remote", f.remote)
        row("Excludes", f.excl or "—")
        if st.get("last_ok"):
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(int(st["last_ok"])))
            row("Last", f"{when} ({ago(st['last_ok'])}) · {st.get('last_files', '?')} files · "
                        f"{human(st.get('last_bytes'))}")
        else:
            row("Last", "never")
        if st.get("msg"):
            row("Result", st["msg"], THEME["status_error"] if st.get("state") == "error" else "")
        if st.get("state") == "uploading" and pr:
            row("Uploading", f"{pr.get('current', '')} · {pr.get('files_done', 0)} files done")
        info.update(t)

    def hints(self) -> list[tuple[str, str]]:
        hints = [("x", "cancel upload")] if running() else [("enter", "upload"), ("u", "update all")]
        return hints + [("a", "add"), ("e", "edit"), ("d", "remove"), ("l", "log"), ("L", "login"), ("q", "quit")]

    # ── acciones ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "table":
            self.action_upload_one()

    def action_down(self) -> None:
        self.query_one("#table", DataTable).action_cursor_down()

    def action_up(self) -> None:
        self.query_one("#table", DataTable).action_cursor_up()

    def busy(self) -> bool:
        if running():
            self.app.notify_err("An upload is in progress: wait for it to finish or cancel it with x")
            return True
        return False

    def action_upload_one(self) -> None:
        f = self.current()
        if f and not self.busy():
            backup("start", f.id)
            self.app.notify_ok(f"Uploading {f.name}")
            self.refresh_data()

    def action_upload_all(self) -> None:
        if self.folders and not self.busy():
            backup("start")
            self.app.notify_ok("Uploading all folders")
            self.refresh_data()

    def action_cancel(self) -> None:
        if not running():
            return

        def done(yes: bool) -> None:
            if yes:
                backup("cancel")
                self.app.notify_ok("Upload cancelled")

        self.app.push_screen(ConfirmModal("Cancel upload",
                                          "What's already uploaded stays in Proton Drive; next time\n"
                                          "it resumes from what was missing. Cancel?"), done)

    def validator(self, me: str = ""):
        def check(v: dict) -> Optional[str]:
            if not v["name"]:
                return "The name is missing"
            if "|" in "".join(v.values()):
                return "| can't be used"
            if any(f.name == v["name"] and f.id != me for f in self.folders):
                return f"There is already a folder called {v['name']}"
            if not Path(v["local"]).expanduser().is_dir():
                return f"Folder not found: {v['local']}"
            if not v["remote"].startswith("/my-files/"):
                return "The remote folder must start with /my-files/"
            return None
        return check

    def form_fields(self, f: Optional[Folder]) -> list[Field]:
        return [
            Field("local", "Local folder", f.local if f else str(Path.home()) + "/", paths=True),
            Field("name", "Name", f.name if f else ""),
            Field("icon", "Icon (Nerd Font)", f.icon if f else DEFAULT_ICON),
            Field("remote", "Proton Drive folder", f.remote if f else "", placeholder=f"{REMOTE_BASE}/<name>"),
            Field("excl", "Exclude (space separated; with / it's relative to the root)",
                  f.excl if f else DEFAULT_EXCL),
        ]

    @staticmethod
    def normalize(v: dict) -> dict:
        v["local"] = str(Path(v["local"]).expanduser().resolve())
        if not v["name"]:
            v["name"] = Path(v["local"]).name
        if not v["remote"]:
            v["remote"] = f"{REMOTE_BASE}/{v['name']}"
        v["remote"] = v["remote"].rstrip("/")
        return v

    def action_add(self) -> None:
        def done(v: Optional[dict]) -> None:
            if not v:
                return
            fid, base, n = slug(v["name"]), slug(v["name"]), 2
            while any(f.id == fid for f in self.folders):
                fid, n = f"{base}-{n}", n + 1
            folders = read_conf() + [Folder(fid, v["icon"], v["name"], v["local"], v["remote"], v["excl"])]
            write_conf(folders)
            self.app.notify_ok(f"{v['name']} added: press enter to upload it")
            self.refresh_data()
            self.query_one("#table", DataTable).move_cursor(row=len(folders) - 1)

        check = self.validator()
        self.app.push_screen(FormModal("Add folder", self.form_fields(None),
                                       hint="Name and destination are filled in automatically if left empty.",
                                       validate=lambda v: check(self.normalize(dict(v)))),
                             lambda v: done(self.normalize(v) if v else None))

    def action_edit(self) -> None:
        f = self.current()
        if not f or self.busy():
            return

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            v = self.normalize(v)
            folders = read_conf()
            for g in folders:
                if g.id == f.id:
                    g.icon, g.name, g.local, g.remote, g.excl = v["icon"], v["name"], v["local"], v["remote"], v["excl"]
            write_conf(folders)
            # Otra carpeta local o remota: la próxima subida compara todo de cero
            # (el CLI saltea lo que ya está igual en Proton)
            if v["local"] != f.local or v["remote"] != f.remote:
                for ext in ("files", "dirs"):
                    (STATE / f"{f.id}.{ext}").unlink(missing_ok=True)
                self.app.notify_ok("Saved: the next upload checks the whole folder")
            else:
                self.app.notify_ok("Saved")
            self.refresh_data()

        check = self.validator(f.id)
        self.app.push_screen(FormModal(f"Edit {f.name}", self.form_fields(f),
                                       validate=lambda v: check(self.normalize(dict(v)))), done)

    def action_remove(self) -> None:
        f = self.current()
        if not f or self.busy():
            return

        def done(yes: bool) -> None:
            if not yes:
                return
            write_conf([g for g in read_conf() if g.id != f.id])
            for ext in ("files", "dirs", "status", "progress", "last.log", "failed"):
                (STATE / f"{f.id}.{ext}").unlink(missing_ok=True)
            self.app.notify_ok(f"{f.name} removed")
            self.refresh_data()

        self.app.push_screen(ConfirmModal("Remove folder",
                                          f"{f.name} will no longer be backed up.\n"
                                          f"The copy in Proton Drive ({f.remote}) is left untouched. Remove?"), done)

    def action_log(self) -> None:
        f = self.current()
        if not f:
            return
        t = Text()
        t.append("Last upload\n", style=f"bold {THEME['primary']}")
        try:
            t.append((STATE / f"{f.id}.last.log").read_text() or "(empty)\n")
        except OSError:
            t.append("(none yet)\n")
        t.append("\nHistory\n", style=f"bold {THEME['primary']}")
        try:
            lines = [l for l in (STATE / "runner.log").read_text().splitlines() if f"[{f.id}]" in l]
            t.append("\n".join(lines[-200:]) or "(empty)")
        except OSError:
            t.append("(empty)")
        self.app.push_screen(TextModal(f"Log · {f.name}", t))

    def action_login(self) -> None:
        with self.app.suspend():
            os.system("clear")
            print("Sign in to Proton Drive\n")
            subprocess.run(["proton-drive", "auth", "login"])
            input("\nPress enter to go back...")
        self.refresh_data()


def BackupApp() -> ViewApp:
    return ViewApp(BackupView, title="Backup")


if __name__ == "__main__":
    BackupApp().run()
