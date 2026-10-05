"""
common.py — helpers compartidos por las secciones de Settings que viven en
tools/settings/sections/ (una por archivo, cada una una DView).

Las secciones se importan desde settings_tui.py y se registran en CATEGORIES.
Estilo común de las TUIs: tools/dtui.py. Textos visibles en inglés.

Settings nunca edita archivos versionados del repo:
- Hyprland: los cambios (input, cursor) van como líneas planas
  (`input:sensitivity = 0.2`, `env = XCURSOR_SIZE,24`) a
  ~/.config/dotfiles/hypr/settings.conf, que hyprland.conf incluye al final
  (`source = ~/.config/dotfiles/hypr/*.conf`) y por eso gana. Las apps de
  inicio propias van a autostart.conf, en la misma carpeta.
- Temas: lo que se edita (Theme editor, Appearance, Fonts) se guarda en
  ~/.config/dotfiles/themes/<tema>/; si el tema es del repo se copia ahí
  primero. theme-switch.sh busca ahí antes que en themes/ del repo.
- Teclado: KB_LAYOUT / KB_VARIANT de ~/.config/dotfiles/user.conf (de donde
  se genera config/hypr/env.conf) + settings.conf para que gane al instante.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

TOOLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS))

# Raíz del repo: DOTFILES_DIR si está exportado; si no, dos niveles arriba de tools/settings
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or TOOLS.parent)
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
CONF_DIR = CONFIG_HOME / "dotfiles"
USER_CONF = CONF_DIR / "user.conf"
HYPR_CONF = DOTFILES / "config" / "hypr" / "hyprland.conf"      # del repo: solo lectura
HYPR_USER_DIR = CONF_DIR / "hypr"
SETTINGS_CONF = HYPR_USER_DIR / "settings.conf"                  # lo escribe Settings
AUTOSTART_CONF = HYPR_USER_DIR / "autostart.conf"                # apps de inicio propias
THEMES_DIR = DOTFILES / "themes"
USER_THEMES_DIR = CONF_DIR / "themes"
CURRENT_THEME = STATE_HOME / "dotfiles" / "current_theme.json"
THEME_SWITCH = DOTFILES / "scripts" / "theme-switch.sh"
STATE = STATE_HOME / "dotfiles" / "settings"
HYPRLAND = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
HOME = str(Path.home())


def run(cmd: list[str], timeout: float = 10, **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def detach(cmd: list[str]) -> None:
    """Lanza un proceso que sobrevive al cierre de Settings."""
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def tilde(path: str | Path) -> str:
    return str(path).replace(HOME, "~", 1)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# ── user.conf ─────────────────────────────────────────────

def user_conf() -> dict[str, str]:
    """KEY=VALUE de ~/.config/dotfiles/user.conf (comillas simples o dobles)."""
    out = {}
    try:
        lines = USER_CONF.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            v = m.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            out[m.group(1)] = v
    return out


def user_conf_set(key: str, value: str) -> None:
    """Cambia (o agrega) KEY="valor" en user.conf conservando el resto."""
    try:
        lines = USER_CONF.read_text().splitlines()
    except OSError:
        lines = []
    new = f'{key}="{value}"'
    pat = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}=")
    for i, l in enumerate(lines):
        if pat.match(l):
            lines[i] = new
            break
    else:
        lines.append(new)
    atomic_write(USER_CONF, "\n".join(lines) + "\n")


def display_name() -> str:
    """USER_DISPLAY_NAME de user.conf, o el nombre de GECOS, o el login."""
    name = user_conf().get("USER_DISPLAY_NAME", "")
    if not name:
        try:
            import pwd
            name = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0]
        except (KeyError, ImportError):
            name = ""
    return name or os.environ.get("USER", "")


def wallpaper_dirs() -> list[Path]:
    """Igual que WALLPAPER_DIRS de scripts/lib/env.sh."""
    extra = user_conf().get("EXTRA_WALLPAPER_DIRS", "")
    dirs = [Path(os.path.expandvars(d)).expanduser() for d in extra.split(":") if d]
    return dirs + [DATA_HOME / "backgrounds", DOTFILES / "assets" / "wallpapers"]


def resolve_wallpaper(name: str) -> Optional[Path]:
    """Como df_resolve_wallpaper: ruta absoluta (o ~) o nombre en wallpaper_dirs()."""
    p = Path(name).expanduser()
    if p.is_absolute():
        return p if p.is_file() else None
    return next((d / name for d in wallpaper_dirs() if (d / name).is_file()), None)


# ── Temas ─────────────────────────────────────────────────

def current_theme() -> dict:
    try:
        return json.loads(CURRENT_THEME.read_text())
    except (OSError, ValueError):
        return {}


def theme_dirs() -> list[Path]:
    """Carpetas de temas: las del usuario primero (pisan a las del repo con
    el mismo nombre), después las del repo. Igual que theme_names() en
    scripts/lib/theme.sh."""
    out, seen = [], set()
    for base in (USER_THEMES_DIR, THEMES_DIR):
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            if d.name in seen or d.name.startswith("_") or not (d / "theme.json").is_file():
                continue
            seen.add(d.name)
            out.append(d)
    return sorted(out, key=lambda d: d.name)


def is_user_theme(d: Path) -> bool:
    return d.parent == USER_THEMES_DIR


def active_theme_dir() -> Optional[Path]:
    """Carpeta del tema activo (`.dir` de current_theme.json; si falta, por nombre)."""
    cur = current_theme()
    dirs = theme_dirs()
    if cur.get("dir"):
        d = next((d for d in dirs if d.name == cur["dir"]), None)
        if d:
            return d
    for d in dirs:
        try:
            if json.loads((d / "theme.json").read_text()).get("name") == cur.get("name"):
                return d
        except ValueError:
            continue
    return None


def editable_theme_dir(d: Optional[Path] = None) -> Optional[Path]:
    """Carpeta donde se pueden guardar cambios del tema `d` (o del activo).
    Si es del repo, se copia antes a ~/.config/dotfiles/themes/<nombre>/."""
    d = d or active_theme_dir()
    if d is None or is_user_theme(d):
        return d
    dst = USER_THEMES_DIR / d.name
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("theme.json", "preview.png"):
        if (d / f).is_file() and not (dst / f).exists():
            shutil.copy2(d / f, dst / f)
    return dst


@contextmanager
def settings_hidden(app):
    """Esconde la ventana de Settings (workspace especial) mientras se captura
    la pantalla o se elige un píxel, y la devuelve después."""
    addr, ws = None, None
    if HYPRLAND:
        try:
            win = json.loads(run(["hyprctl", "activewindow", "-j"]).stdout or "{}")
            addr, ws = win.get("address"), win.get("workspace", {}).get("id")
        except ValueError:
            pass
    if addr:
        run(["hyprctl", "dispatch", "movetoworkspacesilent", f"special:dotfiles-hide,address:{addr}"])
        time.sleep(0.35)   # que el compositor redibuje sin la ventana
    try:
        yield
    finally:
        if addr:
            run(["hyprctl", "dispatch", "movetoworkspace", f"{ws},address:{addr}"])
            run(["hyprctl", "dispatch", "focuswindow", f"address:{addr}"])


# ── Hyprland: lectura del repo + overrides en settings.conf ──

def _flat_get(text: str, key: str) -> Optional[str]:
    # [ \t] y no \s: con un valor vacío, \s saltaba a la línea siguiente
    m = None
    for m in re.finditer(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*(.*?)[ \t]*(#.*)?$", text, re.M):
        pass
    return m.group(1) if m else None


def _block_span(text: str, block: str) -> Optional[tuple[int, int]]:
    """(inicio, fin) del cuerpo de un bloque; `input:touchpad` = bloque anidado."""
    start, end = 0, len(text)
    for name in block.split(":"):
        m = re.compile(rf"^\s*{re.escape(name)}\s*\{{\s*$", re.M).search(text, start, end)
        if not m:
            return None
        depth, i = 1, m.end()
        while i < end and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        start, end = m.end(), i - 1
    return start, end


def _conf_get(path: Path, key: str) -> Optional[str]:
    """Valor de `input:touchpad:natural_scroll` en un .conf, escrito plano o
    dentro de los bloques `input { touchpad { … } }`."""
    try:
        text = path.read_text()
    except OSError:
        return None
    flat = _flat_get(text, key)
    if flat is not None:
        return flat
    block, _, leaf = key.rpartition(":")
    span = _block_span(text, block) if block else None
    return _flat_get(text[span[0]:span[1]], leaf) if span else None


def _chain() -> list[Path]:
    """Archivos de Hyprland en orden de prioridad (el primero que define gana)."""
    # Hyprland los incluye en orden alfabético: el último que define gana
    # (settings.conf incluido; un override propio con nombre posterior le gana)
    user = sorted(HYPR_USER_DIR.glob("*.conf"), reverse=True)
    return [*user, HYPR_CONF.with_name("env.conf"), HYPR_CONF]


def hypr_get(key: str) -> Optional[str]:
    """Valor efectivo de una opción: overrides del usuario (settings.conf,
    local.conf…) > env.conf / hyprland.conf del repo."""
    for path in _chain():
        v = _conf_get(path, key)
        if v is not None:
            return v
    return None


def hypr_set(key: str, value: str) -> None:
    """Guarda `key = value` (plano) en settings.conf."""
    try:
        lines = SETTINGS_CONF.read_text().splitlines()
    except OSError:
        lines = ["# settings.conf — lo escribe Settings (tools/settings). Se puede editar",
                 "# a mano; gana sobre config/hypr/hyprland.conf porque se incluye al final.", ""]
    pat = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=")
    for i, l in enumerate(lines):
        if pat.match(l):
            lines[i] = f"{key} = {value}"
            break
    else:
        lines.append(f"{key} = {value}")
    atomic_write(SETTINGS_CONF, "\n".join(lines) + "\n")


def env_get(name: str) -> str:
    """`env = NAME,valor` efectivo (settings.conf > overrides > repo)."""
    for path in _chain():
        try:
            found = re.findall(rf"^[ \t]*env[ \t]*=[ \t]*{name}[ \t]*,[ \t]*(.+?)[ \t]*$", path.read_text(), re.M)
        except OSError:
            continue
        if found:
            return found[-1]
    return ""


def env_set(name: str, value: str) -> None:
    try:
        text = SETTINGS_CONF.read_text()
    except OSError:
        text = ""
    pat = re.compile(rf"^([ \t]*env[ \t]*=[ \t]*{name}[ \t]*,).*$", re.M)
    text = pat.sub(lambda m: m.group(1) + value, text) if pat.search(text) else \
        text.rstrip("\n") + ("\n" if text else "") + f"env = {name},{value}\n"
    atomic_write(SETTINGS_CONF, text)


def which_any(*names: str) -> Optional[str]:
    for n in names:
        if shutil.which(n):
            return n
    return None


# ── cambios que necesitan root ────────────────────────────

def sudo_run(app, cmds: list[list[str]], title: str = "") -> bool:
    """Corre los comandos con sudo en la terminal (Settings se suspende: sudo pide
    contraseña o huella). Si uno falla frena y espera un enter para leer el error.
    Devuelve True si todos terminaron bien."""
    ok = True
    with app.suspend():
        os.system("clear")
        if title:
            print(title + "\n")
        for cmd in cmds:
            print("$ sudo " + " ".join(cmd))
            if subprocess.run(["sudo", *cmd]).returncode != 0:
                ok = False
                break
        if not ok:
            input("\nPress enter to go back to Settings...")
    app.refresh(layout=True)
    return ok


def root_file(content: str) -> str:
    """Escribe `content` a un temporal del usuario para instalarlo con
    `sudo install -m644 <tmp> /etc/...` (sudo_run). Devuelve la ruta."""
    d = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "dotfiles-settings"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"root-{os.getpid()}-{time.monotonic_ns()}"
    f.write_text(content)
    return str(f)
