"""Modes (GUI): paridad con ModesView — "No mode" (deja el escritorio sin modo, sin tocar las
ventanas), aplicar un modo (scripts/mode-switch.sh), crear, renombrar (nombre + ícono; sigue activo
si lo estaba) y borrar modos (con confirmación), y por modo sus apps: agregar desde una ventana
abierta (toma la clase exacta o el título en terminales y el comando de su .desktop o del
proceso) o a mano, editar y quitar (con confirmación), con la validación de la TUI. modes.conf se
escribe con temporal + os.replace."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from . import _lib as L

UI: dict = {}
STATE: dict = {"pick": None, "wins": {}}


def M():
    p = str(L.TOOLS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import modes_tui
    return modes_tui


def save(c) -> None:
    m = M()
    m.CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = m.CONF.with_name(m.CONF.name + ".tmp")
    tmp.write_text("\n".join(c.lines) + "\n")
    os.replace(tmp, m.CONF)


def active() -> str:
    m = M()
    return m.STATE.read_text().strip() if m.STATE.exists() else ""


def pick_groups(mode: str) -> list:
    m = M()
    wins = m.windows()
    STATE["wins"] = {w["address"]: w for w in wins}
    rows = [L.button("manual", "Enter manually", "Name, command, match and workspace", "Enter")]
    rows += [L.item(f"win:{w['address']}", w["class"], sub=w["title"][:80], right=f"WS {w['workspace']['id']}", glyph="󰖯") for w in wins]
    return [L.group(f"Add app to {mode}", [L.button("back", "Back", "", "Back")]), L.group("Pick an open window", rows)]


def get() -> dict:
    m = M()
    c = m.Conf()
    if STATE["pick"] and STATE["pick"] in c.modes():
        return L.page("Modes", f"Add an app to {STATE['pick']}", pick_groups(STATE["pick"]))
    STATE["pick"] = None
    cur = active()
    names = c.modes()
    top = [L.item("none", f"{m.NONE_ICON}  No mode", sub="No mode applied; windows stay where they are", on=cur not in names,
                  right="● active" if cur not in names else "", actions=[] if cur not in names else [L.action("none", "Use")]),
           L.button("newmode", "New mode", "Name and icon", "Create")]
    groups = [L.group("Modes", top)]
    for name in names:
        on = name == cur
        apps = c.apps(name)
        rows = [L.item(f"apply:{name}", f"{c.icon(name)}  {name}", sub=f"{len(apps)} apps · " + ("active" if on else "click to apply"),
                       on=on, right="● active" if on else "",
                       actions=[L.action(f"apply:{name}", "Apply"), L.action(f"rename:{name}", "Rename"), L.action(f"addapp:{name}", "Add app"),
                                L.action(f"delmode:{name}", "Delete", True)])]
        for a in apps:
            rows.append(L.item(f"edit:{a.line}", a.name or Path(a.cmd.split()[0]).name if a.cmd else a.name, sub=f"{a.match} · {a.cmd}"[:100],
                               right=f"WS {a.ws}", glyph="󰀻",
                               actions=[L.action(f"edit:{a.line}", "Edit"), L.action(f"rmapp:{a.line}", "Remove", True)]))
        if not apps:
            rows.append(L.info(f"noapps:{name}", "No apps yet", "Add app picks an open window"))
        groups.append(L.group(name, rows))
    return L.page("Modes", "Desktop modes · each app goes to its workspace", groups, refresh=10)


def set_value(key, value):
    return L.fail("Unknown setting")


def mode_form(key: str, title: str, name: str, icon: str, error: str = "") -> dict:
    return L.form(key, title, [{"name": "name", "label": "NAME", "text": name}, {"name": "icon", "label": "ICON (NERD FONT)", "text": icon}],
                  error=error)


def mode_check(c, name: str, orig: str = "") -> str:
    if not name:
        return "The name is missing"
    if name != orig and name in c.modes():
        return f"There is already a mode called {name}"
    return ""


def app_fields(v: dict) -> list:
    return [{"name": "name", "label": "NAME", "text": v.get("name", "")}, {"name": "cmd", "label": "COMMAND", "text": v.get("cmd", "")},
            {"name": "match", "label": "MATCH (class:<regex> or title:<regex>, see hyprctl clients)", "text": v.get("match", "")},
            {"name": "ws", "label": "WORKSPACE (1-9)", "text": v.get("ws", "")}]


def app_check(v: dict) -> str:
    m = M()
    if not m.clean(v.get("name", "")) or not m.clean(v.get("cmd", "")):
        return "The name or the command is missing"
    if not re.match(r"^(class|title):.+", v.get("match", "")):
        return "The match starts with class: or title:"
    if not re.fullmatch(r"[1-9]", v.get("ws", "")):
        return "The workspace is a number from 1 to 9"
    return ""


def app_save(c, mode: str, v: dict, line: int | None) -> dict:
    m = M()
    vals = (v["ws"], v["match"].replace("|", "."), m.clean(v["cmd"]), m.clean(v["name"]))
    if line is None:
        c.add_app(mode, *vals)
    else:
        c.set_app(line, *vals)
    save(c)
    STATE["pick"] = None
    return L.ok(f"{vals[3]} → workspace {vals[0]}")


def from_window(w: dict) -> dict:
    m = M()
    cls, title = w["class"], w["title"]
    if m.TERMINALS.match(cls):
        match, name = f"title:^{re.escape(title)}$", title
    else:
        match, name = f"class:^{re.escape(cls)}$", cls
    info = None if m.TERMINALS.match(cls) else m.desktop_for_class(cls)
    if info:
        cmd, nm = info
        name = nm or name
    else:
        try:
            cmd = Path(f"/proc/{w['pid']}/cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
        except OSError:
            cmd = ""
    return {"match": match.replace("|", "."), "cmd": cmd, "name": name, "ws": ""}


def act(key: str, text=None):
    m = M()
    c = m.Conf()
    op, _, arg = key.partition(":")
    if op == "back":
        STATE["pick"] = None
        return L.ok()
    if op == "none":
        try:
            m.STATE.unlink()
        except FileNotFoundError:
            return L.ok("No mode was active")
        return L.ok("No mode active")
    if op == "apply" and arg in c.modes():
        L.detach(["bash", str(m.MODE_SWITCH), arg])
        return {"ok": True, "msg": f"Applying {arg}…", "close": True}
    if op == "newmode":
        if text is None:
            return mode_form("newmode", "New mode", "", m.DEFAULT_ICON)
        f = L.parse_form(text)
        name, icon = m.clean(f.get("name", "")), m.clean(f.get("icon", ""))
        if err := mode_check(c, name):
            return mode_form("newmode", "New mode", name, icon, err)
        c.add_mode(name, icon or m.DEFAULT_ICON)
        save(c)
        return L.ok(f"Mode {name} created: Add app adds its apps")
    if op == "rename" and arg in c.modes():
        if text is None:
            return mode_form(key, f"Rename {arg}", arg, c.icon(arg))
        f = L.parse_form(text)
        name, icon = m.clean(f.get("name", "")), m.clean(f.get("icon", ""))
        if err := mode_check(c, name, arg):
            return mode_form(key, f"Rename {arg}", name, icon, err)
        c.rename(arg, name, icon)
        save(c)
        if active() == arg:
            m.STATE.write_text(name + "\n")
        return L.ok(f"Renamed to {name}")
    if op == "delmode" and arg in c.modes():
        if not L.yes(text):
            return L.confirm(key, "Delete mode", f"Delete mode {arg}? Open apps are not closed.", ok_label="Delete")
        c.delete_mode(arg)
        save(c)
        return L.ok(f"{arg} deleted")
    if op == "addapp" and arg in c.modes():
        STATE["pick"] = arg
        return L.ok()
    if op in ("manual", "win") and STATE["pick"]:
        mode = STATE["pick"]
        if op == "manual":
            return L.form("newapp", f"Add app to {mode}", app_fields({}))
        w = STATE["wins"].get(arg)
        return L.form("newapp", f"Add app to {mode}", app_fields(from_window(w))) if w else L.ok()
    if op == "newapp" and STATE["pick"]:
        v = L.parse_form(text)
        if err := app_check(v):
            return L.form("newapp", f"Add app to {STATE['pick']}", app_fields(v), error=err)
        return app_save(c, STATE["pick"], v, None)
    if op in ("edit", "rmapp") and arg.isdigit():
        line = int(arg)
        a = next((a for mode in c.modes() for a in c.apps(mode) if a.line == line), None)
        if not a:
            return L.fail("That app moved: reloading")
        if op == "rmapp":
            if not L.yes(text):
                return L.confirm(key, "Remove app", f"Remove {a.name} from mode {a.mode}?", ok_label="Remove")
            c.remove_line(line)
            save(c)
            return L.ok(f"{a.name} removed")
        cur = {"ws": a.ws, "match": a.match, "cmd": a.cmd, "name": a.name}
        if text is None:
            return L.form(key, f"Edit {a.name}", app_fields(cur))
        v = L.parse_form(text)
        if err := app_check(v):
            return L.form(key, f"Edit {a.name}", app_fields(v), error=err)
        return app_save(c, a.mode, v, line)
    return L.ok()
