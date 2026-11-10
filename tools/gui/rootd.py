#!/usr/bin/env python3
"""
rootd.py — helper root de la GUI (modo de sesión GUI).

Lo arranca tools/gui/bridge.py con `pkexec` la PRIMERA vez que una ventana GUI
necesita root (polkit pide la huella una vez) y queda vivo mientras viva el
backend de la GUI: lee pedidos por stdin y muere cuando stdin se cierra (el
backend se cierra unos minutos después de cerrar todas las ventanas GUI).

Protocolo: una línea JSON por pedido {"id", "argv", "input"?, "timeout"?, "log"?}
→ una línea {"id", "rc", "out", "err"}. Solo corre binarios de ALLOWED, por ruta
absoluta resuelta acá (no por PATH del usuario) y sin shell. "log": ruta donde ir
escribiendo la salida (trabajos largos como la actualización; la GUI la lee en vivo).
Es el equivalente de `sudo` de la TUI (common.sudo_run), sin terminal.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

ALLOWED = {
    "systemctl", "firewall-cmd", "pacman", "paccache", "install", "rm", "mv", "cp", "mkdir", "ln", "chmod",
    "tee", "git", "etckeeper", "timeshift", "usbguard", "sysctl", "nft", "ip", "nmcli", "journalctl",
    "fwupdmgr", "openfortivpn", "wg-quick", "tailscale", "pacdiff", "updatedb", "fstrim", "loginctl",
    "openvpn", "openconnect", "kill", "pkill", "resolvectl", "modprobe", "udevadm", "tlp", "powerprofilesctl",
    "netguard-root", "cat", "sed", "test", "touch", "true", "ls",
}
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/usr/local/lib/netguard"


def resolve(cmd: str) -> str | None:
    name = os.path.basename(cmd)
    if name not in ALLOWED:
        return None
    if os.path.isabs(cmd):
        return cmd if os.path.dirname(cmd) in SAFE_PATH.split(":") and os.access(cmd, os.X_OK) else None
    return shutil.which(name, path=SAFE_PATH)


def handle(req: dict) -> dict:
    argv = req.get("argv") or []
    if not argv or not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return {"rc": 2, "out": "", "err": "bad request"}
    exe = resolve(argv[0])
    if not exe:
        return {"rc": 126, "out": "", "err": f"not allowed: {argv[0]}"}
    env = {"PATH": SAFE_PATH, "LANG": os.environ.get("LANG", "C.UTF-8"), "TERM": "dumb"}
    timeout = min(int(req.get("timeout") or 600), 7200)
    try:
        if req.get("log"):
            with open(req["log"], "w") as log:
                os.chmod(req["log"], 0o644)
                p = subprocess.run([exe, *argv[1:]], input=req.get("input"), stdout=log, stderr=subprocess.STDOUT,
                                   text=True, timeout=timeout, env=env)
            return {"rc": p.returncode, "out": "", "err": ""}
        p = subprocess.run([exe, *argv[1:]], input=req.get("input"), capture_output=True, text=True,
                           timeout=timeout, env=env)
        return {"rc": p.returncode, "out": p.stdout[-200000:], "err": p.stderr[-20000:]}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "out": "", "err": "timeout"}
    except OSError as e:
        return {"rc": 127, "out": "", "err": str(e)}


def main() -> None:
    if os.geteuid() != 0:
        sys.exit("rootd: must run as root (pkexec)")
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except ValueError:
            continue
        res = handle(req)
        res["id"] = req.get("id")
        print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
