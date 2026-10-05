"""Maintenance — salud del sistema que se arregla una vez y no se vuelve a mirar.

- Health: limpieza automática de la caché de pacman (paccache.timer, semanal,
  conserva 3 versiones), descargas a medias que deja pacman en la caché, protección
  ante falta de memoria (earlyoom) y los contadores de las dos tablas de abajo.
- Config files: los .pacnew/.pacsave que dejan las actualizaciones (`pacdiff -o`,
  sin root). enter muestra el diff, m los fusiona en nvim -d, k conserva el actual
  (borra el .pacnew), u usa el nuevo (el actual queda como .pacold). Nunca se
  aplican solos: un .pacnew pisa cambios propios (ej. pam_fprintd en pam.d/sudo).
- Failed units: servicios caídos del sistema y del usuario. enter logs, r
  reiniciar, m enmascarar (si es una instancia, la plantilla: todas), x olvidar.

¿Por qué earlyoom y no systemd-oomd? Las apps de Hyprland viven todas en el
scope de la sesión (session-N.scope): oomd mata cgroups enteros, o sea la sesión.
earlyoom mata un proceso, el que más memoria tiene, evitando el compositor, la
barra y la terminal y prefiriendo navegadores/electron.

Todo lo que cambia el sistema va con sudo en la terminal (common.sudo_run).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from common import root_file, run, sudo_run, tilde
from dtui import THEME, ConfirmModal, DView, Panel, Table, TextModal, ago, css, human
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable

PKG_CACHE = Path("/var/cache/pacman/pkg")
PACMAN_LOCK = Path("/var/lib/pacman/db.lck")
EARLYOOM_CONF = Path("/etc/default/earlyoom")
# -m/-s: actúa con menos de 4 % de RAM libre Y menos de 10 % de swap (zram) libre.
# Nombres = comm del proceso (15 caracteres como mucho)
EARLYOOM_ARGS = ("-r 3600 -m 4 -s 10 "
                 "--avoid '^(Hyprland|waybar|sddm|systemd|systemd-.*|dbus-.*|pipewire.*|wireplumber|kitty|"
                 "Xwayland|gtklock|hypridle|dunst|kdeconnectd)$' "
                 "--prefer '^(chromium|chrome|brave|firefox|Isolated Web Co|Web Content|electron|code|"
                 "obsidian|node|java|opencode)$'")


# ── datos ──

def unit_enabled(unit: str) -> bool:
    return run(["systemctl", "is-enabled", unit]).stdout.strip() == "enabled"


def unit_active(unit: str) -> bool:
    return run(["systemctl", "is-active", unit]).stdout.strip() == "active"


def cache_info() -> tuple[int, int, list[str]]:
    """(bytes de paquetes en la caché, cantidad, carpetas download-* que dejó
    pacman al cortarse una descarga). Sin root: los download-* no se pueden leer,
    pero sí listar."""
    size = count = 0
    leftovers = []
    try:
        with os.scandir(PKG_CACHE) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and e.name.startswith("download-"):
                    leftovers.append(e.name)
                elif e.is_file(follow_symlinks=False) and ".pkg.tar" in e.name and not e.name.endswith(".sig"):
                    size += e.stat().st_size
                    count += 1
    except OSError:
        pass
    return size, count, leftovers


def last_oom_kill() -> Optional[tuple[float, str]]:
    """(cuándo, qué) de lo último que mató earlyoom, del journal."""
    r = run(["journalctl", "-u", "earlyoom", "-o", "short-unix", "--no-pager", "-n", "200",
             "--grep", "sending SIG"], timeout=5)
    for line in reversed(r.stdout.splitlines()):
        m = re.match(r"([\d.]+) \S+ \S+: sending SIG\w+ to process \d+ uid \d+ \"([^\"]+)\"", line)
        if m:
            return float(m.group(1)), m.group(2)
    return None


def config_files() -> list[dict]:
    """.pacnew/.pacsave pendientes: [{path, kind, target, mtime, plus, minus, readable}]."""
    out = []
    for line in run(["pacdiff", "-o"], timeout=20).stdout.splitlines():
        p = Path(line.strip())
        if not p.name.endswith((".pacnew", ".pacsave")):
            continue
        kind = p.suffix[1:]
        target = p.with_name(p.name.rsplit(".", 1)[0])
        d = {"path": str(p), "kind": kind, "target": str(target), "mtime": 0.0, "plus": 0, "minus": 0,
             "readable": os.access(p, os.R_OK) and (not target.exists() or os.access(target, os.R_OK)),
             "target_exists": target.exists()}
        try:
            d["mtime"] = p.stat().st_mtime
        except OSError:
            pass
        if d["readable"] and d["target_exists"]:
            diff = run(["diff", str(target), str(p)]).stdout.splitlines()
            d["plus"] = sum(1 for x in diff if x.startswith("> "))
            d["minus"] = sum(1 for x in diff if x.startswith("< "))
        out.append(d)
    return sorted(out, key=lambda d: -d["mtime"])


def failed_units() -> list[dict]:
    out = []
    for scope, extra in (("system", []), ("user", ["--user"])):
        for line in run(["systemctl", *extra, "--failed", "--plain", "--no-legend"]).stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 4:
                out.append({"unit": parts[0], "scope": scope, "desc": parts[4] if len(parts) > 4 else ""})
    return out


def template_of(unit: str) -> Optional[str]:
    """systemd-pcrlogin@1000.service → systemd-pcrlogin@.service."""
    m = re.match(r"^(.+@)[^.]+(\.\w+)$", unit)
    return f"{m.group(1)}{m.group(2)}" if m else None


# ── vista ──

class MaintenanceView(DView):
    FOCUS = "#mnt-health"
    TABLES = ["mnt-health", "mnt-files", "mnt-units"]
    DEFAULT_CSS = css("""
    #mnt-health-panel { height: auto; }
    #mnt-health { height: auto; }
    #mnt-files-panel { width: 1fr; height: 1fr; }
    #mnt-units-panel { width: 1fr; height: 1fr; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False),
        Binding("shift+tab", "cycle(-1)", show=False),
        Binding("m", "merge", "merge .pacnew / mask unit"),
        Binding("k", "keep", "keep current file", show=False),
        Binding("u", "use_new", "use the new file", show=False),
        Binding("r", "restart", "restart unit / refresh", show=False),
        Binding("x", "forget", "forget failed unit", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="mnt-health", show_header=False), title="󰣉  Maintenance", id="mnt-health-panel")
        with Horizontal():
            yield Panel(Table(id="mnt-files"), title="Config files", id="mnt-files-panel")
            yield Panel(Table(id="mnt-units"), title="Failed units", id="mnt-units-panel")

    def on_mount(self) -> None:
        h = self.query_one("#mnt-health", Table)
        h.add_column("", key="name", width=26)
        h.add_column("", key="state", width=34)
        h.add_column("", key="desc", width=64)
        f = self.query_one("#mnt-files", Table)
        f.add_column("File", key="file", width=46)
        f.add_column("Changes", key="chg", width=10)
        f.add_column("Age", key="age", width=10)
        u = self.query_one("#mnt-units", Table)
        u.add_column("Unit", key="unit", width=34)
        u.add_column("", key="scope", width=7)
        u.add_column("Description", key="desc", width=40)
        self.files: list[dict] = []
        self.units: list[dict] = []
        self.health: dict = {}
        self.reload()

    def on_show(self) -> None:
        if self.is_mounted and hasattr(self, "files"):
            self.reload()

    @work(thread=True, exclusive=True, group="mnt")
    def reload(self) -> None:
        size, count, leftovers = cache_info()
        health = {"paccache": unit_enabled("paccache.timer"), "cache": (size, count), "leftovers": leftovers,
                  "earlyoom": shutil.which("earlyoom") is not None, "earlyoom_on": unit_active("earlyoom"),
                  "oom_kill": last_oom_kill(), "pacman_busy": PACMAN_LOCK.exists()}
        files, units = config_files(), failed_units()
        self.app.call_from_thread(self.show, health, files, units)

    def show(self, health: dict, files: list[dict], units: list[dict]) -> None:
        self.health, self.files, self.units = health, files, units
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]

        def state(on: bool, yes: str, no: str, bad: str = warn) -> Text:
            return Text(f"●  {yes}", style=ok) if on else Text(f"○  {no}", style=bad)

        size, count = health["cache"]
        rows = [("paccache", ["󰃢  Package cache cleanup", state(health["paccache"], "weekly", "off"),
                              Text(f"keeps the last 3 versions of each package · now {human(size)} in {count} files"
                                   f"{'' if health['paccache'] else ' · enter to turn on'}", style=muted)])]
        if health["leftovers"]:
            rows.append(("leftovers", ["󰇚  Leftover downloads", Text(f"✗  {len(health['leftovers'])} folders", style=warn),
                                       Text("half-finished pacman downloads (download-*) · enter to delete them",
                                            style=muted)]))
        if not health["earlyoom"]:
            oom = Text("○  not installed", style=warn)
            desc = "kills the biggest app when memory runs out, instead of freezing the session · enter to install"
        else:
            oom = state(health["earlyoom_on"], "watching", "off")
            k = health["oom_kill"]
            desc = (f"last kill: {k[1]} {ago(k[0])}" if k else "nothing killed yet") + \
                " · avoids Hyprland, waybar, kitty · prefers browsers/electron"
        rows.append(("earlyoom", ["󰍛  Out-of-memory guard", oom, Text(desc, style=muted)]))
        rows.append(("files", ["󰈙  Config files to review",
                               Text(f"✗  {len(files)} pending", style=warn) if files else Text("✓  none", style=ok),
                               Text(".pacnew/.pacsave left by updates · review them below", style=muted)]))
        rows.append(("units", ["󰒏  Failed units",
                               Text(f"✗  {len(units)} failed", style=err) if units else Text("✓  none", style=ok),
                               Text("services that failed to start (system and user)", style=muted)]))
        self.query_one("#mnt-health", Table).set_rows(rows)
        self.query_one("#mnt-health-panel").border_subtitle = \
            " pacman is running · wait before cleaning " if health["pacman_busy"] else " changes ask for sudo "

        primary = THEME["primary"]
        frows = []
        for d in files:
            chg = Text(f"+{d['plus']} −{d['minus']}", style=muted) if d["readable"] and d["target_exists"] else \
                Text("no file" if not d["target_exists"] else "root only", style=warn)
            name = tilde(d["target"])
            name = name if len(name) <= 36 else "…" + name[-35:]
            frows.append((d["path"], [Text.assemble((name, ""), (f"  .{d['kind']}", primary)), chg,
                                      Text(ago(d["mtime"]) if d["mtime"] else "—", style=muted)]))
        self.query_one("#mnt-files", Table).set_rows(frows)
        self.query_one("#mnt-files-panel").border_subtitle = \
            " enter diff · m merge · k keep current · u use new " if files else " nothing to review "
        self.query_one("#mnt-units", Table).set_rows([
            (f"{u['scope']}:{u['unit']}", [Text(u["unit"], style=err), Text(u["scope"], style=muted),
                                          Text(u["desc"], style=muted)]) for u in units])
        self.query_one("#mnt-units-panel").border_subtitle = \
            " enter logs · r restart · m mask · x forget " if units else " all good "

    # ── navegación ──

    def focused_table(self) -> str:
        f = self.app.focused
        return f.id if f is not None and f.id in self.TABLES else ""

    def action_cycle(self, step: int) -> None:
        i = self.TABLES.index(self.focused_table()) if self.focused_table() else 0
        self.query_one(f"#{self.TABLES[(i + step) % len(self.TABLES)]}", Table).focus()
        self.update_hints()

    def hints(self) -> list[tuple[str, str]]:
        t = self.focused_table()
        if t == "mnt-files":
            return [("enter", "diff"), ("m", "merge"), ("k", "keep current"), ("u", "use new"), ("tab", "panel")]
        if t == "mnt-units":
            return [("enter", "logs"), ("r", "restart"), ("m", "mask"), ("x", "forget"), ("tab", "panel")]
        return [("enter", "turn on/off · fix"), ("r", "refresh"), ("tab", "panel"), ("q", "quit")]

    def selected(self, table: str) -> Optional[str]:
        if self.focused_table() != table:
            return None
        return self.query_one(f"#{table}", Table).selected_key()

    def file(self, key: Optional[str]) -> Optional[dict]:
        return next((d for d in self.files if d["path"] == key), None)

    def unit(self, key: Optional[str]) -> Optional[dict]:
        return next((u for u in self.units if f"{u['scope']}:{u['unit']}" == key), None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tid, key = event.data_table.id, str(event.row_key.value)
        if tid == "mnt-health":
            self.health_action(key)
        elif tid == "mnt-files" and (d := self.file(key)):
            self.show_diff(d)
        elif tid == "mnt-units" and (u := self.unit(key)):
            extra = ["--user"] if u["scope"] == "user" else []
            r = run(["journalctl", *extra, "-b", "-u", u["unit"], "-n", "120", "--no-pager"])
            st = run(["systemctl", *extra, "status", u["unit"], "--no-pager", "-n", "0"])
            self.app.push_screen(TextModal(f"Logs · {u['unit']}", (st.stdout + "\n" + (r.stdout or r.stderr))
                                           .strip() or "(empty)", end=True))

    # ── Health ──

    def health_action(self, key: str) -> None:
        h = self.health
        if key == "paccache":
            verb = "disable" if h.get("paccache") else "enable"
            if sudo_run(self.app, [["systemctl", verb, "--now", "paccache.timer"]],
                        "Weekly package cache cleanup (paccache.timer)"):
                self.app.notify_ok("Package cache cleanup " + ("off" if verb == "disable" else "on: weekly"))
        elif key == "leftovers":
            if h.get("pacman_busy"):
                return self.app.notify_err("pacman is running: try again when it finishes")
            dirs = [str(PKG_CACHE / n) for n in h.get("leftovers", [])]
            if dirs and sudo_run(self.app, [["rm", "-rf", "--", *dirs]], "Delete leftover pacman downloads"):
                self.app.notify_ok(f"Deleted {len(dirs)} leftover folders")
        elif key == "earlyoom":
            if not h.get("earlyoom"):
                conf = root_file("# Generado por Settings → Maintenance (dotfiles). Ver `man earlyoom`.\n"
                                 f'EARLYOOM_ARGS="{EARLYOOM_ARGS}"\n')
                if sudo_run(self.app, [["pacman", "-S", "--needed", "--noconfirm", "earlyoom"],
                                       ["install", "-m644", conf, str(EARLYOOM_CONF)],
                                       ["systemctl", "enable", "--now", "earlyoom"]],
                            "Install earlyoom (out-of-memory guard)"):
                    self.app.notify_ok("earlyoom installed and watching")
            else:
                verb = "disable" if h.get("earlyoom_on") else "enable"
                if sudo_run(self.app, [["systemctl", verb, "--now", "earlyoom"]], f"earlyoom: {verb}"):
                    self.app.notify_ok("Out-of-memory guard " + ("off" if verb == "disable" else "on"))
        elif key == "files":
            self.query_one("#mnt-files", Table).focus()
            self.update_hints()
            return
        elif key == "units":
            self.query_one("#mnt-units", Table).focus()
            self.update_hints()
            return
        self.reload()

    # ── .pacnew ──

    def show_diff(self, d: dict) -> None:
        if not d["target_exists"]:
            body = (f"{d['target']} no longer exists: the package was removed and pacman kept your copy.\n\n"
                    "k deletes the .pacsave · u puts it back in place")
        elif not d["readable"]:
            body = "Only root can read one of the files: m opens both in nvim -d with sudo."
        else:
            body = run(["diff", "-u", d["target"], d["path"]]).stdout or "(identical: k deletes the copy)"
            body = (f"--- current  {d['target']}\n+++ new      {d['path']}\n\n"
                    "Lines with - are yours (or the old default) and would be lost with u;\n"
                    "lines with + are what the package brings now. m merges by hand.\n\n" + body)
        self.app.push_screen(TextModal(f"Diff · {tilde(d['target'])}", body, end=False))

    def action_merge(self) -> None:
        if (d := self.file(self.selected("mnt-files"))):
            if not d["target_exists"]:
                return self.app.notify_err("Nothing to merge with: u puts the .pacsave back")
            editor = "nvim" if shutil.which("nvim") else "vim"
            sudo_run(self.app, [[editor, "-d", d["target"], d["path"]]],
                     f"Merge: left = current file, right = {d['kind']}.\n"
                     "Copy what you want into the LEFT one (do / dp), save with :wqa")

            def done(yes: bool) -> None:
                if yes and sudo_run(self.app, [["rm", "-f", d["path"]]]):
                    self.app.notify_ok(f"Merged {tilde(d['target'])}")
                self.reload()

            self.app.push_screen(ConfirmModal("Merged?", f"Delete {tilde(d['path'])} now that it is merged?"), done)
        elif (u := self.unit(self.selected("mnt-units"))):
            self.mask(u)

    def action_keep(self) -> None:
        if not (d := self.file(self.selected("mnt-files"))):
            return

        def done(yes: bool) -> None:
            if yes and sudo_run(self.app, [["rm", "-f", d["path"]]]):
                self.app.notify_ok(f"Kept the current {tilde(d['target'])}")
            self.reload()

        self.app.push_screen(ConfirmModal("Keep the current file",
                                          f"Delete {tilde(d['path'])} and keep {tilde(d['target'])} as it is?"), done)

    def action_use_new(self) -> None:
        if not (d := self.file(self.selected("mnt-files"))):
            return
        if not d["target_exists"]:
            cmds, msg = [["mv", d["path"], d["target"]]], f"Put {tilde(d['path'])} back as {tilde(d['target'])}?"
        else:
            cmds = [["cp", "-a", d["target"], d["target"] + ".pacold"], ["mv", d["path"], d["target"]]]
            msg = (f"Replace {tilde(d['target'])} with the new version?\n"
                   f"Your current one is kept as {tilde(d['target'])}.pacold. Lines you added are lost: "
                   "check the diff (enter) first.")

        def done(yes: bool) -> None:
            if yes and sudo_run(self.app, cmds):
                self.app.notify_ok(f"Using the new {tilde(d['target'])}")
            self.reload()

        self.app.push_screen(ConfirmModal("Use the new file", msg), done)

    # ── units ──

    def ctl(self, u: dict, *args: str, title: str) -> bool:
        if u["scope"] == "user":
            r = run(["systemctl", "--user", *args])
            if r.returncode:
                self.app.notify_err(r.stderr.strip() or "systemctl failed")
            return r.returncode == 0
        return sudo_run(self.app, [["systemctl", *args]], title)

    def mask(self, u: dict) -> None:
        tpl = template_of(u["unit"])
        target = tpl or u["unit"]
        msg = (f"Mask {target}? It will never start again (systemctl unmask {target} undoes it)."
               + (f"\nIt is a template: every {tpl.split('@')[0]}@… instance is masked." if tpl else ""))

        def done(yes: bool) -> None:
            if yes:
                ok = self.ctl(u, "mask", target, title=f"Mask {target}") and \
                    self.ctl(u, "reset-failed", *[x["unit"] for x in self.units if x["scope"] == u["scope"] and
                                                  (template_of(x["unit"]) or x["unit"]) == target],
                             title="Forget the failure")
                if ok:
                    self.app.notify_ok(f"Masked {target}")
            self.reload()

        self.app.push_screen(ConfirmModal("Mask unit", msg), done)

    def action_restart(self) -> None:
        if (u := self.unit(self.selected("mnt-units"))):
            if self.ctl(u, "restart", u["unit"], title=f"Restart {u['unit']}"):
                self.app.notify_ok(f"Restarted {u['unit']}")
        else:
            self.app.notify_ok("refreshing…")
        self.reload()

    def action_forget(self) -> None:
        if (u := self.unit(self.selected("mnt-units"))):
            if self.ctl(u, "reset-failed", u["unit"], title=f"Forget the failure of {u['unit']}"):
                self.app.notify_ok(f"{u['unit']}: failure cleared (it comes back if it fails again)")
            self.reload()
