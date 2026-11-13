"""Shortcuts (GUI): paridad con ShortcutsView — una pestaña por app (Hyprland, kitty, herdr,
Obsidian, LazyVim, Settings, Finances) con su cantidad, búsqueda por combo, descripción o
categoría (salta a la primera app con resultados), Settings/Finances agrupados por categoría,
editar el combo (validado y escrito por shortcuts_tui: temporal + os.replace; el keymap de las
TUIs con save_settings_key, vacío = default) y recargar. Los de solo lectura dicen por qué."""

from __future__ import annotations

import sys

from . import _lib as L

UI: dict = {}
STATE: dict = {"all": None}


def S():
    p = str(L.TOOLS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import shortcuts_tui
    return shortcuts_tui


def load() -> list:
    if STATE["all"] is None:
        STATE["all"] = S().load_all()
    return STATE["all"]


def matches(app: str) -> list:
    q = (UI.get("search") or "").strip().lower()
    return [(i, s) for i, s in enumerate(load()) if s.app == app and
            (not q or S().combo_matches(s, q) or q in (s.description or s.action).lower() or q in s.category.lower())]


def on_ui(name: str):
    if name == "search" and not matches(UI.get("tab") or S().APP_ORDER[0]):
        first = next((a for a in S().APP_ORDER if matches(a)), None)
        if first:
            UI["tab"] = first
    return None


def get() -> dict:
    s_ = S()
    tab = UI.get("tab") or s_.APP_ORDER[0]
    rows = matches(tab)
    groups: dict[str, list] = {}
    if tab in s_.KEYMAP_APPS:
        order = list(dict.fromkeys(s.category for _i, s in rows))
        rows.sort(key=lambda r: order.index(r[1].category))
    for i, s in rows:
        g = s.category if tab in s_.KEYMAP_APPS else tab
        groups.setdefault(g, []).append(L.item(f"e:{i}", s.display or s.combo, sub=(s.description or s.action)[:120]
                                               + ("" if s.editable else " · read only"),
                                               glyph="󰌌" if s.editable else "󰌾", on=s.editable,
                                               actions=[L.action(f"e:{i}", "Edit")] if s.editable else []))
    total = len(load())
    p = L.page("Shortcuts", f"{len(rows)} shortcuts in {tab} · {total} in total",
               [L.group("Shortcuts", [L.button("reload", "Reload", "Read the config files again", "Reload")])]
               + [L.group(k, v) for k, v in groups.items()])
    p.update(tabs=[{"key": a, "label": f"{a} · {len(matches(a))}"} for a in s_.APP_ORDER], tab=tab,
             search="Combo or description…")
    return p


def set_value(key, value):
    return L.fail("Unknown setting")


def act(key: str, text=None):
    s_ = S()
    op, _, arg = key.partition(":")
    if op == "reload":
        STATE["all"] = None
        load()
        return L.ok("Reloaded")
    if op != "e" or not arg.isdigit():
        return L.ok()
    allr = load()
    i = int(arg)
    if i >= len(allr):
        return L.fail("The list changed: reload")
    s = allr[i]
    if not s.editable:
        return L.fail(f"Read only: {s.reload_hint}")
    if s.app in s_.KEYMAP_APPS:
        cur = s_.load_keymap().get(s.action, s.default)
        hint = f"{s.description}\nDefault: {s.default}   ·   id: {s.action}\n{s_.FORMATS['Settings']}"
        if text is None:
            return L.form(key, f"Edit key · {s.section}", [{"name": "combo", "label": "KEYS", "text": cur}], hint=hint)
        combo = L.parse_form(text).get("combo", "")
        if err := s_.save_settings_key(s, combo, allr):
            return L.form(key, f"Edit key · {s.section}", [{"name": "combo", "label": "KEYS", "text": combo}], hint=hint, error=err)
        STATE["all"] = None
        return L.ok("Saved. " + ("Back to default" if not combo.strip() else s.reload_hint))
    hint = (f"Current: {s.combo}  ({s.description or s.action})\nShown as: {s.display or s.combo}\n"
            f"{s_.FORMATS.get(s.app, '')}")
    if text is None:
        return L.form(key, f"Edit shortcut · {s.app}", [{"name": "combo", "label": "COMBO", "text": s.combo}], hint=hint)
    combo = L.parse_form(text).get("combo", "").strip()
    if not combo or combo == s.combo:
        return L.ok()
    try:
        s_.save_shortcut(s, combo)
    except Exception as e:  # noqa: BLE001 - mostrar cualquier falla
        return L.fail(f"Error saving: {e}")
    STATE["all"] = None
    return L.ok(f"Saved. To apply: {s.reload_hint}")
