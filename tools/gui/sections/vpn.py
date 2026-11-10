"""VPN (GUI): paridad con tools/vpn_tui.py (usa su backend, sin Textual).

Las conexiones VPN que ya existen en NetworkManager, en tres grupos (NetworkManager:
OpenConnect, L2TP, vpnc…; WireGuard; OpenVPN) + Tailscale si está instalado. Los .conf/.ovpn
de ~/.config/dotfiles/vpn/ sin importar aparecen como "not imported" (click = importar).
Lo que la TUI hace en la terminal: las VPN de NetworkManager que piden contraseña u OTP se
conectan en una terminal (`nmcli --ask`); el setup de Tailscale que va con sudo pasa por el
helper root (huella una vez) y el login abre la URL en el navegador.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import _lib as L

sys.path.insert(0, str(L.TOOLS))
import vpn_tui as V  # noqa: E402  (el backend no carga Textual)

UI: dict = {}
STATE = {"autoconnect_done": False}
TITLES = {"nm": "NetworkManager", "wireguard": "WireGuard", "openvpn": "OpenVPN"}
GLYPHS = {"nm": "󰛳", "wireguard": "󰌆", "openvpn": "󰒃"}
EXT = {"wireguard": ".conf", "openvpn": ".ovpn"}


def tilde(p) -> str:
    return str(p).replace(str(Path.home()), "~", 1)


def get() -> dict:
    if not STATE["autoconnect_done"]:          # como la TUI al abrir: cada VPN se conecta a mano
        V.disable_autoconnect()
        STATE["autoconnect_done"] = True
    conns = V.list_conns()
    groups = []
    for kind in V.KINDS:
        mine = [c for c in conns if c.kind == kind]
        rows = []
        for c in mine:
            state = "not imported" if not c.imported else ("connected" if c.active else "disconnected")
            acts = [L.action(f"del:{c.name}", "Delete", True)] if c.imported else []
            rows.append(L.item(f"conn:{c.name}", c.name, sub=c.plugin if kind == "nm" else (tilde(c.path) if c.path else "—"),
                               right=state, glyph=GLYPHS[kind], on=c.active, actions=acts))
        new = (L.button("new:nm", "New connection", "OpenConnect, L2TP, vpnc… (nm-connection-editor)", "New") if kind == "nm"
               else L.button(f"new:{kind}", f"Import {EXT[kind]}", f"Any path; files in {tilde(V.IMPORT_DIR)}/ also show up here", "Import"))
        active = [c.name for c in mine if c.active]
        title = TITLES[kind] + (f" · connected: {', '.join(active)}" if active else "")
        groups.append(L.group(title, rows + [new]))
    groups.append(L.group("Tailscale", tailscale_rows()))
    return L.page("VPN", "Click a connection to connect or disconnect", groups, refresh=5)


def tailscale_rows() -> list:
    if not V.tailscale_installed():
        return [L.info("ts", "Tailscale", "not installed (sudo pacman -S tailscale)", "optional")]
    s = V.tailscale_status()
    if s is None:
        return [L.item("ts:setup", "Tailscale", sub="daemon off — click to set up (once)", right="off", glyph="󰖂")]
    state = s.get("BackendState", "")
    me = s.get("Self") or {}
    ip = (me.get("TailscaleIPs") or [""])[0]
    tailnet = (s.get("CurrentTailnet") or {}).get("Name", "")
    label = {"Running": "connected", "NeedsLogin": "logged out", "NoState": "logged out",
             "NeedsMachineAuth": "awaiting approval", "Starting": "starting…"}.get(state, "disconnected")
    rows = [L.item("ts:self", f"{me.get('HostName') or 'this device'} (this)",
                   sub=" · ".join(x for x in (ip, tailnet) if x) or "click to log in",
                   right=label, glyph="󰖂", on=state == "Running",
                   actions=[L.action("ts:logout", "Log out", True)] if state not in ("NeedsLogin", "NoState") else [])]
    if state == "Running":
        for p in V.tailscale_peers(s):
            acts = []
            if p["exit"]:
                acts = [L.action("ts:exitoff", "Stop exit node")]
            elif p["exit_option"]:
                acts = [L.action(f"ts:exit:{p['ip']}", "Use as exit node")]
            rows.append(L.item(f"ts:peer:{p['ip']}", p["name"],
                               sub=f"{p['ip']} · {p['os']}" + (" · exit node available" if p["exit_option"] else ""),
                               right="exit node" if p["exit"] else ("online" if p["online"] else "offline"),
                               glyph="󰍹", on=p["online"], actions=acts + [L.action(f"ts:copy:{p['ip']}", "Copy IP")]))
    return rows


def set_value(key, value):
    return L.fail("Unknown field")


def res(r: subprocess.CompletedProcess, ok_msg: str) -> dict:
    if r.returncode == 0:
        return L.ok(ok_msg)
    lines = ((r.stderr or r.stdout or "").strip().splitlines() or ["failed (see nmcli)"])
    return L.fail(lines[-1][:160])


def find(name: str):
    return next((c for c in V.list_conns() if c.name == name), None)


def ts_run(ok_msg: str, *args: str) -> dict:
    """tailscale como usuario si es operator; si no, como root (helper de la GUI)."""
    if V.tailscale_operator():
        return res(V.tailscale_cmd(*args), ok_msg)
    return L.root_ok([["tailscale", *args]], ok_msg)


def ts_login() -> dict:
    """`tailscale up` imprime la URL de login y espera: se corre aparte y se abre la URL en el navegador."""
    log = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "tailscale-up.log"
    with open(log, "w") as f:
        subprocess.Popen(["tailscale", "up"], stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(40):
        time.sleep(0.25)
        m = re.search(r"https://login\.tailscale\.com/\S+", log.read_text(errors="ignore"))
        if m:
            L.detach(["xdg-open", m.group(0)])
            return L.ok("Login page opened in the browser")
    return L.ok("Tailscale is coming up")


def import_form(kind: str, error: str = "", path: str = "") -> dict:
    return L.form(f"new:{kind}", f"Import {TITLES[kind]} profile",
                  [{"name": "path", "label": f"{EXT[kind].upper()} FILE", "text": path or f"{V.IMPORT_DIR}/"}],
                  error=error, hint=f"Any path works; files in {tilde(V.IMPORT_DIR)}/ also show up here before importing.",
                  ok_label="Import")


def act(key: str, text=None):
    op, _, arg = key.partition(":")

    if op == "conn":
        c = find(arg)
        if c is None:
            return L.ok()
        if not c.imported:
            return res(V.import_file(c.path), f"{c.name} imported")
        if c.active:
            return res(V._run(["nmcli", "connection", "down", "id", c.name], 20), f"{c.name} disconnected")
        if c.kind == "nm":
            # Puede pedir contraseña u OTP: como la TUI, se conecta en una terminal
            return L.terminal(["nmcli", "--ask", "connection", "up", "id", c.name], f"Connect {c.name}",
                              "Finish connecting in the terminal")
        if c.kind == "openvpn":
            needs, user = V.openvpn_auth(c.name)
            if needs:
                if text is None:
                    return L.form(key, f"Connect · {c.name}", [{"name": "user", "label": "USER", "text": user},
                                                              {"name": "pass", "label": "PASSWORD", "text": "", "secret": True}],
                                  hint="The password is not stored by NetworkManager", ok_label="Connect")
                f = L.parse_form(text)
                return res(V.openvpn_up(c.name, f.get("user", "").strip(), f.get("pass", "")), f"{c.name} connected")
        return res(V._run(["nmcli", "connection", "up", "id", c.name], 40), f"{c.name} connected")

    if op == "new":
        if arg == "nm":
            if shutil.which("nm-connection-editor"):
                L.detach(["nm-connection-editor", "--create", "--type=vpn"])
                return L.ok("nm-connection-editor opened")
            return L.fail("Install nm-connection-editor (or use nmcli connection add type vpn)")
        if arg not in EXT:
            return L.ok()
        if text is None:
            return import_form(arg)
        raw = L.parse_form(text).get("path", "").strip()
        p = Path(raw).expanduser()
        if not p.is_file():
            return import_form(arg, f"File not found: {raw}", raw)
        if p.suffix.lower() != EXT[arg]:
            return import_form(arg, f"Expected a {EXT[arg]} file", raw)
        if p.stem in {c.name for c in V.nm_conns()}:
            return import_form(arg, f"'{p.stem}' is already imported", raw)
        return res(V.import_file(p), f"{p.stem} imported")

    if op == "del":
        c = find(arg)
        if c is None or not c.imported:
            return L.fail("Nothing to delete: the profile is not imported")
        if not L.yes(text):
            return L.confirm(key, "Delete profile", f"Delete “{c.name}” from NetworkManager?\nThe source file (if any) is kept.",
                             ok_label="Delete")
        if c.active:
            V._run(["nmcli", "connection", "down", "id", c.name], 15)
        return res(V._run(["nmcli", "connection", "delete", "id", c.name]), f"{c.name} deleted")

    if op == "ts":
        sub, _, ip = arg.partition(":")
        if not V.tailscale_installed():
            return L.fail("tailscale is not installed: sudo pacman -S tailscale")
        s = V.tailscale_status()
        if sub == "setup" or s is None or s.get("BackendState") in ("NeedsLogin", "NoState"):
            user = os.environ.get("USER", "")
            cmds = []
            if s is None:
                cmds.append(["systemctl", "enable", "--now", "tailscaled"])
            if s is None or not V.tailscale_operator():
                cmds.append(["tailscale", "set", f"--operator={user}"])
            if cmds:
                ok_, out = L.root_run(cmds)
                if not ok_:
                    return L.fail(out[-160:])
                time.sleep(1)
            if s is not None and s.get("BackendState") == "Running" and not cmds:
                return L.ok("Tailscale is already set up and connected")
            return ts_login()
        if sub == "self":
            return ts_run("Tailscale disconnected", "down") if s.get("BackendState") == "Running" else ts_run("Tailscale connected", "up")
        if sub == "logout":
            if not L.yes(text):
                return L.confirm(key, "Log out of Tailscale", "Log this device out of the tailnet?\n"
                                 "You'll need to log in again to reconnect.", ok_label="Log out")
            return ts_run("Logged out of Tailscale", "logout")
        if sub == "exitoff":
            return ts_run("Exit node off", "set", "--exit-node=")
        if sub == "exit":
            if not L.yes(text):
                return L.confirm(key, "Use exit node", f"Route all your traffic through {ip}?\nLAN access is kept.",
                                 danger=False, ok_label="Use")
            return ts_run(f"Exit node: {ip}", "set", f"--exit-node={ip}", "--exit-node-allow-lan-access")
        if sub in ("copy", "peer"):
            subprocess.run(["wl-copy", ip])
            return L.ok(f"Copied {ip}")
    return L.ok()
