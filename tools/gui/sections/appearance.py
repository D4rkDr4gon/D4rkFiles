"""Appearance: modo de sesión + forma del tema activo (mismo backend que la TUI)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import _lib as L

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import uimode  # noqa: E402

THEMES_DIR = L.DOTFILES / "themes"
THEME_SWITCH = L.DOTFILES / "scripts" / "theme-switch.sh"
TUI_SETTINGS = L.SETTINGS_SRC
CENTER = Path.home() / ".config" / "waybar" / "scripts" / "center-tui-launch.sh"


def active_theme_dir() -> Path | None:
    try:
        name = json.loads((THEMES_DIR / "current_theme.json").read_text()).get("name")
    except (OSError, ValueError):
        return None
    for d in sorted(THEMES_DIR.iterdir()):
        f = d / "theme.json"
        try:
            if f.is_file() and json.loads(f.read_text()).get("name") == name:
                return d
        except ValueError:
            continue
    return None


def get() -> dict:
    d = active_theme_dir()
    data = json.loads((d / "theme.json").read_text()) if d else {}
    groups = [L.group("Session", [L.choice(
        "ui_mode", "Session mode",
        "TUI = terminal apps · GUI = own windows. Switching to TUI closes this window",
        uimode.get_mode(), uimode.MODES)])]
    for gname, fields in L.literal("SHAPE_FIELDS"):
        rows = []
        for key, name, kind, default, lim, desc in fields:
            custom = key in data
            extra = {"custom": custom, "actions": [L.action(f"reset:{key}", "Reset")] if custom else []}
            val = data.get(key, default)
            if kind == "bool":
                rows.append(L.toggle(key, name, desc, val in (True, "true"), **extra))
            elif kind == "choice":
                rows.append(L.choice(key, name, desc, str(val), lim, **extra))
            else:
                lo, hi = lim
                step = 1 if kind == "int" else max(round((hi - lo) / 100, 4), 0.01)
                rows.append(L.slider(key, name, desc, val, lo, hi, step, **extra))
        groups.append(L.group(gname, rows))
    sub = f"Theme: {d.name} · saved in its theme.json and applied to every app" if d else "No active theme"
    return L.page("Appearance", sub, groups)


def _write(key: str, value) -> dict:
    valid = {f[0] for _g, fs in L.literal("SHAPE_FIELDS") for f in fs}
    d = active_theme_dir()
    if not d or key not in valid:
        return L.fail("Unknown field or no active theme")
    f = d / "theme.json"
    data = json.loads(f.read_text())
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, f)
    subprocess.run(["bash", str(THEME_SWITCH), d.name], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, start_new_session=True)
    return L.ok("Applied")


def set_value(key: str, value):
    if key == "ui_mode":
        if value == "tui":
            # apagar el daemon cierra esta ventana: el cambio y la reapertura van desprendidos
            L.detach(["bash", "-c",
                      f"python3 '{Path(uimode.__file__)}' tui; sleep 0.5; "
                      f"'{CENTER}' settings Settings python3 '{TUI_SETTINGS}' --section appearance"])
            return L.ok("Switching to TUI…")
        if not uimode.gui_available():
            return L.fail("GUI mode needs Quickshell")
        uimode.set_mode(value)
        uimode.apply_daemon(value)
        return L.ok("Session mode: GUI")
    return _write(key, value)


def act(key: str, text=None):
    if key.startswith("reset:"):
        return _write(key.split(":", 1)[1], None)
    return L.fail("Unknown action")
