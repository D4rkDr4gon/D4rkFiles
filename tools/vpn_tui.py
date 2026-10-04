#!/usr/bin/env python3
"""
vpn_tui.py — TUI para gestionar VPN vía NetworkManager.

No trae ningún perfil ni proveedor configurado: muestra las conexiones VPN que
YA existen en NetworkManager, separadas en tres paneles, y te deja importar las
tuyas. Cada uno usa el tipo que prefiera; los paneles sin perfiles quedan vacíos.

  NetworkManager  otras VPN de NM (OpenConnect, L2TP, vpnc, strongSwan, PPTP…):
                    se crean con nm-connection-editor y se conectan en la
                    terminal (`nmcli --ask`), porque suelen pedir contraseña u OTP
  WireGuard       .conf de cualquier proveedor (wg-quick)
  OpenVPN         .ovpn (plugin networkmanager-openvpn); si el perfil usa
                    auth-user-pass pide usuario y contraseña
  Tailscale       opcional, solo si el paquete está instalado: estado y equipos
                    de `tailscale status --json`. La primera vez (n) habilita
                    tailscaled, deja al usuario como operator (up/down/exit node
                    sin sudo) y hace el login (URL en la terminal). tailscaled
                    recuerda si quedó arriba o abajo: si se baja, no vuelve solo.

Atajos: tab cambia de panel · enter conecta / desconecta (o importa si la fila
es un archivo todavía no importado; en Tailscale: up/down de este equipo, usar
otro de exit node o copiar su IP) · n importa un archivo (o abre
nm-connection-editor en NetworkManager; en Tailscale, setup/login) · d elimina
el perfil (en Tailscale, cierra la sesión) · r refresca. El refresco corre en
un worker (nmcli y tailscale no traban la interfaz).

Los archivos de ~/.config/dotfiles/vpn/ (*.conf -> WireGuard, *.ovpn ->
OpenVPN) que todavía no están en NetworkManager aparecen en su panel como
"not imported". También sirve `nmcli connection import type wireguard file
<archivo>`.

Modo rápido para waybar (sin Textual):

    vpn_tui.py --waybar-status

Imprime una línea JSON {"text", "tooltip", "class"} y sale. class:
  "connected" | "disconnected" | "disabled" (sin ningún perfil VPN configurado).

Se abre desde el módulo VPN de waybar (ventana flotante de kitty) y como
sección VPN de Settings (view_class()). Estilo común: tools/dtui.py; textos
visibles en inglés.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
IMPORT_DIR = CONFIG_HOME / "dotfiles" / "vpn"
IMPORT_KINDS = {".conf": "wireguard", ".ovpn": "openvpn"}
KINDS = ["nm", "wireguard", "openvpn"]      # orden de los paneles
ICON_ON, ICON_OFF = "󰦝", "󰦞"

_UNESCAPED_COLON = re.compile(r"(?<!\\):")
_VALID_IFNAME = re.compile(r"^[A-Za-z0-9_-]{1,15}$")  # IFNAMSIZ = 16 con el nul


# ── NetworkManager ──────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


@dataclass
class Conn:
    name: str
    kind: str                    # "nm" | "wireguard" | "openvpn"
    active: bool
    imported: bool = True        # False = archivo de IMPORT_DIR sin importar
    plugin: str = ""             # vpn.service-type abreviado (openconnect, l2tp…)
    path: Optional[Path] = None  # archivo fuente en IMPORT_DIR, si hay


def _split_terse(line: str) -> list[str]:
    """`nmcli -t` separa con ':' y escapa los ':' internos como '\\:'."""
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in _UNESCAPED_COLON.split(line)]


def _service_type(name: str) -> str:
    """Plugin de una conexión tipo vpn: `org.freedesktop.NetworkManager.openvpn` -> `openvpn`."""
    r = _run(["nmcli", "-g", "vpn.service-type", "connection", "show", "id", name])
    return r.stdout.strip().rsplit(".", 1)[-1]


def nm_conns() -> list[Conn]:
    """Conexiones VPN de NetworkManager. `connection show` solo dice TYPE=vpn:
    el plugin se consulta por conexión para separar OpenVPN del resto."""
    r = _run(["nmcli", "-t", "-f", "NAME,TYPE,ACTIVE", "connection", "show"])
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        name, ctype, active = parts[0], parts[1], parts[2] == "yes"
        if ctype == "wireguard":
            out.append(Conn(name, "wireguard", active))
        elif ctype == "vpn":
            plugin = _service_type(name)
            out.append(Conn(name, "openvpn" if plugin == "openvpn" else "nm", active, plugin=plugin))
    return out


def list_conns() -> list[Conn]:
    """Conexiones de NM + archivos de IMPORT_DIR que todavía no están importados."""
    conns = nm_conns()
    have = {c.name for c in conns}
    try:
        for p in sorted(IMPORT_DIR.iterdir()):
            kind = IMPORT_KINDS.get(p.suffix.lower())
            if not kind:
                continue
            if p.stem in have:
                for c in conns:
                    if c.name == p.stem:
                        c.path = p
            else:
                conns.append(Conn(p.stem, kind, False, imported=False, path=p))
    except OSError:
        pass
    return sorted(conns, key=lambda c: c.name.lower())


def no_autoconnect(name: str) -> None:
    """NM importa los .conf/.ovpn con autoconnect=yes y levanta solas todas las VPN al
    arrancar o al cambiar de red (varias a la vez): acá cada VPN se conecta a mano."""
    _run(["nmcli", "connection", "modify", "id", name, "connection.autoconnect", "no"])


def disable_autoconnect() -> None:
    """Pasada al abrir la TUI: apaga el autoconnect de toda VPN de NM que lo tenga prendido,
    incluidas las importadas por fuera. No desconecta nada: solo el arranque automático."""
    r = _run(["nmcli", "-t", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"])
    for line in r.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) >= 3 and parts[1] in ("wireguard", "vpn") and parts[2] == "yes":
            no_autoconnect(parts[0])


def import_file(path: Path) -> subprocess.CompletedProcess:
    r = _import_file(path)
    if r.returncode == 0:
        no_autoconnect(path.stem)
    return r


def _import_file(path: Path) -> subprocess.CompletedProcess:
    """Importa un .conf/.ovpn. Para WireGuard, NetworkManager usa el nombre del archivo como
    nombre de interfaz (máx. 15 caracteres); si es más largo se importa una copia con nombre
    corto y se renombra la conexión (connection.id admite cualquier largo). OpenVPN copia
    los certificados embebidos a ~/.local/share/networkmanager-openvpn/."""
    kind = IMPORT_KINDS[path.suffix.lower()]
    if kind != "wireguard" or _VALID_IFNAME.match(path.stem):
        return _run(["nmcli", "connection", "import", "type", kind, "file", str(path)], timeout=20)
    try:
        data = path.read_bytes()
    except OSError as exc:
        return subprocess.CompletedProcess(["nmcli"], 1, "", f"could not read {path}: {exc}")
    fd, tmp = tempfile.mkstemp(prefix="wgimp", suffix=".conf")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        r = _run(["nmcli", "connection", "import", "type", "wireguard", "file", str(tmp_path)], timeout=20)
        if r.returncode != 0:
            return r
        rn = _run(["nmcli", "connection", "modify", tmp_path.stem, "connection.id", path.stem])
        return rn if rn.returncode != 0 else r
    finally:
        tmp_path.unlink(missing_ok=True)


def openvpn_auth(name: str) -> tuple[bool, str]:
    """(pide_contraseña, usuario_guardado) según vpn.data. connection-type
    `password`/`password-tls` = .ovpn con auth-user-pass; `tls` = solo certificados."""
    r = _run(["nmcli", "-g", "vpn.data", "connection", "show", "id", name])
    data = {}
    for item in r.stdout.strip().split(","):
        k, _, v = item.partition("=")
        data[k.strip()] = v.strip()
    return data.get("connection-type", "tls").startswith("password"), data.get("username", "")


def openvpn_up(name: str, user: str = "", password: str = "") -> subprocess.CompletedProcess:
    """Conecta un perfil OpenVPN. El usuario queda guardado en la conexión; la contraseña
    va por un passwd-file temporal (0600) que se borra al terminar: NM no la persiste."""
    if user:
        r = _run(["nmcli", "connection", "modify", "id", name, "+vpn.data", f"username={user}"])
        if r.returncode != 0:
            return r
    if not password:
        return _run(["nmcli", "connection", "up", "id", name], 40)
    fd, tmp = tempfile.mkstemp(prefix="ovpn-", dir=os.environ.get("XDG_RUNTIME_DIR") or None)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(f"vpn.secrets.password:{password}\n")
        return _run(["nmcli", "connection", "up", "id", name, "passwd-file", tmp], 40)
    finally:
        Path(tmp).unlink(missing_ok=True)


# ── Tailscale ──

def tailscale_installed() -> bool:
    return bool(shutil.which("tailscale"))


def tailscale_status() -> Optional[dict]:
    """`tailscale status --json`, o None si no está instalado o tailscaled no corre."""
    if not tailscale_installed():
        return None
    r = _run(["tailscale", "status", "--json"], timeout=4)
    try:
        st = json.loads(r.stdout)
    except ValueError:
        return None
    return st if isinstance(st, dict) and st.get("BackendState") else None


def tailscale_operator() -> bool:
    """Si el usuario es operator de tailscaled (up/down/set sin sudo)."""
    try:
        prefs = json.loads(_run(["tailscale", "debug", "prefs"], timeout=4).stdout or "{}")
    except ValueError:
        return False
    return prefs.get("OperatorUser") == os.environ.get("USER")


def tailscale_peers(st: dict) -> list[dict]:
    peers = []
    for p in (st.get("Peer") or {}).values():
        peers.append({"name": p.get("HostName") or p.get("DNSName", "?").split(".")[0],
                      "ip": (p.get("TailscaleIPs") or ["—"])[0], "os": p.get("OS", ""),
                      "online": bool(p.get("Online")), "exit_option": bool(p.get("ExitNodeOption")),
                      "exit": bool(p.get("ExitNode"))})
    return sorted(peers, key=lambda p: (not p["online"], p["name"].lower()))


def tailscale_cmd(*args: str) -> subprocess.CompletedProcess:
    return _run(["tailscale", *args], timeout=20)


def waybar_status_json() -> str:
    conns = nm_conns()
    active = [c for c in conns if c.active]
    ts = tailscale_status()
    if ts and ts.get("BackendState") == "Running":
        exit_node = next((p["name"] for p in tailscale_peers(ts) if p["exit"]), None)
        active = active + [Conn(name="Tailscale" + (f" (exit node {exit_node})" if exit_node else ""),
                                kind="tailscale", active=True)]
    if not conns and not active:
        text, cls = ICON_OFF, "disabled"
        tip = "No VPN profiles yet\nClick to add one"
    elif active:
        text, cls = ICON_ON, "connected"
        tip = "VPN: " + ", ".join(c.name for c in active) + "\nClick to manage VPNs"
    else:
        text, cls = ICON_OFF, "disconnected"
        tip = f"VPN disconnected ({len(conns)} profile{'s' if len(conns) != 1 else ''})\nClick to manage VPNs"
    return json.dumps({"text": text, "tooltip": tip, "class": cls}, ensure_ascii=False)


def main_waybar_status() -> None:
    try:
        print(waybar_status_json())
    except Exception as exc:  # nunca colgar el polling de waybar
        print(json.dumps({"text": ICON_OFF, "tooltip": f"vpn-tui error: {exc}", "class": "disconnected"}))
    sys.exit(0)


# ── TUI (Textual, se importa solo si hace falta) ────────────────────────
_VIEW_CLS = None


def view_class():
    """Clase de la vista de VPN (DView). Se arma acá y no arriba para que
    --waybar-status siga sin cargar Textual; Settings la importa con esto."""
    global _VIEW_CLS
    if _VIEW_CLS is not None:
        return _VIEW_CLS

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dtui import THEME as T, ConfirmModal, DView, Field, FormModal, Panel, Table, css
    from rich.text import Text
    from textual import work
    from textual.app import ComposeResult
    from textual.binding import Binding

    TITLES = {"nm": "󰛳  NetworkManager", "wireguard": "󰌆  WireGuard", "openvpn": "󰒃  OpenVPN"}
    TABLES = list(KINDS) + ["ts"]   # + panel Tailscale
    EMPTY = {"nm": " none: press n to create one ",
             "wireguard": " none: press n to import a .conf ",
             "openvpn": " none: press n to import a .ovpn "}

    class VpnView(DView):
        FOCUS = "#wireguard"
        DEFAULT_CSS = css("""
        VpnView .panel { height: auto; max-height: 25%%; }
        VpnView DataTable { height: auto; max-height: 100%%; }
        """)
        BINDINGS = [
            Binding("tab", "cycle(1)", show=False),
            Binding("shift+tab", "cycle(-1)", show=False),
            Binding("n", "new", "new"),
            Binding("d", "delete", "delete"),
            Binding("r", "reload", "refresh"),
            Binding("j", "down", show=False),
            Binding("k", "up", show=False),
        ]

        def compose(self) -> ComposeResult:
            for kind in KINDS:
                yield Panel(Table(id=kind), title=TITLES[kind], id=f"{kind}-panel")
            yield Panel(Table(id="ts"), title="󰖂  Tailscale", id="ts-panel")

        def on_mount(self) -> None:
            for kind in KINDS:
                t = self.query_one(f"#{kind}", Table)
                t.add_column("Name", key="name", width=28)
                t.add_column("State", key="state", width=18)
                t.add_column("Type" if kind == "nm" else "Source", key="src", width=30)
            ts = self.query_one("#ts", Table)
            ts.add_column("Device", key="name", width=28)
            ts.add_column("State", key="state", width=18)
            ts.add_column("Details", key="info", width=44)
            self.busy = ""
            self._loading = False
            disable_autoconnect()   # cada VPN se conecta a mano
            self.action_reload()
            self.set_interval(5.0, self.tick)

        def tick(self) -> None:
            if self.visible_now:
                self.action_reload()

        def fill(self, tid: str, rows: list) -> None:
            # Solo redibuja si cambió (sin parpadeo, conserva la selección)
            self.query_one(f"#{tid}", Table).set_rows(rows)

        @staticmethod
        def state(c: Conn) -> Text:
            if not c.imported:
                return Text("◌  not imported", style=T["status_warn"])
            if c.active:
                return Text("●  connected", style=f"bold {T['status_ok']}")
            return Text("○  disconnected", style=T["muted"])

        def action_reload(self) -> None:
            # nmcli y tailscale tardan: se consultan en un worker y acá solo se pinta
            if not self._loading:
                self._loading = True
                self.gather()

        @work(thread=True, exclusive=True, group="vpn")
        def gather(self) -> None:
            try:
                data = (list_conns(), tailscale_installed(), tailscale_status())
            finally:
                self.app.call_from_thread(setattr, self, "_loading", False)
            self.app.call_from_thread(self.paint, *data)

        def paint(self, conns: list, ts_installed: bool, ts: Optional[dict]) -> None:
            home = str(Path.home())
            for kind in KINDS:
                mine = [c for c in conns if c.kind == kind]
                self.fill(kind, [(c.name, [c.name, self.state(c), Text(
                    c.plugin if kind == "nm" else str(c.path).replace(home, "~") if c.path else "—",
                    style=T["muted"])]) for c in mine])
                active = [c.name for c in mine if c.active]
                panel = self.query_one(f"#{kind}-panel")
                panel.border_subtitle = (
                    f" connected: {', '.join(active)} " if active else
                    EMPTY[kind] if not mine else " disconnected ")
            self.refresh_tailscale(ts_installed, ts)
            if self.busy:
                self.query_one(f"#{self.focused_kind()}-panel").border_subtitle = f" {self.busy} "
            self.update_hints()

        def refresh_tailscale(self, installed: bool, st: Optional[dict]) -> None:
            panel, muted = self.query_one("#ts-panel"), T["muted"]
            if not installed:
                self.fill("ts", [("ts:self", ["Tailscale", Text("○  not installed", style=muted),
                                              Text("sudo pacman -S tailscale, then n here", style=muted)])])
                panel.border_subtitle = " optional "
                return
            if st is None:
                self.fill("ts", [("ts:self", ["Tailscale", Text("○  daemon off", style=muted),
                                              Text("n to set up (sudo, once)", style=T["status_warn"])])])
                panel.border_subtitle = " tailscaled is not running "
                return
            state = st.get("BackendState", "")
            me = st.get("Self") or {}
            ip = (me.get("TailscaleIPs") or [""])[0]
            tailnet = (st.get("CurrentTailnet") or {}).get("Name", "")
            if state == "Running":
                cell = Text("●  connected", style=f"bold {T['status_ok']}")
            elif state in ("NeedsLogin", "NoState"):
                cell = Text("✗  logged out", style=T["status_warn"])
            elif state == "NeedsMachineAuth":
                cell = Text("◌  awaiting approval", style=T["status_warn"])
            else:
                cell = Text("○  disconnected", style=muted)
            rows = [("ts:self", [f"{me.get('HostName') or 'this device'} (this)", cell,
                                 Text(" · ".join(x for x in (ip, tailnet) if x) or "n to log in", style=muted)])]
            if state == "Running":
                for p in tailscale_peers(st):
                    rows.append((f"ts:peer:{p['ip']}", [
                        p["name"],
                        Text("●  exit node", style=f"bold {T['status_ok']}") if p["exit"]
                        else Text("●  online", style=T["status_ok"]) if p["online"] else Text("○  offline", style=muted),
                        Text(f"{p['ip']} · {p['os']}{' · exit node' if p['exit_option'] else ''}", style=muted)]))
            self.fill("ts", rows)
            panel.border_subtitle = (f" {tailnet} " if state == "Running" else
                                     " n to log in " if state == "NeedsLogin" else " disconnected ")

        def focused_kind(self) -> str:
            f = self.app.focused
            return f.id if isinstance(f, Table) and f.id in TABLES else "wireguard"

        def hints(self) -> list[tuple[str, str]]:
            kind = self.focused_kind()
            if kind == "ts":
                return [("enter", "up/down · exit node · copy IP"), ("n", "set up / log in"), ("d", "log out"),
                        ("tab", "panel"), ("r", "refresh"), ("q", "quit")]
            new = {"nm": "new (editor)", "wireguard": "import .conf", "openvpn": "import .ovpn"}
            return [("enter", "connect/disconnect"), ("n", new[kind]), ("d", "delete"),
                    ("tab", "panel"), ("r", "refresh"), ("q", "quit")]

        def action_cycle(self, step: int) -> None:
            i = TABLES.index(self.focused_kind())
            self.query_one(f"#{TABLES[(i + step) % len(TABLES)]}", Table).focus()

        def action_down(self) -> None:
            if isinstance(self.app.focused, Table):
                self.app.focused.action_cursor_down()

        def action_up(self) -> None:
            if isinstance(self.app.focused, Table):
                self.app.focused.action_cursor_up()

        def say(self, r: subprocess.CompletedProcess, ok_msg: str) -> None:
            if r.returncode == 0:
                self.app.notify_ok(ok_msg)
            else:
                msg = ((getattr(r, "stderr", "") or getattr(r, "stdout", "") or "").strip().splitlines() or
                       ["failed (see nmcli)"])
                self.app.notify_err(msg[-1])

        async def run_busy(self, label: str, fn, *args) -> subprocess.CompletedProcess:
            self.busy = label
            self.action_reload()
            r = await asyncio.to_thread(fn, *args)
            self.busy = ""
            return r

        def find(self, name: str) -> Optional[Conn]:
            return next((c for c in list_conns() if c.name == name), None)

        async def on_data_table_row_selected(self, event: Table.RowSelected) -> None:
            if event.data_table.id == "ts" and event.row_key.value:
                self.select_tailscale(str(event.row_key.value))
            elif event.data_table.id in KINDS and event.row_key.value:
                await self.toggle(str(event.row_key.value))

        async def import_path(self, path: Path) -> None:
            r = await self.run_busy(f"importing {path.name}…", import_file, path)
            self.say(r, f"{path.stem} imported")
            self.action_reload()

        async def toggle(self, name: str) -> None:
            conn = self.find(name)
            if conn is None:
                return
            if not conn.imported:
                return await self.import_path(conn.path)
            if conn.active:
                r = await self.run_busy(f"disconnecting {name}…", _run,
                                        ["nmcli", "connection", "down", "id", name], 20)
                ok = f"{name} disconnected"
            elif conn.kind == "nm":
                # Puede pedir contraseña/OTP: se conecta en la terminal.
                with self.app.suspend():
                    r = subprocess.run(["nmcli", "--ask", "connection", "up", "id", name])
                ok = f"{name} connected"
            elif conn.kind == "openvpn" and openvpn_auth(name)[0]:
                return self.ask_openvpn(name)
            else:
                r = await self.run_busy(f"connecting {name}…", _run,
                                        ["nmcli", "connection", "up", "id", name], 40)
                ok = f"{name} connected"
            self.say(r, ok)
            self.action_reload()

        def ask_openvpn(self, name: str) -> None:
            user = openvpn_auth(name)[1]

            async def done(v: Optional[dict]) -> None:
                if v is None:
                    return
                r = await self.run_busy(f"connecting {name}…", openvpn_up, name,
                                        v["user"].strip(), v["pass"])
                self.say(r, f"{name} connected")
                self.action_reload()

            self.app.push_screen(FormModal(f"Connect · {name}",
                                           [Field("user", "User", user),
                                            Field("pass", "Password", password=True)],
                                           hint="the password is not stored by NetworkManager",
                                           enter_advances=True, focus="pass" if user else "user"),
                                 lambda v: self.app.run_worker(done(v)))

        def action_new(self) -> None:
            kind = self.focused_kind()
            if kind == "ts":
                return self.setup_tailscale()
            if kind == "nm":
                # OpenConnect, L2TP, vpnc…: cada plugin tiene su propio formulario
                if shutil.which("nm-connection-editor"):
                    subprocess.Popen(["nm-connection-editor", "--create", "--type=vpn"],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                    return self.app.notify_ok("nm-connection-editor opened")
                return self.app.notify_err("install nm-connection-editor (or use nmcli connection add type vpn)")
            ext = ".conf" if kind == "wireguard" else ".ovpn"

            def check(v: dict) -> Optional[str]:
                p = Path(v["path"]).expanduser()
                if not p.is_file():
                    return f"File not found: {v['path']}"
                if p.suffix.lower() != ext:
                    return f"Expected a {ext} file"
                if p.stem in {c.name for c in nm_conns()}:
                    return f"'{p.stem}' is already imported"
                return None

            def done(v: Optional[dict]) -> None:
                if v:
                    self.app.run_worker(self.import_path(Path(v["path"]).expanduser()))

            self.app.push_screen(FormModal(f"Import {TITLES[kind].split()[-1]} profile",
                                           [Field("path", f"{ext} file", f"{IMPORT_DIR}/", files=True)],
                                           hint=f"Any path works; files in {IMPORT_DIR}/\n"
                                                "also show up here before importing.",
                                           validate=check), done)

        # ── Tailscale ──

        def ts_sudo(self, cmds: list[list[str]], title: str) -> None:
            """Corre comandos en la terminal (sudo y el login piden interacción)."""
            with self.app.suspend():
                os.system("clear")
                print(f"== {title} ==\n")
                for cmd in cmds:
                    print("$ " + " ".join(cmd))
                    if subprocess.run(cmd).returncode != 0:
                        input("\nFailed. Press enter to go back...")
                        break
                else:
                    time.sleep(0.5)
            self.action_reload()

        def ts_run(self, ok_msg: str, *args: str) -> None:
            """tailscale como usuario si es operator; si no, con sudo en la terminal."""
            if tailscale_operator():
                r = tailscale_cmd(*args)
                self.say(r, ok_msg)
                return self.action_reload()
            self.ts_sudo([["sudo", "tailscale", *args]], f"tailscale {' '.join(args)}")

        def setup_tailscale(self) -> None:
            if not tailscale_installed():
                return self.app.notify_err("tailscale is not installed: sudo pacman -S tailscale")
            st = tailscale_status()
            user = os.environ.get("USER", "")
            cmds = []
            if st is None:
                cmds.append(["sudo", "systemctl", "enable", "--now", "tailscaled"])
            if st is None or not tailscale_operator():
                cmds.append(["sudo", "tailscale", "set", f"--operator={user}"])
            if st is None or st.get("BackendState") != "Running":
                # sin flags: no pisa prefs (exit node, operator); si falta login,
                # imprime la URL y espera a que se apruebe
                cmds.append(["tailscale", "up"])
            if not cmds:
                return self.app.notify_ok("Tailscale is already set up and connected")
            self.ts_sudo(cmds, "Tailscale setup (open the login URL when it shows up)")

        def select_tailscale(self, key: str) -> None:
            if not tailscale_installed():
                return self.app.notify_err("tailscale is not installed: sudo pacman -S tailscale")
            st = tailscale_status()
            if st is None or st.get("BackendState") in ("NeedsLogin", "NoState"):
                return self.setup_tailscale()
            if key == "ts:self":
                if st.get("BackendState") == "Running":
                    return self.ts_run("Tailscale disconnected", "down")
                return self.ts_run("Tailscale connected", "up")
            ip = key.split(":", 2)[2]
            peer = next((p for p in tailscale_peers(st) if p["ip"] == ip), None)
            if peer is None:
                return
            if peer["exit"]:
                return self.ts_run("exit node off", "set", "--exit-node=")
            if peer["exit_option"]:
                return self.app.push_screen(ConfirmModal(
                    "Use exit node", f"Route all your traffic through {peer['name']}?\n"
                    "LAN access is kept."),
                    lambda yes: yes and self.ts_run(f"exit node: {peer['name']}", "set",
                                                    f"--exit-node={ip}", "--exit-node-allow-lan-access"))
            if _run(["wl-copy", ip]).returncode == 0:
                self.app.notify_ok(f"copied {ip} ({peer['name']})")

        def logout_tailscale(self) -> None:
            st = tailscale_status()
            if st is None or st.get("BackendState") in ("NeedsLogin", "NoState"):
                return self.app.notify_err("Tailscale is not logged in")
            self.app.push_screen(ConfirmModal("Log out of Tailscale",
                                              "Log this device out of the tailnet?\n"
                                              "You'll need to log in again (n) to reconnect."),
                                 lambda yes: yes and self.ts_run("logged out of Tailscale", "logout"))


        def action_delete(self) -> None:
            if self.focused_kind() == "ts":
                return self.logout_tailscale()
            t = self.query_one(f"#{self.focused_kind()}", Table)
            name = t.selected_key()
            conn = self.find(name) if name else None
            if conn is None or not conn.imported:
                return self.app.notify_err("nothing to delete: the profile is not imported")

            def done(yes: bool) -> None:
                if yes:
                    if conn.active:
                        _run(["nmcli", "connection", "down", "id", name], 15)
                    self.say(_run(["nmcli", "connection", "delete", "id", name]), f"{name} deleted")
                    self.action_reload()

            self.app.push_screen(ConfirmModal("Delete profile",
                                              f"Delete “{name}” from NetworkManager?\n"
                                              "The source file (if any) is kept."), done)

    _VIEW_CLS = VpnView
    return VpnView


def main() -> None:
    if "--waybar-status" in sys.argv:
        main_waybar_status()
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return
    cls = view_class()   # agrega tools/ al path
    from dtui import ViewApp
    ViewApp(cls, title="VPN").run()


if __name__ == "__main__":
    main()
