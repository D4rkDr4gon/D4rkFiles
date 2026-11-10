"""Startup apps: lista `autostart` de hypr/hyprland.lua (prender/apagar, correr ahora)."""

from __future__ import annotations

import os
import re

from . import _lib as L

HYPR_LUA = L.CONFIG / "hypr" / "hyprland.lua"
HYPR_DISPATCH = str(L.CONFIG / "hypr" / "scripts" / "hypr-dispatch")
LINE = re.compile(r'^(?P<off>--off\s+)?"(?P<cmd>(?:[^"\\]|\\.)*)",\s*(?:--\s*(?P<note>.*))?$')
CRITICAL = ("waybar", "dunst", "hyprpaper", "hyprland-session-init", "wl-paste", "swayosd", "quickshell")


def entries() -> list[dict]:
    out, inside = [], False
    for i, line in enumerate(HYPR_LUA.read_text().splitlines()):
        if "local autostart = {" in line:
            inside = True
            continue
        if inside and line.strip() == "}":
            break
        m = LINE.match(line.strip()) if inside else None
        if m:
            out.append({"line": i, "on": not m.group("off"), "cmd": m.group("cmd").strip(), "note": (m.group("note") or "").strip()})
    return out


def set_line(line: int, on: bool) -> None:
    lines = HYPR_LUA.read_text().splitlines()
    raw = lines[line]
    indent = raw[:len(raw) - len(raw.lstrip())]
    body = re.sub(r"^--off\s+", "", raw.strip())
    lines[line] = indent + (body if on else f"--off {body}")
    tmp = HYPR_LUA.with_suffix(".lua.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, HYPR_LUA)


def get() -> dict:
    rows = []
    for e in entries():
        crit = any(c in e["cmd"] for c in CRITICAL)
        rows.append(L.item(f"t:{e['line']}", e["cmd"].replace("$HOME", "~")[:90], sub=e["note"] + (" · part of the desktop" if crit else ""),
                           glyph="●" if e["on"] else "○", on=e["on"], right="on" if e["on"] else "off",
                           actions=[L.action(f"run:{e['line']}", "Run now")]))
    on = sum(r["on"] for r in rows)
    return L.page("Startup apps", f"{on} of {len(rows)} on · changes apply at the next login", [L.group("Autostart", rows)])


def set_value(key, value):
    return L.fail("Unknown field")


def act(key: str, text=None):
    op, _, n = key.partition(":")
    es = {str(e["line"]): e for e in entries()}
    e = es.get(n)
    if not e:
        return L.fail("Entry moved — reloading")
    if op == "t":
        if e["on"] and any(c in e["cmd"] for c in CRITICAL):
            if not L.yes(text):
                return L.confirm(key, "Turn off at login", f"{e['cmd']}\nis part of the desktop (bar, notifications, "
                                 "wallpaper, clipboard or session). Turn it off anyway?", ok_label="Turn off")
        set_line(e["line"], not e["on"])
        return L.ok(f"{'Off' if e['on'] else 'On'} at next login")
    if op == "run":
        L.run([HYPR_DISPATCH, "exec", e["cmd"]])
        return L.ok(f"Started: {e['cmd'].split()[0]}")
    return L.ok()
