"""etckeeper — /etc versionado con git, gestionado desde Settings.

- Status: etckeeper instalado, repo inicializado, hook de pacman (commit automático
  antes/después de cada instalación) y timer diario (commitea lo que cambió a mano).
  `enter` sobre una fila instala / inicializa / prende o apaga el timer.
- Changes: archivos de /etc modificados desde el último commit. `enter` muestra el
  diff, `x` descarta el cambio (vuelve el archivo al último commit).
- History: commits. `enter` muestra el detalle (stat + diff).

/etc/.git es root-only (el repo contiene /etc/shadow y otros secretos), así que
leerlo necesita sudo. No se hace polling de pkexec: la vista usa `sudo -n` (solo
funciona con la credencial ya cacheada) y, si no hay, muestra la última foto
guardada en el estado; `u` autentica una vez (sudo -v, en la misma ventana).
Nunca se ofrece un remoto: subir ese repo a GitHub filtraría hashes de contraseñas.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from common import STATE, run, sudo_run
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, Table, TextModal, ago, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

ETC_GIT = Path("/etc/.git")
# Lo que NO debe entrar al primer commit: secretos (claves Wi-Fi en texto plano, claves de
# pacman) y salida regenerada por update-ca-trust (~740 archivos que ensucian cada update).
# etckeeper init deja todo en staging y el hook de pacman commitea solo: se filtra antes.
IGNORE = ["ca-certificates/extracted/", "ssl/certs/", "NetworkManager/system-connections/",
          "pacman.d/gnupg/private-keys-v1.d/"]
CACHE = STATE / "etckeeper.json"
HOOKS = Path("/usr/share/libalpm/hooks")
TIMER = "etckeeper.timer"
TABLES = ["ek-status", "ek-log"]


# ── datos ──

def installed() -> bool:
    return shutil.which("etckeeper") is not None


def initialized() -> bool:
    return ETC_GIT.is_dir()


def hook_present() -> bool:
    return any(HOOKS.glob("*etckeeper*")) if HOOKS.is_dir() else False


def timer_on() -> bool:
    return run(["systemctl", "is-enabled", TIMER]).stdout.strip() == "enabled"


def unlocked() -> bool:
    """sudo sin contraseña ahora mismo (credencial cacheada)."""
    return run(["sudo", "-n", "true"]).returncode == 0


def git(*args: str, timeout: float = 15):
    return run(["sudo", "-n", "git", "-C", "/etc", *args], timeout=timeout)


def snapshot() -> dict:
    """Estado del repo leído con sudo -n: rama, cambios sin commitear y commits."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    changes = []
    for line in git("status", "--porcelain").stdout.splitlines():
        if len(line) > 3:
            path = line[3:].split(" -> ")[-1].strip('"')
            changes.append({"code": line[:2].strip() or "M", "path": path})
    log = []
    for line in git("log", "-n", "200", "--format=%h%x09%at%x09%s").stdout.splitlines():
        h, _, rest = line.partition("\t")
        at, _, msg = rest.partition("\t")
        if h and at.isdigit():
            log.append({"hash": h, "time": int(at), "msg": msg})
    return {"time": time.time(), "branch": branch, "changes": changes, "log": log}


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def save_cache(data: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_name(CACHE.name + ".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(CACHE)
    except OSError:
        pass


CODES = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "??": "new"}


class EtckeeperView(DView):
    FOCUS = "#ek-status"
    BINDINGS = [
        Binding("tab", "cycle(1)", "next panel", show=False),
        Binding("shift+tab", "cycle(-1)", "previous panel", show=False),
        Binding("u", "unlock", "unlock (sudo)"),
        Binding("c", "commit", "commit"),
        Binding("x", "discard", "discard change", show=False),
        Binding("r", "refresh", "refresh", show=False),
    ]
    DEFAULT_CSS = css("""
    EtckeeperView #ek-status-panel { height: auto; max-height: 12; }
    EtckeeperView #ek-log-panel { height: 1fr; }
    """)

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="ek-status", show_header=False), title="󰊢  etckeeper · /etc in git", id="ek-status-panel")
        yield Panel(Table(id="ek-log"), title="Changes & history", id="ek-log-panel")

    def on_mount(self) -> None:
        s = self.query_one("#ek-status", Table)
        s.add_column("", key="name", width=26)
        s.add_column("", key="state", width=26)
        s.add_column("", key="desc", width=70)
        t = self.query_one("#ek-log", Table)
        t.add_column("What", key="what", width=40)
        t.add_column("State", key="state", width=14)
        t.add_column("When", key="when", width=14)
        self.data: dict = load_cache()
        self.live = False
        self.reload()

    def on_show(self) -> None:
        if self.is_mounted:
            self.reload()

    # ── carga ──

    @work(thread=True, exclusive=True, group="ek")
    def reload(self) -> None:
        facts = {"installed": installed(), "init": initialized(), "hook": hook_present(),
                 "timer": timer_on() if installed() else False}
        live = False
        data = self.data
        if facts["installed"] and facts["init"] and unlocked():
            data, live = snapshot(), True
            save_cache(data)
        self.app.call_from_thread(self.show, facts, data, live)

    def show(self, facts: dict, data: dict, live: bool) -> None:
        self.facts, self.data, self.live = facts, data, live
        ok, warn, muted, prim = THEME["status_ok"], THEME["status_warn"], THEME["muted"], THEME["primary"]

        def state(on: bool, yes: str, no: str) -> Text:
            return Text(f"●  {yes}", style=ok) if on else Text(f"○  {no}", style=warn)

        rows = []
        if not facts["installed"]:
            rows.append(("install", ["󰏖  etckeeper", state(False, "", "not installed"),
                                     Text("keeps /etc in git, commits on every pacman transaction · enter to install",
                                          style=muted)]))
        else:
            rows.append(("init", ["󰊢  Repository", state(facts["init"], "initialized", "not initialized"),
                                  Text("git repo at /etc/.git (root only: it holds /etc/shadow)" if facts["init"]
                                       else "enter to run `etckeeper init` + first commit", style=muted)]))
            rows.append(("hook", ["󰏗  pacman hook", state(facts["hook"], "active", "missing"),
                                  Text("auto-commit before and after every install/upgrade/remove"
                                       if facts["hook"] else "the package ships it; reinstall etckeeper if missing",
                                       style=muted)]))
            rows.append(("timer", ["󰔟  Daily auto-commit", state(facts["timer"], "daily", "off"),
                                   Text("commits by-hand edits once a day · enter to turn on/off", style=muted)]))
            if facts["init"]:
                n = len(data.get("changes", []))
                rows.append(("changes", ["󰈙  Uncommitted changes",
                                         Text("?  locked", style=muted) if not (self.live or data)
                                         else Text(f"✗  {n} files", style=warn) if n else Text("✓  none", style=ok),
                                         Text(("as of " + ago(data["time"])) if data.get("time") and not self.live
                                              else "live" if self.live else "unlock to read the repo (u)",
                                              style=muted)]))
        self.query_one("#ek-status", Table).set_rows(rows)
        self.query_one("#ek-status-panel").border_subtitle = (
            "" if not (facts["installed"] and facts["init"]) else
            " live " if live else " locked · showing last snapshot · u to unlock " if data else " locked · u to unlock ")

        lrows: list = []
        if facts["init"]:
            changes = data.get("changes", [])
            lrows.append(("hdr:changes", [Text("UNCOMMITTED", style=f"bold {prim}"), Text(""), Text("")]))
            if changes:
                for c in changes:
                    name = c["path"] if len(c["path"]) <= 38 else "…" + c["path"][-37:]
                    lrows.append((f"chg:{c['code']}:{c['path']}", [Text(name), Text(CODES.get(c["code"], c["code"]),
                                                                                    style=warn), Text("now", style=muted)]))
            else:
                lrows.append(("hdr:nochg", [Text("nothing to commit", style=muted), Text(""), Text("")]))
            lrows.append(("gap:1", [Text(""), Text(""), Text("")]))
            lrows.append(("hdr:history", [Text(f"HISTORY · {data.get('branch') or '—'}", style=f"bold {prim}"),
                                          Text(""), Text("")]))
            for c in data.get("log", []):
                msg = c["msg"] if len(c["msg"]) <= 38 else c["msg"][:37] + "…"
                lrows.append((f"c:{c['hash']}", [Text(msg), Text(c["hash"], style=muted), Text(ago(c["time"]), style=muted)]))
            if not data.get("log"):
                lrows.append(("hdr:nolog", [Text("no history loaded · u to unlock", style=muted), Text(""), Text("")]))
        else:
            lrows.append(("hdr:off", [Text(("install etckeeper first" if not facts["installed"] else "initialize the repository to track /etc"), style=muted), Text(""), Text("")]))
        t = self.query_one("#ek-log", Table)
        if t.set_rows(lrows):
            t.first_selectable()
        self.query_one("#ek-log-panel").border_subtitle = \
            " enter diff · c commit · x discard change " if facts["init"] else ""

    # ── navegación ──

    def focused_table(self) -> str:
        f = self.app.focused
        return f.id if f is not None and f.id in TABLES else ""

    def action_cycle(self, step: int) -> None:
        i = TABLES.index(self.focused_table()) if self.focused_table() else 0
        self.query_one(f"#{TABLES[(i + step) % len(TABLES)]}", Table).focus()
        self.update_hints()

    def hints(self) -> list[tuple[str, str]]:
        if self.focused_table() == "ek-log":
            return [("enter", "diff"), ("c", "commit"), ("x", "discard change"), ("u", "unlock"), ("tab", "panel"),
                    ("q", "quit")]
        return [("enter", "install · init · timer"), ("c", "commit"), ("u", "unlock"), ("r", "refresh"),
                ("tab", "panel"), ("q", "quit")]

    # ── acciones ──

    def action_refresh(self) -> None:
        self.reload()

    def action_unlock(self) -> None:
        if not installed() or not initialized():
            self.app.notify_err("etckeeper is not set up yet")
            return
        if sudo_run(self.app, [["-v"]], "Authenticating to read /etc/.git"):
            self.reload()

    def action_commit(self) -> None:
        if not (installed() and initialized()):
            self.app.notify_err("etckeeper is not set up yet")
            return

        def done(v: dict | None) -> None:
            if v and v["msg"].strip():
                if sudo_run(self.app, [["etckeeper", "commit", v["msg"].strip()]], "Committing /etc"):
                    self.app.notify_ok("committed /etc")
                self.reload()

        self.app.push_screen(FormModal("Commit /etc", [Field("msg", "Message", placeholder="e.g. tweak sshd config")],
                                       validate=lambda v: None if v["msg"].strip() else "Write a message"), done)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        if event.data_table.id == "ek-status":
            self.status_action(key)
        elif key.startswith("chg:"):
            self.show_change(key)
        elif key.startswith("c:"):
            self.show_commit(key[2:])

    @staticmethod
    def init_commands() -> list[list[str]]:
        """init → filtrar secretos (ignore + sacarlos del staging) → identidad local si falta → commit."""
        ignore = "\\n".join(["# Locales: secretos y salida regenerada", *IGNORE])
        ident = ("git -C /etc config user.name >/dev/null || git -C /etc config user.name etckeeper; "
                 "git -C /etc config user.email >/dev/null || git -C /etc config user.email etckeeper@localhost")
        return [["etckeeper", "init"],
                ["sh", "-c", f"printf '\\n{ignore}\\n' >> /etc/.gitignore"],
                ["git", "-C", "/etc", "rm", "-r", "--cached", "-q", "--ignore-unmatch", *IGNORE],
                ["sh", "-c", ident],
                ["etckeeper", "commit", "Initial commit"]]

    def status_action(self, key: str) -> None:
        if key == "install":
            if sudo_run(self.app, [["pacman", "-S", "--needed", "etckeeper"]], "Installing etckeeper"):
                self.app.notify_ok("etckeeper installed")
            self.reload()
        elif key == "init":
            if initialized():
                return

            def done(yes: bool) -> None:
                if yes and sudo_run(self.app, self.init_commands(), "Initializing /etc as a git repo"):
                    self.app.notify_ok("/etc is now tracked")
                    self.reload()

            self.app.push_screen(ConfirmModal(
                "Initialize /etc", "Create /etc/.git (root only) and make the first commit?\n"
                                   "Wi-Fi passwords, pacman keys and regenerated certificates are left out.\n"
                                   "Nothing is uploaded anywhere. Files in /etc are not modified."), done)
        elif key == "timer":
            on = timer_on()
            cmd = ["systemctl", "disable" if on else "enable", "--now", TIMER]
            if sudo_run(self.app, [cmd], f"{'Disabling' if on else 'Enabling'} {TIMER}"):
                self.app.notify_ok(f"daily auto-commit {'off' if on else 'on'}")
            self.reload()

    @work(thread=True, exclusive=True, group="ek-diff")
    def show_change(self, key: str) -> None:
        _, code, path = key.split(":", 2)
        if code == "??":
            out = f"{path} is new and not tracked yet.\nIt will be added by the next commit."
        else:
            r = git("diff", "HEAD", "--", path)
            out = r.stdout or r.stderr or "(no diff — locked? press u)"
        self.app.call_from_thread(self.app.push_screen, TextModal(f"/etc/{path}", out, end=False))

    @work(thread=True, exclusive=True, group="ek-diff")
    def show_commit(self, h: str) -> None:
        r = git("show", "--stat", "--patch", "--format=%h  %an  %ad%n%n%s%n%b", "--date=format:%Y-%m-%d %H:%M", h)
        self.app.call_from_thread(self.app.push_screen,
                                  TextModal(f"commit {h}", r.stdout or r.stderr or "(locked? press u)", end=False))

    def action_discard(self) -> None:
        if self.focused_table() != "ek-log":
            return
        key = self.query_one("#ek-log", Table).selected_key() or ""
        if not key.startswith("chg:"):
            return
        _, code, path = key.split(":", 2)
        if code == "??":
            self.app.notify_err("Untracked file: nothing to restore (delete it by hand if you want)")
            return

        def done(yes: bool) -> None:
            if yes:
                if sudo_run(self.app, [["git", "-C", "/etc", "checkout", "HEAD", "--", path]], f"Restoring /etc/{path}"):
                    self.app.notify_ok(f"restored /etc/{path}")
                self.reload()

        self.app.push_screen(ConfirmModal(
            "Discard change", f"Overwrite /etc/{path} with the last committed version?\n"
                              "The change you made by hand is lost (unless it is in an older commit)."), done)
