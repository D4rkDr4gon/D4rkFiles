#!/usr/bin/env python3
"""
bridge.py — puente entre la GUI (Quickshell/QML) y los backends Python.

QML lo invoca con `Process` y lee JSON por stdout; no tiene dependencias
pesadas (nada de Textual). Cada comando reusa el mismo estado que la TUI para
que las dos versiones compartan favoritas, historial, etc.

    bridge.py bump <desktop-id>     suma un uso al historial del launcher
    bridge.py fav <nombre>          agrega/saca una favorita (~/.config/dotfiles/launcher-favorites.txt)
    bridge.py settings-menu         categorías y secciones de Settings (JSON)
    bridge.py section <id> get|set|act ...   página de una sección de Settings (tools/gui/sections/<id>.py)
    bridge.py session-mode [tui|gui]                 lee o cambia el modo de sesión
    bridge.py profile               nombre del perfil de Settings (common.display_name)
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[2])
CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dotfiles"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "dotfiles"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uimode  # noqa: E402

SETTINGS_SRC = DOTFILES / "tools" / "settings" / "settings_tui.py"
THEMES_DIR = DOTFILES / "themes"
THEME_SWITCH = DOTFILES / "scripts" / "theme-switch.sh"
FAVORITES = Path(os.environ.get("LAUNCHER_FAVORITES") or CONF_DIR / "launcher-favorites.txt")
HISTORY = Path(os.environ.get("LAUNCHER_HISTORY") or STATE_DIR / "launcher-history.json")


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def bump(key: str) -> None:
    """Mismo formato que launcher_tui.bump_history: {id: [usos, último uso]}."""
    try:
        h = json.loads(HISTORY.read_text())
        h = h if isinstance(h, dict) else {}
    except (OSError, ValueError):
        h = {}
    count, _ = h.get(key, [0, 0])
    h[key] = [count + 1, int(time.time())]
    _atomic(HISTORY, json.dumps(h))


def toggle_favorite(name: str) -> None:
    """Agrega o saca el Name del .desktop, conservando comentarios y orden."""
    lines = FAVORITES.read_text().splitlines() if FAVORITES.exists() else []
    keep = [ln for ln in lines if ln.strip().lower() != name.strip().lower()]
    if len(keep) == len(lines):
        keep.append(name.strip())
    _atomic(FAVORITES, "\n".join(keep) + "\n")


def _literal(name: str):
    """Valor de una constante literal de settings_tui.py sin importarlo (importarlo
    carga Textual y todas las secciones): el menú y los campos de forma tienen una
    sola fuente, la de la TUI."""
    tree = ast.parse(SETTINGS_SRC.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def settings_menu() -> list:
    gui = set(gui_sections())
    return [{"category": cat, "sections": [{"id": i, "icon": ic, "label": lb, "gui": i in gui} for i, ic, lb in secs]}
            for cat, secs in _literal("CATEGORIES")]


def gui_sections() -> list[str]:
    """Secciones de Settings que ya tienen GUI: un módulo en tools/gui/sections/."""
    return sorted(p.stem for p in (Path(__file__).resolve().parent / "sections").glob("*.py")
                  if not p.stem.startswith("_"))


def ws_list() -> list[dict]:
    """Workspaces 1..N con las apps que tienen (selector del lanzador)."""
    import re
    try:
        n = int(re.search(r"^# count: *(\d+)", (CONF_DIR / "hypr" / "workspaces.conf").read_text(), re.M).group(1))
    except (OSError, AttributeError, ValueError):
        n = 9
    def hc(*a):
        try:
            return json.loads(subprocess.run(["hyprctl", *a, "-j"], capture_output=True, text=True, timeout=3).stdout)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            return []
    apps: dict[int, list[str]] = {}
    for c in hc("clients"):
        apps.setdefault(c.get("workspace", {}).get("id", 0), []).append(c.get("class") or c.get("title") or "?")
    cur = (hc("activeworkspace") or {}).get("id", 0) if isinstance(hc("activeworkspace"), dict) else 0
    return [{"label": f"Workspace {i}", "sub": ", ".join(dict.fromkeys(apps.get(i, []))) or "empty", "glyph": "󰍹" if i == cur else "󰍺",
             "ws": str(i)} for i in range(1, n + 1)]


UI_STATE: dict[str, dict] = {}


def section_result(sid: str, op: str, args: list):
    """get | set <clave> <json> | act <clave> [texto]  →  objeto JSON-able."""
    import importlib
    if sid not in gui_sections():
        return {"ok": False, "msg": f"no GUI for section {sid}"}
    mod = importlib.import_module(f"sections.{sid}")
    ui = UI_STATE.setdefault(sid, {})
    mod.UI = ui                                   # pestaña y búsqueda actuales de la página
    if op == "set" and len(args) == 2 and args[0].startswith("__"):
        ui[args[0][2:]] = json.loads(args[1]) if isinstance(args[1], str) else args[1]
        hook = getattr(mod, "on_ui", None)
        return (hook(args[0][2:]) if hook else None) or {"ok": True, "msg": ""}
    if op == "leave":                             # la página dejó de mostrar la sección
        hook = getattr(mod, "on_leave", None)
        return (hook() if hook else None) or {"ok": True, "msg": ""}
    if op == "get":
        res = mod.get()
        if isinstance(res, dict) and "groups" in res:
            res["groups"] = [g for g in res["groups"] if g.get("rows")]
    elif op == "set" and len(args) == 2:
        res = mod.set_value(args[0], json.loads(args[1]) if isinstance(args[1], str) else args[1])
    elif op == "act" and args:
        res = mod.act(args[0], args[1] if len(args) > 1 else None)
    else:
        return {"ok": False, "msg": "bad section call"}
    return res if res is not None else {"ok": True}


def section_call(sid: str, op: str, args: list[str]) -> None:
    print(json.dumps(section_result(sid, op, args), ensure_ascii=False))


def serve() -> None:
    """Proceso persistente para la GUI: una petición JSON por línea de stdin
    ({id, section, op, args}) → una respuesta JSON por línea de stdout
    ({id, section, op, res}). Cada petición va en su hilo (nmcli y compañía
    pueden tardar) y los módulos quedan importados: cambiar de sección es instantáneo."""
    import threading
    lock = threading.Lock()

    def emit(ev: dict) -> None:
        with lock:
            sys.stdout.write(json.dumps({"event": ev}, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    from sections import _lib
    _lib.EMIT = emit

    def handle(req: dict) -> None:
        try:
            res = section_result(req["section"], req["op"], req.get("args", []))
        except Exception as e:  # nunca matar el servidor por un módulo
            res = {"ok": False, "msg": f"{type(e).__name__}: {e}"[:160]}
        with lock:
            sys.stdout.write(json.dumps({"id": req.get("id"), "section": req.get("section"), "op": req.get("op"),
                                         "res": res}, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    for line in sys.stdin:
        try:
            req = json.loads(line)
        except ValueError:
            continue
        threading.Thread(target=handle, args=(req,), daemon=True).start()


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "bump" and args:
        bump(args[0])
    elif cmd == "fav" and args:
        toggle_favorite(args[0])
    elif cmd == "settings-menu":
        print(json.dumps(settings_menu()))
    elif cmd == "section" and len(args) >= 2:
        section_call(args[0], args[1], args[2:])
    elif cmd == "pick-color":
        from sections import colorpicker
        colorpicker.pick_cli()
    elif cmd == "profile":
        from sections import _lib
        print(_lib.settings_common().display_name())
    elif cmd == "ws-list":
        print(json.dumps(ws_list(), ensure_ascii=False))
    elif cmd == "serve":
        serve()
    elif cmd == "session-mode":
        if args:
            uimode.set_mode(args[0])
            uimode.apply_daemon(args[0])
        print(uimode.get_mode())
    else:
        sys.exit(__doc__)
