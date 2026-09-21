#!/usr/bin/env python3
"""
vpn_tui.py — TUI para gestionar VPN vía NetworkManager (WireGuard, OpenVPN…).

No trae ningún perfil ni proveedor configurado: muestra las conexiones VPN que
YA existen en NetworkManager y te deja importar las tuyas.

  Conexiones   Enter conecta / desconecta · d elimina · r refresca
  Importar     Enter importa un archivo de ~/.config/dotfiles/vpn/
                 *.conf -> WireGuard      *.ovpn -> OpenVPN

Agregar tu VPN: copiá el archivo de tu proveedor a ~/.config/dotfiles/vpn/ y
abrí la pestaña "Importar". (También sirve `nmcli connection import type
wireguard file <archivo>`.) Los perfiles con contraseña guardada se conectan
sin más; los que la piden se conectan en la terminal (`nmcli --ask`).

Modo rápido para waybar (sin Textual):

    vpn_tui.py --waybar-status

Imprime una línea JSON {"text", "tooltip", "class"} y sale. class:
  "connected" | "disconnected" | "disabled" (sin ningún perfil VPN configurado).

Atajo de la cheatsheet: se abre desde el módulo VPN de waybar (ventana flotante de kitty).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VPN_TYPES = {"vpn", "wireguard"}
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
IMPORT_DIR = CONFIG_HOME / "dotfiles" / "vpn"
IMPORT_KINDS = {".conf": "wireguard", ".ovpn": "openvpn"}
ICON_ON, ICON_OFF = "󰦝", "󰦞"

_UNESCAPED_COLON = re.compile(r"(?<!\\):")
_VALID_IFNAME = re.compile(r"^[A-Za-z0-9_-]{1,15}$")  # IFNAMSIZ = 16 con el nul


# ── tema (mismo estado que usan el resto de las TUIs) ───────────────────
def _hex_blend(c1: str, c2: str, pct: int) -> str:
    c1, c2 = c1.lstrip("#"), c2.lstrip("#")
    a = [int(c1[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{(x * pct + y * (100 - pct)) // 100:02x}" for x, y in zip(a, b))


def _load_theme() -> dict:
    theme = {
        "primary": "#c62828", "secondary": "#8e1a1a", "background": "#0a0a0a", "foreground": "#c5c8c6",
        "chip_battery": "#141414", "chip_bluetooth": "#1e1e1e", "status_ok": "#5cb85c",
        "status_warn": "#f9a825", "status_error": "#ff4444",
    }
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    try:
        data = json.loads((state / "dotfiles" / "current_theme.json").read_text())
        theme.update({k: v for k, v in data.items() if k in theme})
    except (OSError, ValueError):
        pass
    theme["text_muted"] = _hex_blend(theme["foreground"], theme["background"], 45)
    return theme


THEME = _load_theme()


# ── NetworkManager ──────────────────────────────────────────────────────
def _run(cmd: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 1, "", str(exc))


@dataclass
class Conn:
    name: str
    kind: str      # "wireguard" | "vpn" (OpenVPN, etc.)
    active: bool


def _split_terse(line: str) -> list[str]:
    """`nmcli -t` separa con ':' y escapa los ':' internos como '\\:'."""
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in _UNESCAPED_COLON.split(line)]


def list_conns() -> list[Conn]:
    r = _run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show"])
    if r.returncode != 0:
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3 or parts[1] not in VPN_TYPES:
            continue
        out.append(Conn(name=parts[0], kind=parts[1], active=bool(parts[2].strip())))
    return sorted(out, key=lambda c: c.name.lower())


def importable() -> list[tuple[Path, str]]:
    """Archivos de IMPORT_DIR que todavía no están en NetworkManager."""
    have = {c.name for c in list_conns()}
    files = []
    try:
        for p in sorted(IMPORT_DIR.iterdir()):
            if p.suffix.lower() in IMPORT_KINDS and p.stem not in have:
                files.append((p, IMPORT_KINDS[p.suffix.lower()]))
    except OSError:
        pass
    return files


def import_file(path: Path, kind: str) -> subprocess.CompletedProcess:
    """Importa un .conf/.ovpn. NetworkManager usa el nombre del archivo como nombre de interfaz
    (máx. 15 caracteres); si es más largo se importa una copia con nombre corto y se renombra
    la conexión (connection.id admite cualquier largo)."""
    if kind != "wireguard" or _VALID_IFNAME.match(path.stem):
        return _run(["nmcli", "connection", "import", "type", kind, "file", str(path)], timeout=20)
    try:
        data = path.read_bytes()
    except OSError as exc:
        return subprocess.CompletedProcess(["nmcli"], 1, "", f"no se pudo leer {path}: {exc}")
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


def waybar_status_json() -> str:
    conns = list_conns()
    active = [c for c in conns if c.active]
    if not conns:
        text, cls = ICON_OFF, "disabled"
        tip = "Sin perfiles VPN configurados\nClick para agregar uno"
    elif active:
        text, cls = ICON_ON, "connected"
        tip = "VPN: " + ", ".join(c.name for c in active) + "\nClick para gestionar VPN"
    else:
        text, cls = ICON_OFF, "disconnected"
        tip = f"VPN desconectada ({len(conns)} perfil{'es' if len(conns) != 1 else ''})\nClick para gestionar VPN"
    return json.dumps({"text": text, "tooltip": tip, "class": cls}, ensure_ascii=False)


def main_waybar_status() -> None:
    try:
        print(waybar_status_json())
    except Exception as exc:  # nunca colgar el polling de waybar
        print(json.dumps({"text": ICON_OFF, "tooltip": f"vpn-tui error: {exc}", "class": "disconnected"}))
    sys.exit(0)


# ── TUI (Textual, se importa solo si hace falta) ────────────────────────
def build_app():
    from textual import on
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, DataTable, Footer, Header, Static, TabbedContent, TabPane

    class ConfirmModal(ModalScreen[bool]):
        BINDINGS = [Binding("escape", "dismiss(False)", "")]

        def __init__(self, msg: str) -> None:
            super().__init__()
            self._msg = msg

        def compose(self) -> ComposeResult:
            with Vertical(id="confirm-box"):
                yield Static(self._msg)
                with Horizontal(id="confirm-btns"):
                    yield Button("Sí", id="yes", variant="error")
                    yield Button("Cancelar", id="no")

        @on(Button.Pressed)
        def _pressed(self, event: Button.Pressed) -> None:
            self.dismiss(event.button.id == "yes")

    class VpnApp(App):
        TITLE = "VPN"
        CSS = """
        Screen { background: %(background)s; color: %(foreground)s; }
        Header { background: %(chip_battery)s; color: %(primary)s; }
        Footer { background: %(chip_battery)s; }
        DataTable { background: %(background)s; height: 1fr; }
        DataTable > .datatable--cursor { background: %(primary)s; color: %(background)s; }
        #hint { color: %(text_muted)s; padding: 1 2; }
        #status { color: %(text_muted)s; height: 1; padding: 0 2; }
        ConfirmModal { align: center middle; }
        #confirm-box { background: %(chip_battery)s; padding: 2 3; width: 60; height: auto; }
        #confirm-btns { height: auto; margin-top: 1; }
        """ % THEME
        BINDINGS = [
            Binding("q", "quit", "salir"),
            Binding("r", "reload", "refrescar"),
            Binding("d", "delete", "eliminar"),
            Binding("1", "tab('tab-conns')", "conexiones"),
            Binding("2", "tab('tab-import')", "importar"),
        ]

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with TabbedContent(initial="tab-conns"):
                with TabPane("1 Conexiones", id="tab-conns"):
                    yield Static("", id="hint")
                    yield DataTable(id="conns", cursor_type="row")
                with TabPane("2 Importar", id="tab-import"):
                    yield Static(f"Archivos de {IMPORT_DIR} (.conf = WireGuard, .ovpn = OpenVPN). Enter importa.", id="import-hint")
                    yield DataTable(id="imports", cursor_type="row")
            yield Static("", id="status")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#conns", DataTable).add_columns("Nombre", "Tipo", "Estado")
            self.query_one("#imports", DataTable).add_columns("Archivo", "Tipo")
            self.action_reload()

        def _say(self, msg: str) -> None:
            self.query_one("#status", Static).update(msg)

        def action_tab(self, tab_id: str) -> None:
            self.query_one(TabbedContent).active = tab_id

        def action_reload(self) -> None:
            conns, files = list_conns(), importable()
            table = self.query_one("#conns", DataTable)
            table.clear()
            for c in conns:
                estado = "[b]● conectada[/b]" if c.active else "○ desconectada"
                table.add_row(c.name, "WireGuard" if c.kind == "wireguard" else "VPN", estado, key=c.name)
            self.query_one("#hint", Static).update(
                "" if conns else
                "Sin perfiles VPN.\nCopiá el archivo de tu proveedor a "
                f"{IMPORT_DIR} y usá la pestaña 2 (Importar)."
            )
            imp = self.query_one("#imports", DataTable)
            imp.clear()
            for path, kind in files:
                imp.add_row(path.name, kind, key=str(path))

        @on(DataTable.RowSelected, "#conns")
        async def _toggle(self, event: DataTable.RowSelected) -> None:
            name = event.row_key.value
            conn = next((c for c in list_conns() if c.name == name), None)
            if conn is None:
                return
            if conn.active:
                self._say(f"Desconectando {name}…")
                r = await asyncio.to_thread(_run, ["nmcli", "connection", "down", "id", name], 20)
            elif conn.kind == "vpn":
                # Puede pedir contraseña/OTP: se conecta en la terminal.
                with self.suspend():
                    r = subprocess.run(["nmcli", "--ask", "connection", "up", "id", name])
            else:
                self._say(f"Conectando {name}…")
                r = await asyncio.to_thread(_run, ["nmcli", "connection", "up", "id", name], 30)
            msg = (getattr(r, "stderr", "") or getattr(r, "stdout", "") or "").strip().splitlines()
            self._say("OK" if r.returncode == 0 else (msg[-1] if msg else "falló (ver nmcli)"))
            self.action_reload()

        @on(DataTable.RowSelected, "#imports")
        async def _import(self, event: DataTable.RowSelected) -> None:
            path = Path(event.row_key.value)
            self._say(f"Importando {path.name}…")
            r = await asyncio.to_thread(import_file, path, IMPORT_KINDS[path.suffix.lower()])
            msg = (r.stderr or r.stdout).strip().splitlines()
            self._say("Importada: aparece en la pestaña Conexiones" if r.returncode == 0 else (msg[-1] if msg else "falló"))
            self.action_reload()

        def action_delete(self) -> None:
            table = self.query_one("#conns", DataTable)
            if self.query_one(TabbedContent).active != "tab-conns" or table.row_count == 0:
                return
            name = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

            def done(ok: Optional[bool]) -> None:
                if ok:
                    r = _run(["nmcli", "connection", "delete", "id", name])
                    self._say("Eliminada" if r.returncode == 0 else "no se pudo eliminar")
                    self.action_reload()

            self.push_screen(ConfirmModal(f"¿Eliminar el perfil «{name}» de NetworkManager?"), done)

    return VpnApp()


def main() -> None:
    if "--waybar-status" in sys.argv:
        main_waybar_status()
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        return
    build_app().run()


if __name__ == "__main__":
    main()
