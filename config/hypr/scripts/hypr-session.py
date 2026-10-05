#!/usr/bin/env python3
"""hypr-session — guarda las ventanas abiertas y las vuelve a abrir cada una en su workspace.

Uso: hypr-session.py save | restore | status | daemon
  save     guarda ahora (~/.local/state/hypr-session/session.json; la anterior
           queda como previous.json)
  restore  abre lo guardado que no esté ya abierto
  status   resumen en JSON (lo usa Settings → Workspaces)
  daemon   exec-once: restaura al iniciar sesión si restore_on_login=on y después
           guarda cada `interval` s si autosave=on (solo si cambió algo y hay ventanas)

Config: ~/.config/dotfiles/session.conf (SESSION_CONF para una copia; estado con
SESSION_STATE). Qué se relanza por ventana, en orden:
1. Webapps de firefoxpwa: su FFPWA-<id>.desktop → `gio launch` (también cualquier
   app con .desktop del nombre de su clase si no se pudo leer el proceso).
2. Si no, la línea de comandos del proceso dueño de la ventana (/proc/<pid>/cmdline), en
   su mismo directorio (kitty -e herdr, obsidian, firefox…).
Un proceso con varias ventanas (navegadores) se lanza una vez: el resto lo
restaura la propia app. Las ventanas nuevas se ubican por clase (y título) en su
workspace y, si eran flotantes, con su tamaño y posición; también las que abre una
app al restaurar su propia sesión, mientras dure la ventana de restauración (60 s).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

CONF = Path(os.environ.get("SESSION_CONF", Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
                          / "dotfiles" / "session.conf"))
STATE = Path(os.environ.get("SESSION_STATE", Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
                            / "hypr-session"))
SESSION = STATE / "session.json"
PREVIOUS = STATE / "previous.json"
APP_DIRS = [Path.home() / ".local/share/applications", Path("/usr/share/applications")]
PLACE_WINDOW = 60     # segundos que se espera a que aparezcan las ventanas restauradas
DEFAULTS = {"autosave": "on", "interval": "120", "restore_on_login": "off",
            # TUIs flotantes y diálogos: no tiene sentido reabrirlos
            "skip": "settings,modes,shortcuts,clipboard,vpn-tui,webapps,claude-agents,dotfiles-update,impala,"
                    "bluetui,hyprmon,cliamp,pinentry,ssh-askpass,nm-connection-editor,pavucontrol,blueman-manager,"
                    "xdg-desktop-portal-gtk,hyprpolkitagent"}


def load_conf() -> dict:
    conf = dict(DEFAULTS)
    try:
        for line in CONF.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                conf[k.strip()] = v.strip()
    except OSError:
        pass
    return conf


def hypr(*args: str) -> str:
    try:
        return subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def clients() -> list[dict]:
    try:
        return json.loads(hypr("clients", "-j") or "[]")
    except ValueError:
        return []


def proc_cmd(pid: int) -> tuple[list[str], str]:
    try:
        argv = [a for a in Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").split("\0") if a]
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return [], ""
    return argv, cwd


def shell_cwd(pid: int) -> str:
    try:
        kids = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        return os.readlink(f"/proc/{kids[0]}/cwd") if kids else ""
    except OSError:
        return ""


def desktop_for(cls: str) -> str:
    for d in APP_DIRS:
        f = d / f"{cls}.desktop"
        if f.is_file():
            return str(f)
    return ""


def snapshot(skip: set[str]) -> list[dict]:
    """Ventanas a guardar, en orden de workspace (las especiales y las de skip no)."""
    out = []
    for c in clients():
        ws = c.get("workspace", {})
        cls = c.get("class") or c.get("initialClass") or ""
        if not cls or cls in skip or ws.get("id", 0) <= 0 or not c.get("mapped", True):
            continue
        argv, cwd = proc_cmd(c["pid"])
        if argv and Path(argv[0]).name == "kitty":
            cwd = shell_cwd(c["pid"]) or cwd     # donde quedó parada la shell, no donde arrancó kitty
        out.append({"class": cls, "title": c.get("title", ""), "initialTitle": c.get("initialTitle", ""),
                    "workspace": ws["id"], "monitor": c.get("monitor"), "floating": c.get("floating", False),
                    "at": c.get("at"), "size": c.get("size"), "fullscreen": c.get("fullscreen", 0),
                    "pid": c["pid"], "argv": argv, "cwd": cwd, "desktop": desktop_for(cls)})
    return sorted(out, key=lambda w: (w["workspace"], w["class"]))


def signature(wins: list[dict]) -> list:
    return [(w["class"], w["workspace"], w["floating"]) for w in wins]


def save(force: bool = True) -> int:
    conf = load_conf()
    wins = snapshot({s.strip() for s in conf["skip"].split(",") if s.strip()})
    if not wins:
        return 0
    try:
        old = json.loads(SESSION.read_text())
    except (OSError, ValueError):
        old = None
    if not force and old and signature(old.get("windows", [])) == signature(wins):
        return len(wins)
    STATE.mkdir(parents=True, exist_ok=True)
    if old:
        os.replace(SESSION, PREVIOUS)
    tmp = SESSION.with_suffix(".tmp")
    tmp.write_text(json.dumps({"time": time.time(), "windows": wins}, indent=1))
    os.replace(tmp, SESSION)
    return len(wins)


def launch_line(w: dict) -> str:
    # El .desktop solo para webapps (su cmdline es el runtime de firefox con un
    # perfil) o si no se pudo leer el proceso: el de kitty perdería el `-e herdr`
    if w["desktop"] and (w["class"].startswith("FFPWA-") or not w["argv"]):
        return shlex.join(["gio", "launch", w["desktop"]])
    if not w["argv"]:
        return ""
    cmd = shlex.join(w["argv"])
    return f"cd {shlex.quote(w['cwd'])} && exec {cmd}" if w["cwd"] else cmd


def place(addr: str, w: dict) -> None:
    hypr("dispatch", "movetoworkspacesilent", f"{w['workspace']},address:{addr}")
    if w["floating"]:
        hypr("dispatch", "setfloating", f"address:{addr}")
        if w.get("size"):
            hypr("dispatch", "resizewindowpixel", f"exact {w['size'][0]} {w['size'][1]},address:{addr}")
        if w.get("at"):
            hypr("dispatch", "movewindowpixel", f"exact {w['at'][0]} {w['at'][1]},address:{addr}")


def restore() -> int:
    try:
        wins = json.loads(SESSION.read_text()).get("windows", [])
    except (OSError, ValueError):
        return 0
    before = clients()
    open_count: dict[str, int] = {}
    for c in before:
        open_count[c.get("class", "")] = open_count.get(c.get("class", ""), 0) + 1
    # Lo que ya está abierto no se relanza (restaurar dos veces no duplica)
    pending, launched_pids = [], set()
    for w in wins:
        if open_count.get(w["class"], 0) > 0:
            open_count[w["class"]] -= 1
            continue
        pending.append(w)
        if w["pid"] in launched_pids:
            continue        # otra ventana del mismo proceso: la abre la app
        launched_pids.add(w["pid"])
        line = launch_line(w)
        if line:
            hypr("dispatch", "exec", f"[workspace {w['workspace']} silent] {line}")
    if not pending:
        return 0
    total = len(pending)
    seen = {c["address"] for c in before}
    deadline = time.monotonic() + PLACE_WINDOW
    while pending and time.monotonic() < deadline:
        time.sleep(1)
        for c in clients():
            if c["address"] in seen:
                continue
            same = [w for w in pending if w["class"] == c.get("class")]
            if not same:
                continue        # todavía sin clase definitiva (electron): se reintenta
            seen.add(c["address"])
            w = next((x for x in same if x["title"] == c.get("title")), None) or \
                next((x for x in same if x["initialTitle"] == c.get("initialTitle")), None) or same[0]
            pending.remove(w)
            place(c["address"], w)
    return total - len(pending)


def status() -> dict:
    conf = load_conf()
    try:
        data = json.loads(SESSION.read_text())
    except (OSError, ValueError):
        data = {}
    wins = data.get("windows", [])
    return {"conf": conf, "time": data.get("time"), "count": len(wins),
            "workspaces": sorted({w["workspace"] for w in wins}),
            "apps": sorted({w["class"] for w in wins})}


def daemon() -> None:
    conf = load_conf()
    if conf.get("restore_on_login") == "on":
        time.sleep(3)       # que arranquen waybar, portales y el resto del exec-once
        restore()
    while True:
        conf = load_conf()
        try:
            interval = max(30, int(conf.get("interval", "120")))
        except ValueError:
            interval = 120
        time.sleep(interval)
        if load_conf().get("autosave") == "on":
            save(force=False)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "save":
        n = save()
        print(f"saved {n} windows" if n else "nothing to save")
    elif cmd == "restore":
        print(f"restored {restore()} windows")
    elif cmd == "daemon":
        daemon()
    elif cmd == "status":
        print(json.dumps(status()))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
