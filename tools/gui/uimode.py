#!/usr/bin/env python3
"""
uimode.py — modo de sesión TUI / GUI (~/.config/dotfiles/ui.conf).

Lo usa Settings → Appearance → Session mode. Los scripts bash leen el mismo
archivo con scripts/ui-mode.sh. UI_CONF apunta a una copia en las pruebas.

    python3 uimode.py            # imprime el modo
    python3 uimode.py gui|tui    # lo guarda y arranca/detiene el daemon de Quickshell
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MODES = ("tui", "gui")
CONF = Path(os.environ.get("UI_CONF") or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dotfiles" / "ui.conf")
LAUNCH = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[2]) / "config" / "quickshell" / "launch.sh"


def get_mode() -> str:
    """'tui' si falta el archivo, la clave o el valor es inválido."""
    try:
        for line in reversed(CONF.read_text().splitlines()):
            m = re.match(r"\s*mode\s*=\s*([A-Za-z]+)", line)
            if m:
                return m.group(1) if m.group(1) in MODES else "tui"
    except OSError:
        pass
    return "tui"


def gui_available() -> bool:
    """Quickshell instalado y su configuración presente."""
    return shutil.which("qs") is not None and LAUNCH.is_file()


def set_mode(mode: str) -> None:
    """Escribe el modo conservando comentarios (temporal + os.replace)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    lines = CONF.read_text().splitlines() if CONF.exists() else []
    done = False
    for i, line in enumerate(lines):
        if re.match(r"\s*mode\s*=", line):
            lines[i], done = f"mode={mode}", True
    if not done:
        lines.append(f"mode={mode}")
    CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONF.with_suffix(".conf.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, CONF)


def apply_daemon(mode: str) -> None:
    """Arranca (gui) o detiene (tui) el daemon de Quickshell. No hace nada si
    la GUI no está disponible. Solo se llama cuando el usuario cambia el modo."""
    if not gui_available():
        return
    if mode == "gui":
        subprocess.Popen([str(LAUNCH)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        subprocess.run(["qs", "-p", str(LAUNCH.parent), "kill"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(get_mode())
    else:
        set_mode(sys.argv[1])
        apply_daemon(sys.argv[1])
