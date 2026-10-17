"""Cliente de netguard para Settings: todo pasa por su CLI (https://github.com/D4rkDr4gon/netguard), así
Settings no tiene una copia propia de la lógica. Se lee con `netguard … --json` y se cambia con sus comandos.

- `read(...)`   JSON de un comando de lectura (None si netguard no está o falló).
- `call(...)`   comando que cambia algo. Si baja la protección, netguard pide huella/contraseña al agente de
                polkit: bloquea, así que se llama desde un worker.
- `term(...)`   comando que usa sudo (setup, harden, apps apply…): suspende Settings y lo corre en la terminal.
- `install(...)` instala netguard con scripts/install-netguard.sh (versión fijada, makepkg).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Optional

from common import DOTFILES

INSTALLER = DOTFILES / "scripts" / "install-netguard.sh"
DOCS = "https://github.com/D4rkDr4gon/netguard/tree/main/docs"


def exe() -> Optional[str]:
    return shutil.which("netguard")


def available() -> bool:
    return exe() is not None


def read(*args: str, timeout: float = 20) -> Any:
    if not exe():
        return None
    try:
        r = subprocess.run([exe(), *args, "--json"], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "NO_COLOR": "1"})
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def call(*args: str, timeout: float = 150) -> tuple[bool, str]:
    """(salió bien, mensaje de netguard). Puede esperar la autenticación de polkit."""
    if not exe():
        return False, "netguard is not installed"
    try:
        r = subprocess.run([exe(), *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env={**os.environ, "NO_COLOR": "1"})
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    msg = (r.stdout + r.stderr).strip().splitlines()
    msg = [m for m in msg if not m.startswith("authentication needed")]
    return r.returncode == 0, (msg[-1] if msg else "").lstrip("✓✗ ").strip()


def term(app, args: list[str], title: str = "") -> bool:
    """Corre un comando de netguard en la terminal (Settings se suspende: sudo pide contraseña o huella)."""
    with app.suspend():
        os.system("clear")
        if title:
            print(f"{title}\n")
        ok = subprocess.run([exe() or "netguard", *args]).returncode == 0
        input("\nPress enter to go back to Settings...")
    app.refresh(layout=True)
    return ok


def install(app, setup: bool = True) -> bool:
    """Instala netguard (git + makepkg) en la terminal y, si se pide, lo configura."""
    with app.suspend():
        os.system("clear")
        ok = subprocess.run(["bash", str(INSTALLER), *(["--setup"] if setup else [])]).returncode == 0
        input("\nPress enter to go back to Settings...")
    app.refresh(layout=True)
    return ok
