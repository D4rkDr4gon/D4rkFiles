"""Configuración por usuario/máquina para Qtile.

Lee ~/.config/dotfiles/user.conf (KEY=VALUE, mismo archivo que usan los
scripts de shell) y autodetecta lo que falte. Nada acá depende del usuario ni
de dónde esté clonado el repo.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

HOME = Path.home()
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
XDG_STATE = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state"))

# Symlink estable al repo, creado por install.sh (o DOTFILES_DIR si está exportado).
DOTFILES = Path(os.environ.get("DOTFILES_DIR", HOME / ".local/share/dotfiles"))
USER_CONF = XDG_CONFIG / "dotfiles" / "user.conf"
CURRENT_THEME = XDG_STATE / "dotfiles" / "current_theme.json"


def _read_user_conf():
    values = {}
    try:
        for line in USER_CONF.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


_CONF = _read_user_conf()


def conf(key, default=""):
    """Valor de user.conf (o de la variable de entorno del mismo nombre)."""
    return os.environ.get(key) or _CONF.get(key) or default


def first_available(*commands, default=""):
    for cmd in commands:
        if shutil.which(cmd.split()[0]):
            return cmd
    return default


def terminal():
    return conf("TERMINAL") or first_available("kitty", "alacritty", "foot", "xterm", default="xterm")


def browser():
    return conf("BROWSER") or first_available("firefox", "chromium", "brave-browser", default="xdg-open")


def file_manager():
    return conf("FILE_MANAGER") or first_available("thunar", "nautilus", "dolphin", "pcmanfm", default="thunar")


def editor():
    return conf("EDITOR_GUI") or first_available("subl", "code", "gedit", "kate", default=terminal() + " -e nvim")


def kb_layout():
    layout = conf("KB_LAYOUT")
    if layout:
        return layout
    try:
        out = subprocess.run(["localectl", "status"], capture_output=True, text=True, timeout=2).stdout
        for line in out.splitlines():
            if "X11 Layout" in line:
                return line.split(":", 1)[1].strip() or "us"
    except (OSError, subprocess.SubprocessError):
        pass
    return "us"


def theme():
    """Tema activo (theme-switch.sh lo escribe en el directorio de estado)."""
    try:
        return json.loads(CURRENT_THEME.read_text())
    except (OSError, ValueError):
        return {}


def screen_count():
    """Monitores conectados (X11). Con menos de 2 se devuelve 2: los Screen de
    más los ignora Qtile, y así un monitor conectado en caliente ya tiene fondo."""
    n = 0
    if shutil.which("xrandr"):
        try:
            out = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=2).stdout
            n = sum(1 for line in out.splitlines() if " connected" in line)
        except (OSError, subprocess.SubprocessError):
            pass
    return max(2, n)
