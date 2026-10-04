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

Atajos: tab cambia de panel · enter conecta / desconecta (o importa si la fila
es un archivo todavía no importado) · n importa un archivo (o abre
nm-connection-editor en NetworkManager) · d elimina el perfil · r refresca.

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


def waybar_status_json() -> str:
    conns = nm_conns()
    active = [c for c in conns if c.active]
    if not conns:
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
    from textual.app import ComposeResult
    from textual.binding import Binding

    TITLES = {"nm": "󰛳  NetworkManager", "wireguard": "󰌆  WireGuard", "openvpn": "󰒃  OpenVPN"}
    EMPTY = {"nm": " none: press n to create one ",
             "wireguard": " none: press n to import a .conf ",
             "openvpn": " none: press n to import a .ovpn "}

    class VpnView(DView):
        FOCUS = "#wireguard"
        DEFAULT_CSS = css("""
        VpnView .panel { height: auto; max-height: 33%%; }
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

        def on_mount(self) -> None:
            for kind in KINDS:
                t = self.query_one(f"#{kind}", Table)
                t.add_column("Name", key="name", width=28)
                t.add_column("State", key="state", width=18)
                t.add_column("Type" if kind == "nm" else "Source", key="src", width=30)
            self.busy = ""
            disable_autoconnect()   # cada VPN se conecta a mano
            self.action_reload()
            self.set_interval(5.0, self.tick)

        def tick(self) -> None:
            if self.visible_now:
                self.action_reload()

        def fill(self, tid: str, rows: list) -> None:
            t = self.query_one(f"#{tid}", Table)
            row = t.cursor_row or 0
            t.clear()
            for key, cells in rows:
                t.add_row(*cells, key=key)
            if rows:
                t.move_cursor(row=min(row, len(rows) - 1))

        @staticmethod
        def state(c: Conn) -> Text:
            if not c.imported:
                return Text("◌  not imported", style=T["status_warn"])
            if c.active:
                return Text("●  connected", style=f"bold {T['status_ok']}")
            return Text("○  disconnected", style=T["muted"])

        def action_reload(self) -> None:
            conns = list_conns()
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
            if self.busy:
                self.query_one(f"#{self.focused_kind()}-panel").border_subtitle = f" {self.busy} "
            self.update_hints()

        def focused_kind(self) -> str:
            f = self.app.focused
            return f.id if isinstance(f, Table) and f.id in KINDS else "wireguard"

        def hints(self) -> list[tuple[str, str]]:
            new = {"nm": "new (editor)", "wireguard": "import .conf", "openvpn": "import .ovpn"}
            return [("enter", "connect/disconnect"), ("n", new[self.focused_kind()]), ("d", "delete"),
                    ("tab", "panel"), ("r", "refresh"), ("q", "quit")]

        def action_cycle(self, step: int) -> None:
            i = KINDS.index(self.focused_kind())
            self.query_one(f"#{KINDS[(i + step) % len(KINDS)]}", Table).focus()

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
            if event.data_table.id in KINDS and event.row_key.value:
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

        def action_delete(self) -> None:
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
