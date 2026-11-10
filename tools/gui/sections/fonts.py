"""Fonts & cursor (GUI): paridad con FontsView — fuente mono, tamaño, fuente de interfaz y tema de
íconos del tema activo (theme.json + theme-switch.sh), tema y tamaño del cursor (hyprctl setcursor,
gsettings y las variables XCURSOR_*), vista previa real (render_preview de la TUI, en segundo
plano) y dónde se aplica cada tamaño."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import _lib as L
from . import appearance as A

import threading

UI: dict = {}
STATE: dict = {"preview": None, "key": None, "busy": False}


def T():
    return L.tui_module("fonts")

DEFAULT_MONO, DEFAULT_SIZE = "Hack Nerd Font", 13
ICON_DIRS = [Path.home() / ".local/share/icons", Path.home() / ".icons", Path("/usr/share/icons")]


def mono_fonts() -> list[str]:
    fams = L.run(["fc-list", ":spacing=100", "family"]).stdout.splitlines()
    names = {f.split(",")[0].strip() for f in fams if f.strip()}
    nerd = sorted(n for n in names if "Nerd Font" in n and not re.search(r"Ita\b|Italic|Propo", n))
    return nerd or sorted(names)


def ui_fonts() -> list[str]:
    fams = L.run(["fc-list", ":", "family", "spacing"]).stdout.splitlines()
    names = {f.split(":")[0].split(",")[0].strip() for f in fams if "spacing=" not in f and f.strip()}
    return sorted(n for n in names if "Nerd Font" not in n and not n.startswith("."))


def icon_themes() -> list[str]:
    out = set()
    for base in ICON_DIRS:
        for d in base.iterdir() if base.is_dir() else []:
            if (d / "index.theme").is_file() and d.name not in ("default", "hicolor", "locolor") and not (d / "cursors").is_dir():
                out.add(d.name)
    return sorted(out)


def theme() -> dict:
    d = A.active_theme_dir()
    return json.loads((d / "theme.json").read_text()) if d else {}


def get() -> dict:
    th = theme()
    mono, ui, icons = mono_fonts(), ui_fonts(), icon_themes()
    cm, cu, ci = th.get("font_mono", DEFAULT_MONO), th.get("font_ui", "(unchanged)"), th.get("icon_theme", "(unchanged)")

    def opts(lst, cur, extra=()):
        return list(extra) + ([cur] if cur not in lst and cur not in extra else []) + lst

    def extra(key):
        return {"custom": key in th, "actions": [L.action(f"reset:{key}", "Reset")] if key in th else []}

    t = T()
    cur_theme, cur_size = t.env_get("XCURSOR_THEME") or "Adwaita", int(t.env_get("XCURSOR_SIZE") or 24)
    cursors = t.icon_themes(True)
    size = int(th.get("font_size") or DEFAULT_SIZE)
    info = {"mono": cm, "size": size, "ui_set": th.get("font_ui") or "", "icons": th.get("icon_theme") or "Papirus-Dark",
            "cursor": cur_theme, "cursor_size": cur_size}
    key = json.dumps(info, sort_keys=True)
    if STATE["key"] != key and not STATE["busy"]:
        STATE["busy"] = True
        threading.Thread(target=make_preview, args=(key, info), daemon=True).start()
    ui_now = info["ui_set"] or "(unchanged)"
    where = [L.info(f"w{i}", app, f"{pt} pt" + (f" · {note}" if note else "")) for i, (app, pt, note) in enumerate(
        [("kitty", size, "base"), ("waybar workspaces", size - 1, ""), ("waybar", size - 3, ""), ("dunst", size - 3, ""),
         ("GTK", size - 3, ui_now)])] + [L.info("wc", "cursor", f"{cur_size} px · {cur_theme}")]
    pv = [L.item("pv", "Preview", sub="Real fonts, icons and cursor" if STATE["preview"] else
                 ("rendering…" if STATE["busy"] else "preview needs python-pillow"), image=str(STATE["preview"] or ""))]
    return L.page("Fonts & cursor", "Saved in the active theme and applied to every app", [
        L.group("Preview", pv),
        L.group("Fonts", [
            L.choice("font_mono", "Monospace font", "kitty, dunst, waybar, TUIs", cm, opts(mono, cm), **extra("font_mono")),
            L.slider("font_size", "Font size", "Base size; waybar/GTK derive from it", th.get("font_size", DEFAULT_SIZE), 8, 24, 1, **extra("font_size")),
            L.choice("font_ui", "Interface font", "GTK apps", cu, opts(ui, cu, ["(unchanged)"]), **extra("font_ui")),
        ]),
        L.group("Icons", [L.choice("icon_theme", "Icon theme", "Thunar and GTK apps", ci, opts(icons, ci, ["(unchanged)"]), **extra("icon_theme"))]),
        L.group("Cursor", [L.choice("cursor", "Cursor theme", "Hyprland, GTK and XCURSOR_THEME", cur_theme, opts(cursors, cur_theme)),
                           L.slider("cursor_size", "Cursor size", "Pixels", cur_size, 16, 64, 1)]),
        L.group("Where it applies", where),
    ], refresh=2 if STATE["busy"] else 0)


def make_preview(key: str, info: dict) -> None:
    try:
        th = json.loads((L.CURRENT_THEME).read_text())
        STATE["preview"] = T().render_preview(info | {"ui": info["ui_set"] or T().gtk_font(),
                                                      "colors": [th.get(k, "#000000") for k in ("background", "foreground", "primary")]})
    except Exception:  # noqa: BLE001 - sin vista previa la sección anda igual
        STATE["preview"] = None
    STATE["key"], STATE["busy"] = key, False


def set_cursor(theme: str, size: str) -> dict:
    t = T()
    L.run(["hyprctl", "setcursor", theme, size])
    L.run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", theme])
    L.run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", size])
    t.env_set("XCURSOR_THEME", theme)
    t.env_set("XCURSOR_SIZE", size)
    return L.ok(f"Cursor: {theme} {size}px")


def _write(key: str, value) -> dict:
    d = A.active_theme_dir()
    if not d:
        return L.fail("No active theme")
    f = d / "theme.json"
    data = json.loads(f.read_text())
    if value is None or value == "(unchanged)":
        data.pop(key, None)
    else:
        data[key] = value
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, f)
    L.detach(["bash", str(A.THEME_SWITCH), d.name])
    return L.ok("Applied")


def set_value(key: str, value):
    t = T()
    if key == "cursor":
        return set_cursor(str(value), t.env_get("XCURSOR_SIZE") or "24")
    if key == "cursor_size":
        return set_cursor(t.env_get("XCURSOR_THEME") or "Adwaita", str(max(16, min(64, int(float(value))))))
    if key in ("font_mono", "font_size", "font_ui", "icon_theme"):
        return _write(key, int(float(value)) if key == "font_size" else value)
    return L.fail("Unknown field")


def act(key: str, text=None):
    if key.startswith("reset:"):
        return _write(key.split(":", 1)[1], None)
    return L.fail("Unknown action")
