"""Themes (GUI): paridad con ThemesView — lista de themes/*/theme.json con su preview; "Preview"
prueba un tema en vivo sin aplicarlo (scripts/theme-preview.sh; "Revert" o aplicar otro lo
deshace, y cerrar la página también), clic o "Apply" lo aplica a todas las apps (theme-switch.sh)."""

from __future__ import annotations

import json
import subprocess
import threading

from . import _lib as L

UI: dict = {}
THEMES_DIR = L.DOTFILES / "themes"
THEME_SWITCH = L.DOTFILES / "scripts" / "theme-switch.sh"
THEME_PREVIEW = L.DOTFILES / "scripts" / "theme-preview.sh"
STATE: dict = {"previewing": None}


def preview(arg: str) -> None:
    subprocess.run(["bash", str(THEME_PREVIEW), arg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def get() -> dict:
    try:
        active = json.loads((THEMES_DIR / "current_theme.json").read_text()).get("name")
    except (OSError, ValueError):
        active = None
    rows = []
    for d in sorted(THEMES_DIR.iterdir()):
        f = d / "theme.json"
        if d.name.startswith("_") or not f.is_file():
            continue
        try:
            th = json.loads(f.read_text())
        except ValueError:
            continue
        prev = d / "preview.png"
        on = th.get("name") == active
        pv = STATE["previewing"] == d.name
        acts = [] if on else [L.action(f"preview:{d.name}", "Previewing" if pv else "Preview"), L.action(f"apply:{d.name}", "Apply")]
        rows.append(L.item(f"apply:{d.name}", f"{th.get('icon', '')}  {th.get('name', d.name)}".strip(),
                           sub=f"{th.get('primary', '')} · {th.get('background', '')}" + (" · previewing" if pv else ""),
                           right="● active" if on else "", image=f"file://{prev}" if prev.exists() else "",
                           glyph="" if prev.exists() else "󰏘", on=on or pv, color=th.get("primary", ""), actions=acts))
    head = []
    if STATE["previewing"]:
        head = [L.group("Live preview", [L.button("revert", f"Previewing {STATE['previewing']}", "Not applied yet", "Revert")])]
    return L.page("Themes", f"Active: {active or '—'} · Preview tries a theme live, Apply keeps it", head + [L.group("Themes", rows)])


def set_value(key, value):
    return L.fail("Nothing to set")


def on_leave():
    if STATE["previewing"]:
        STATE["previewing"] = None
        threading.Thread(target=preview, args=("--revert",), daemon=True).start()


def act(key: str, text=None):
    op, _, name = key.partition(":")
    if op == "revert":
        if STATE["previewing"]:
            STATE["previewing"] = None
            threading.Thread(target=preview, args=("--revert",), daemon=True).start()
        return L.ok("Back to the active theme")
    if op == "preview" and (THEMES_DIR / name / "theme.json").is_file():
        STATE["previewing"] = name
        threading.Thread(target=preview, args=(name,), daemon=True).start()
        return L.ok(f"Previewing {name}")
    if op == "apply" and (THEMES_DIR / name / "theme.json").is_file():
        STATE["previewing"] = None
        subprocess.run(["bash", str(THEME_SWITCH), name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return L.ok(f"Applied {name}")
    return L.fail("Unknown action")
