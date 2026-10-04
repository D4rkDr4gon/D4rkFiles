"""Update — estado del sistema + acciones de scripts/dotfiles-update.sh.

- System status: paquetes pendientes (pacman + AUR), última actualización
  completa (/var/log/pacman.log), último snapshot de Timeshift, si hay que
  reiniciar por kernel nuevo, vulnerabilidades (arch-audit) y firmware (fwupd).
  enter sobre una fila corre la acción que le corresponde.
- Actions: los modos del script agrupados; corren en la misma ventana (sudo
  necesita terminal) y al volver se refresca todo.
- Pending: los paquetes por actualizar, los importantes primero.
- Installed (v alterna con Pending), al estilo pacseek: todos los paquetes
  instalados (`pacman -Qi`), búsqueda por nombre/descripción (/), solo los
  instalados a mano (e), orden por tamaño (s) y detalles del seleccionado
  (dependencias, quién lo requiere, fecha, origen). x desinstala con
  `sudo pacman -Rns`, mostrando antes la lista exacta (`pacman -Rs --print`,
  que no necesita root) y avisando si es un paquete crítico.

Lo lento (checkupdates, yay -Qua, arch-audit: salen a la red) corre en workers.
Los pendientes se cachean en ~/.local/state/dotfiles/settings/update.json: al
entrar se ven al instante y se refrescan si tienen más de 15 min (o con r).
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from common import DOTFILES, STATE, run
from dtui import THEME, Card, ConfirmModal, DView, Panel, Table, ago, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import ContentSwitcher, DataTable, Input

UPDATE_SH = DOTFILES / "scripts" / "dotfiles-update.sh"
CACHE = STATE / "update.json"
PENDING_MAX_AGE = 15 * 60
PACMAN_LOG = Path("/var/log/pacman.log")
SNAP_DIR = Path("/timeshift/snapshots")
# Los que conviene ver primero (y que suelen pedir reinicio)
IMPORTANT = re.compile(r"^(linux|linux-[a-z]+|systemd|glibc|mesa|nvidia.*|hyprland.*|pacman|grub|"
                       r"systemd-.*|pipewire|wireplumber|networkmanager|firefox)$")

ACTIONS = [
    ("Update", [("all", "󰚰", "Full update", "snapshot → pacman → AUR → clean"),
                ("check", "󰍉", "Check", "list what's pending, change nothing"),
                ("pacman", "󰣇", "Pacman", "official repositories only"),
                ("aur", "󰏗", "AUR (yay)", "AUR packages only")]),
    ("Safety", [("snapshot", "󰄄", "Snapshot", "create a Timeshift snapshot"),
                ("rollback", "󰑗", "Rollback", "list snapshots to restore one")]),
    ("Maintenance", [("clean", "󰃢", "Clean", "package cache and journal"),
                     ("orphans", "󰆴", "Orphans", "remove packages nobody needs")]),
    ("Security", [("audit", "󰒃", "Security audit", "installed packages with known CVEs"),
                  ("firmware", "󰍛", "Firmware", "check and install firmware (fwupd)")]),
]
# Desinstalarlos rompe el sistema o la sesión: se pide confirmación con aviso
CRITICAL = re.compile(r"^(base|linux|linux-[a-z]+|linux-firmware.*|systemd|glibc|pacman|sudo|bash|filesystem|"
                      r"coreutils|networkmanager|hyprland|python|kitty|grub|mkinitcpio|dbus.*)$")
# enter sobre una fila de estado → modo del script
STATUS_ACTION = {"pending": "all", "last": "check", "snapshot": "snapshot", "security": "audit",
                 "firmware": "firmware"}


# ── datos ──

def audit_status() -> tuple[str, str]:
    """(resumen, nivel) de arch-audit; nivel = clave de color del tema."""
    if not shutil.which("arch-audit"):
        return "arch-audit is not installed", "status_warn"
    r = run(["arch-audit"])
    if r.returncode != 0:
        return "could not reach security.archlinux.org", "status_warn"
    n = len(r.stdout.splitlines())
    fix = len(run(["arch-audit", "-u"]).stdout.splitlines())
    if not n:
        return "✓ no known vulnerabilities", "status_ok"
    return f"{n} vulnerable · {fix} fixed by updating", "status_error" if fix else "status_warn"


def firmware_status() -> tuple[str, str]:
    """Con la metadata ya bajada (sin red ni root): cuántos equipos tienen firmware nuevo."""
    if not shutil.which("fwupdmgr"):
        return "fwupd is not installed", "status_warn"
    try:
        remotes = json.loads(run(["fwupdmgr", "get-remotes", "--json"]).stdout or "{}").get("Remotes", [])
    except ValueError:
        remotes = []
    # Mtime de los remotes que se bajan (lvfs): -1 = nunca se bajó la metadata
    mtime = max((r.get("Mtime") or -1 for r in remotes if r.get("Enabled") and r.get("Kind") == "download"),
                default=-1)
    if mtime <= 0:
        return "metadata never downloaded · enter to check", "status_warn"
    try:
        devs = [d for d in json.loads(run(["fwupdmgr", "get-updates", "--json"]).stdout or "{}").get("Devices", [])
                if d.get("Releases")]
    except ValueError:
        devs = []
    if devs:
        return f"{len(devs)} update{'s' if len(devs) > 1 else ''}: " + ", ".join(d.get("Name", "?") for d in devs), \
            "status_error"
    return f"✓ up to date · checked {ago(mtime)}", "status_ok"


def parse_updates(out: str, source: str) -> list[dict]:
    """Líneas "pkg viejo -> nuevo [edad]" de checkupdates / yay -Qua."""
    pkgs = []
    for line in out.splitlines():
        m = re.match(r"^(\S+)\s+(\S+)\s+->\s+(\S+)", line)
        if m:
            pkgs.append({"name": m.group(1), "old": m.group(2), "new": m.group(3), "src": source})
    return pkgs


def pending(force: bool = False) -> dict:
    """{time, pkgs, error}; usa la caché si es reciente."""
    try:
        cached = json.loads(CACHE.read_text())
    except (OSError, ValueError):
        cached = None
    if cached and not force and time.time() - cached.get("time", 0) < PENDING_MAX_AGE:
        return cached
    pkgs, error = [], ""
    if shutil.which("checkupdates"):
        r = run(["checkupdates"], timeout=60)
        if r.returncode not in (0, 2):     # 2 = nada pendiente
            error = "checkupdates failed (offline?)"
        pkgs += parse_updates(r.stdout, "repo")
    if shutil.which("yay"):
        pkgs += parse_updates(run(["yay", "-Qua"], timeout=60).stdout, "AUR")
    data = {"time": time.time(), "pkgs": pkgs, "error": error}
    if not error:
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, CACHE)
        except OSError:
            pass   # sin caché se vuelve a consultar la próxima vez
    return data


SIZE_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}


def installed_pkgs() -> list[dict]:
    """Todos los paquetes de `pacman -Qi` (≈0.3 s para ~1200), con lo que muestra Installed."""
    out = run(["pacman", "-Qi"], timeout=60).stdout
    foreign = set(run(["pacman", "-Qmq"]).stdout.split())
    pkgs = []
    for block in out.strip().split("\n\n"):
        f: dict[str, str] = {}
        last = ""
        for line in block.splitlines():
            if line[:1] == " " and last:          # continuación (Optional Deps, listas largas)
                f[last] += " " + line.strip()
                continue
            k, _, v = line.partition(":")
            last = k.strip()
            f[last] = v.strip()
        if "Name" not in f:
            continue
        num, _, unit = f.get("Installed Size", "0 B").partition(" ")
        try:
            size = float(num) * SIZE_UNITS.get(unit, 1)
        except ValueError:
            size = 0
        def lst(key: str) -> list[str]:
            return [] if f.get(key, "None") == "None" else f[key].split()
        pkgs.append({"name": f["Name"], "version": f.get("Version", ""), "desc": f.get("Description", ""),
                     "url": f.get("URL", ""), "size": size, "size_h": f.get("Installed Size", ""),
                     "explicit": f.get("Install Reason", "").startswith("Explicitly"),
                     "date": " ".join(f.get("Install Date", "").split()[1:4]), "depends": lst("Depends On"),
                     "required": lst("Required By"), "src": "AUR" if f["Name"] in foreign else "repo"})
    return pkgs


def last_upgrade() -> Optional[float]:
    """Epoch de la última `pacman -Syu` completa, de pacman.log."""
    last = None
    try:
        with PACMAN_LOG.open(errors="replace") as f:
            for line in f:
                if "starting full system upgrade" in line:
                    last = line
    except OSError:
        return None
    m = re.match(r"^\[([^\]]+)\]", last or "")
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S%z").timestamp() if m else None
    except ValueError:
        return None


def last_snapshot() -> Optional[tuple[str, float]]:
    try:
        names = sorted(d.name for d in SNAP_DIR.iterdir() if d.is_dir())
    except OSError:
        return None
    if not names:
        return None
    try:
        return names[-1], datetime.strptime(names[-1], "%Y-%m-%d_%H-%M-%S").timestamp()
    except ValueError:
        return names[-1], 0


def kernel_status() -> tuple[str, str]:
    running = platform.release()
    if Path(f"/usr/lib/modules/{running}").is_dir():
        return f"✓ {running}", "status_ok"
    return f"✗ running {running}, a newer one is installed: reboot to use it", "status_error"


# ── vista ──

class UpdateView(DView):
    FOCUS = "#update"
    DEFAULT_CSS = css("""
    #upd-status-panel { height: auto; }
    #upd-status { height: auto; }
    #upd-actions-panel { width: 64; }
    #upd-right { width: 1fr; }
    #upd-right > Vertical { height: 1fr; }
    #upd-pending-panel, #upd-inst-panel { height: 1fr; }
    #upd-search { margin-bottom: 1; }
    #upd-info-panel { height: auto; max-height: 14; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False),
        Binding("shift+tab", "cycle(-1)", show=False),
        Binding("r", "refresh", "refresh"),
        Binding("v", "switch", "pending/installed"),
        Binding("slash", "search", "search installed", show=False),
        Binding("x", "remove", "uninstall package", show=False),
        Binding("e", "explicit", "installed by hand only on/off", show=False),
        Binding("s", "sort", "sort by size / name", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="upd-status", show_header=False), title="󰚰  System status", id="upd-status-panel")
        with Horizontal():
            yield Panel(Table(id="update", show_header=False), title="Actions", id="upd-actions-panel")
            with ContentSwitcher(initial="upd-pending-box", id="upd-right"):
                with Vertical(id="upd-pending-box"):
                    yield Panel(Table(id="upd-pending"), title="Pending", id="upd-pending-panel")
                with Vertical(id="upd-inst-box"):
                    yield Panel(Input(placeholder="search name or description…", id="upd-search"),
                                Table(id="upd-inst"), title="Installed", id="upd-inst-panel")
                    yield Panel(Card(id="upd-info"), title="Package", id="upd-info-panel")

    @property
    def TABLES(self) -> list[str]:
        right = "upd-pending" if self.query_one("#upd-right", ContentSwitcher).current == "upd-pending-box" \
            else "upd-inst"
        return ["update", "upd-status", right]

    def on_mount(self) -> None:
        s = self.query_one("#upd-status", Table)
        s.add_column("", key="name", width=14)
        s.add_column("", key="value", width=90)
        a = self.query_one("#update", Table)
        a.add_column("", key="name", width=22)
        a.add_column("", key="desc", width=36)
        rows = []
        for group, items in ACTIONS:
            if rows:
                rows.append((f"gap:{group}", ["", ""]))
            rows.append((f"hdr:{group}", [Text(group.upper(), style=f"bold {THEME['muted']}"), ""]))
            rows += [(mode, [f"{icon}  {name}", Text(desc, style=THEME["muted"])]) for mode, icon, name, desc in items]
        a.set_rows(rows)
        a.first_selectable(0)
        p = self.query_one("#upd-pending", Table)
        p.add_column("Package", key="name", width=28)
        p.add_column("Version", key="ver", width=30)
        p.add_column("From", key="src", width=6)
        i = self.query_one("#upd-inst", Table)
        i.add_column("Package", key="name", width=28)
        i.add_column("Version", key="ver", width=16)
        i.add_column("Size", key="size", width=8)
        i.add_column("", key="kind", width=12)
        self.inst: list[dict] = []
        self.inst_filter, self.only_explicit, self.by_size = "", False, False
        self.status: dict = {"pending": ("checking…", "muted"), "security": ("checking…", "muted"),
                             "firmware": ("checking…", "muted")}
        self.paint_status()
        self.query_one("#upd-actions-panel").border_subtitle = " sudo may ask for your fingerprint "
        self.load_local()
        self.load_pending()
        self.load_security()

    def on_show(self) -> None:
        if self.is_mounted:
            self.load_local()
            self.load_pending()

    # ── carga ──

    @work(thread=True, exclusive=True, group="upd-local")
    def load_local(self) -> None:
        """Lo que se lee del disco (rápido): log de pacman, snapshots, kernel."""
        up, snap, kern = last_upgrade(), last_snapshot(), kernel_status()
        st = {"last": (f"{ago(up)} · {datetime.fromtimestamp(up):%Y-%m-%d %H:%M}" if up else "never (no -Syu in the log)",
                       "status_warn" if not up or time.time() - up > 14 * 86400 else "foreground"),
              "snapshot": ((f"{ago(snap[1])} · {snap[0]}" if snap[1] else snap[0], "foreground") if snap
                           else ("none yet · enter to create one", "status_warn")),
              "kernel": kern}
        self.app.call_from_thread(self.merge_status, st)

    @work(thread=True, exclusive=True, group="upd-pending")
    def load_pending(self, force: bool = False) -> None:
        data = pending(force)
        self.app.call_from_thread(self.show_pending, data)

    @work(thread=True, exclusive=True, group="upd-security")
    def load_security(self) -> None:
        self.app.call_from_thread(self.merge_status, {"security": audit_status(), "firmware": firmware_status()})

    def merge_status(self, st: dict) -> None:
        self.status.update(st)
        self.paint_status()

    def paint_status(self) -> None:
        labels = [("pending", "Pending"), ("last", "Last update"), ("snapshot", "Snapshot"),
                  ("kernel", "Kernel"), ("security", "Security"), ("firmware", "Firmware")]
        rows = []
        for key, label in labels:
            text, level = self.status.get(key, ("…", "muted"))
            rows.append((key, [Text(label, style=THEME["muted"]),
                               Text(text, style=THEME.get(level, THEME["foreground"]))]))
        self.query_one("#upd-status", Table).set_rows(rows)

    def show_pending(self, data: dict) -> None:
        pkgs = sorted(data.get("pkgs", []), key=lambda p: (not IMPORTANT.match(p["name"]), p["src"], p["name"]))
        repo = sum(p["src"] == "repo" for p in pkgs)
        aur = len(pkgs) - repo
        age = ago(data.get("time")) if data.get("time") else ""
        if data.get("error"):
            summary = (data["error"], "status_warn")
        elif pkgs:
            summary = (f"{repo} pacman · {aur} AUR · checked {age} · enter for a full update", "status_warn")
        else:
            summary = (f"✓ everything up to date · checked {age}", "status_ok")
        self.merge_status({"pending": summary})
        primary, muted = THEME["primary"], THEME["muted"]
        self.query_one("#upd-pending", Table).set_rows([
            (f"{p['src']}:{p['name']}", [
                Text(p["name"], style=f"bold {primary}" if IMPORTANT.match(p["name"]) else ""),
                Text.assemble((p["old"], muted), " → ", (p["new"], "bold")),
                Text(p["src"], style=muted)]) for p in pkgs])
        panel = self.query_one("#upd-pending-panel")
        panel.border_title = f" Pending ({len(pkgs)}) " if pkgs else " Pending "
        panel.border_subtitle = " r to check again " if pkgs or data.get("error") else " nothing to update "

    # ── navegación ──

    def focused_table(self) -> str:
        f = self.app.focused
        if isinstance(f, Input):
            return "upd-inst"
        return f.id if isinstance(f, Table) and f.id in self.TABLES else "update"

    def action_cycle(self, step: int) -> None:
        i = self.TABLES.index(self.focused_table())
        self.query_one(f"#{self.TABLES[(i + step) % len(self.TABLES)]}", Table).focus()

    def hints(self) -> list[tuple[str, str]]:
        tid = self.focused_table()
        if tid == "upd-inst":
            return [("/", "search"), ("x", "uninstall"), ("e", "explicit only" if not self.only_explicit else "all"),
                    ("s", "by name" if self.by_size else "by size"), ("v", "pending"), ("tab", "panel"),
                    ("q", "quit")]
        h = [("enter", "run")] if tid != "upd-pending" else []
        return h + [("v", "installed"), ("tab", "panel"), ("r", "check again"), ("q", "quit")]

    def action_refresh(self) -> None:
        self.status.update({"pending": ("checking…", "muted"), "security": ("checking…", "muted")})
        self.paint_status()
        self.load_local()
        self.load_pending(force=True)
        self.load_security()

    # ── installed (estilo pacseek) ──

    def action_switch(self) -> None:
        sw = self.query_one("#upd-right", ContentSwitcher)
        if sw.current == "upd-pending-box":
            sw.current = "upd-inst-box"
            if not self.inst:
                self.query_one("#upd-inst-panel").border_subtitle = " loading… "
                self.load_installed()
            self.query_one("#upd-inst", Table).focus()
        else:
            sw.current = "upd-pending-box"
            self.query_one("#upd-pending", Table).focus()
        self.update_hints()

    @work(thread=True, exclusive=True, group="upd-installed")
    def load_installed(self) -> None:
        pkgs = installed_pkgs()
        self.app.call_from_thread(self.show_installed, pkgs)

    def show_installed(self, pkgs: Optional[list[dict]] = None, top: bool = False) -> None:
        """top=True: el filtro u orden cambió → el cursor va al primer resultado."""
        if pkgs is not None:
            self.inst = pkgs
        q = self.inst_filter.lower()
        rows = [p for p in self.inst if (not self.only_explicit or p["explicit"])
                and (not q or q in p["name"].lower() or q in p["desc"].lower())]
        rows.sort(key=(lambda p: -p["size"]) if self.by_size else (lambda p: p["name"]))
        muted, primary = THEME["muted"], THEME["primary"]
        self.query_one("#upd-inst", Table).set_rows([
            (p["name"], [Text(p["name"], style="bold" if p["explicit"] else ""), Text(p["version"], style=muted),
                         Text(p["size_h"].replace(" ", "").replace("iB", ""), style=muted),
                         Text(("explicit" if p["explicit"] else "dep") + (" AUR" if p["src"] == "AUR" else ""),
                              style=primary if p["src"] == "AUR" else muted)]) for p in rows])
        if top and rows:
            self.query_one("#upd-inst", Table).move_cursor(row=0)
        total = sum(p["size"] for p in rows) / 1024 ** 3
        panel = self.query_one("#upd-inst-panel")
        panel.border_title = f" Installed ({len(rows)}{'' if len(rows) == len(self.inst) else f' of {len(self.inst)}'}) "
        panel.border_subtitle = (f" {total:.1f} GiB · {'explicit only' if self.only_explicit else 'all'} · "
                                 f"by {'size' if self.by_size else 'name'} ")
        self.show_info()

    def selected_pkg(self) -> Optional[dict]:
        key = self.query_one("#upd-inst", Table).selected_key()
        return next((p for p in self.inst if p["name"] == key), None)

    def show_info(self) -> None:
        p, muted = self.selected_pkg(), THEME["muted"]
        if not p:
            self.query_one("#upd-info", Card).update(Text("no package selected", style=muted))
            return
        t = Text()
        t.append(p["name"], style=f"bold {THEME['primary']}")
        t.append(f"  {p['version']}\n", style=muted)
        t.append(p["desc"] + "\n", style="")
        if p["url"] and p["url"] != "None":
            t.append(p["url"] + "\n", style=muted)
        t.append("\n")
        t.append(f"{p['size_h']} · {'explicitly installed' if p['explicit'] else 'installed as a dependency'}"
                 f" · {p['src']} · {p['date']}\n", style=muted)

        def names(label: str, items: list[str]) -> None:
            t.append(f"{label:<13}", style=muted)
            shown = " ".join(items[:14]) + (f" … +{len(items) - 14}" if len(items) > 14 else "")
            t.append((shown or "—") + "\n")

        names("Depends on", [re.split(r"[<>=]", d)[0] for d in p["depends"]])
        names("Required by", p["required"])
        self.query_one("#upd-info", Card).update(t)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "upd-inst":
            self.show_info()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "upd-search":
            self.inst_filter = event.value.strip()
            self.show_installed(top=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "upd-search":
            self.query_one("#upd-inst", Table).focus()

    def in_installed(self) -> bool:
        return self.query_one("#upd-right", ContentSwitcher).current == "upd-inst-box"

    def action_search(self) -> None:
        if self.in_installed():
            self.query_one("#upd-search", Input).focus()

    def action_explicit(self) -> None:
        if self.in_installed():
            self.only_explicit = not self.only_explicit
            self.show_installed(top=True)
            self.update_hints()

    def action_sort(self) -> None:
        if self.in_installed():
            self.by_size = not self.by_size
            self.show_installed(top=True)
            self.update_hints()

    def action_remove(self) -> None:
        if not self.in_installed():
            return
        p = self.selected_pkg()
        if not p:
            return
        # Lo mismo que borraría -Rns (con sus dependencias huérfanas), sin root
        r = run(["pacman", "-Rs", "--print", "--print-format", "%n %v", p["name"]])
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            return self.app.notify_err(msg[-1] if msg else f"{p['name']} can't be removed")
        targets = r.stdout.strip().splitlines()
        warn = ""
        if CRITICAL.match(p["name"]):
            warn = f"\n⚠ {p['name']} is a core package: removing it can leave the system unbootable.\n"
        shown = "\n".join(f"  {x}" for x in targets[:15]) + (f"\n  … +{len(targets) - 15} more"
                                                              if len(targets) > 15 else "")

        def done(yes: bool) -> None:
            if not yes:
                return
            with self.app.suspend():
                os.system("clear")
                print(f"$ sudo pacman -Rns {p['name']}\n")
                rc = subprocess.run(["sudo", "pacman", "-Rns", "--noconfirm", p["name"]]).returncode
                if rc != 0:
                    input("\nFailed. Press enter to go back to Settings...")
            if rc == 0:
                self.app.notify_ok(f"removed {p['name']}" + (f" (+{len(targets) - 1})" if len(targets) > 1 else ""))
            else:
                self.app.notify_err(f"could not remove {p['name']}")
            self.load_installed()
            self.load_pending(force=True)

        self.app.push_screen(ConfirmModal(f"Uninstall {p['name']}",
                                          f"pacman -Rns will remove {len(targets)} package"
                                          f"{'s' if len(targets) != 1 else ''}:\n{shown}\n{warn}"), done)

    # ── acciones ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        if event.data_table.id == "update" and not key.startswith(("hdr:", "gap:")):
            self.run_mode(key)
        elif event.data_table.id == "upd-status" and key in STATUS_ACTION:
            self.run_mode(STATUS_ACTION[key])

    def run_mode(self, mode: str) -> None:
        with self.app.suspend():
            os.system("clear")
            subprocess.run([str(UPDATE_SH), mode])
            input("\nPress enter to go back to Settings...")
        self.app.refresh(layout=True)
        self.load_local()
        self.load_pending(force=mode in ("all", "pacman", "aur", "check"))
        if mode in ("all", "pacman", "aur", "audit", "firmware"):
            self.load_security()
