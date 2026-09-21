#!/usr/bin/env python3
"""
shortcuts_tui.py — Cheatsheet de shortcuts, ver + editar.

Junta los atajos de Hyprland, kitty, herdr, Qtile (X11) y los defaults de
LazyVim en una tab por app (no una lista
única — con 140+ atajos mezclados se hacía ilegible), y permite reasignar
el combo de cualquiera de los editables (reescribe el archivo real de
config; LazyVim queda solo-lectura, son defaults del plugin instalado, no
un archivo de este repo).

A propósito, "editar" solo reasigna la COMBINACIÓN de teclas — nunca la
acción/comando que dispara (eso sigue siendo un cambio de código, no un
rebind, y es mucho más riesgoso de tocar a ciegas desde una TUI).

Atajo: SUPER+K (Hyprland y Qtile) abre esto en una ventana flotante de
kitty (ver config/waybar/scripts/float-tui-launch.sh).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, TabbedContent, TabPane

# Raíz del repo: DOTFILES_DIR si está exportado; si no, dos niveles arriba de
# este archivo (tools/), que resuelve también los symlinks.
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
CONFIG = DOTFILES / "config"
HYPR_CONF = CONFIG / "hypr" / "hyprland.conf"
HYPRSHELL_CONF = CONFIG / "hyprshell" / "config.ron"
KITTY_CONF = CONFIG / "kitty" / "kitty.conf"
# config.toml de herdr se genera desde la plantilla: los atajos se editan en el .tpl.
HERDR_CONF = CONFIG / "herdr" / "config.toml.tpl"
QTILE_KEYS = CONFIG / "qtile" / "modules" / "keys.py"
# Los keymaps custom del usuario (config/nvim/lua/config/keymaps.lua, en este
# repo) están vacíos hoy — los shortcuts "de LazyVim" que la gente realmente
# usa a diario (<leader>ff, <leader>e, etc.) son los defaults que trae el
# propio plugin, instalados acá, NO versionados en dotfiles.
LAZYVIM_DEFAULT_KEYMAPS = Path.home() / ".local/share/nvim/lazy/LazyVim/lua/lazyvim/config/keymaps.lua"


def _hex_blend(c1: str, c2: str, pct: int) -> str:
    """Réplica de hex_blend() en scripts/lib/theme.sh."""
    c1, c2 = c1.lstrip("#"), c2.lstrip("#")
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r = (r1 * pct + r2 * (100 - pct)) // 100
    g = (g1 * pct + g2 * (100 - pct)) // 100
    b = (b1 * pct + b2 * (100 - pct)) // 100
    return f"#{r:02x}{g:02x}{b:02x}"


def _load_theme() -> dict:
    defaults = {
        "primary": "#c62828", "secondary": "#8e1a1a",
        "background": "#0a0a0a", "foreground": "#c5c8c6",
        "chip_battery": "#141414", "chip_bluetooth": "#1e1e1e",
        "chip_wlan": "#2a0d0d", "chip_audio": "#3a1515",
        "status_ok": "#5cb85c", "status_warn": "#f9a825", "status_error": "#ff4444",
    }
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    theme_file = state / "dotfiles" / "current_theme.json"
    try:
        data = json.loads(theme_file.read_text())
        defaults.update({k: v for k, v in data.items() if k in defaults})
    except (OSError, json.JSONDecodeError):
        pass
    defaults["text_muted"] = _hex_blend(defaults["foreground"], defaults["background"], 45)
    return defaults


THEME = _load_theme()


@dataclass
class Shortcut:
    app: str
    combo: str
    action: str
    description: str
    # Todo lo necesario para reescribir SOLO el combo en el archivo real,
    # sin tocar el resto de la línea/bloque.
    file: Path
    line_no: int  # 1-indexed
    rewrite: Callable[[str, str], str]  # (línea original, combo nuevo) -> línea nueva
    reload_hint: str
    editable: bool = True


# ── Parsers ──────────────────────────────────────────────────────────────

def parse_hyprland() -> list[Shortcut]:
    out = []
    if not HYPR_CONF.exists():
        return out
    lines = HYPR_CONF.read_text().splitlines()
    pat = re.compile(r"^(bind[a-z]*)\s*=\s*([^,]*),\s*([^,]+),\s*(.+)$")
    for i, line in enumerate(lines, start=1):
        m = pat.match(line.strip())
        if not m:
            continue
        directive, mods, key, rest = m.groups()
        action, _, comment = rest.partition("#")
        combo = f"{mods.strip()}, {key.strip()}".strip(", ")
        combo = combo.replace("$mainMod", "SUPER")

        def rewrite(orig_line: str, new_combo: str, _directive=directive) -> str:
            new_mods, _, new_key = new_combo.rpartition(",")
            new_mods = new_mods.strip().upper().replace("SUPER", "$mainMod") or ""
            new_key = new_key.strip()
            return re.sub(
                rf"^({re.escape(_directive)}\s*=\s*)[^,]*,\s*[^,]+,",
                lambda mm: f"{mm.group(1)}{new_mods}, {new_key},",
                orig_line,
                count=1,
            )

        out.append(Shortcut(
            app="Hyprland", combo=combo, action=action.strip(),
            description=comment.strip(), file=HYPR_CONF, line_no=i,
            rewrite=rewrite, reload_hint="hyprctl reload",
        ))

    # Atajos que NO son `bind =` en hyprland.conf: los gestos (`gesture =`) y
    # los que registra hyprshell en runtime (hyprshell/config.ron). Solo
    # lectura: el parser de arriba no sabe reescribirlos.
    def _ro(combo: str, action: str, desc: str, file: Path, hint: str) -> None:
        out.append(Shortcut(
            app="Hyprland", combo=combo, action=action, description=desc,
            file=file, line_no=0, rewrite=lambda o, n: o, editable=False,
            reload_hint=hint,
        ))

    hs_hint = "no editable acá — editar hyprshell/config.ron (se recarga solo)"
    _ro("SUPER, W", "hyprshell overview", "overview de workspaces + launcher", HYPRSHELL_CONF, hs_hint)
    _ro("ALT, Tab", "hyprshell switch", "cambiar ventana con previews (soltar Alt confirma)", HYPRSHELL_CONF, hs_hint)
    gs_hint = "no editable acá — editar las líneas `gesture =` de config/hypr/hyprland.conf"
    _ro("3 dedos ← →", "workspace anterior/siguiente", "gesto de touchpad, sigue el dedo", HYPR_CONF, gs_hint)
    _ro("3 dedos ↑", "hyprshell overview", "gesto de touchpad", HYPR_CONF, gs_hint)
    return out


def parse_kitty() -> list[Shortcut]:
    out = []
    if not KITTY_CONF.exists():
        return out
    lines = KITTY_CONF.read_text().splitlines()
    pat = re.compile(r"^map\s+(\S+)\s+(.+)$")
    for i, line in enumerate(lines, start=1):
        m = pat.match(line.strip())
        if not m:
            continue
        combo, action = m.groups()

        def rewrite(orig_line: str, new_combo: str) -> str:
            return re.sub(r"^(map\s+)\S+", lambda mm: f"{mm.group(1)}{new_combo}", orig_line, count=1)

        out.append(Shortcut(
            app="kitty", combo=combo, action=action.strip(), description=action.strip(),
            file=KITTY_CONF, line_no=i, rewrite=rewrite,
            reload_hint="reabrir la terminal (o ctrl+shift+F5 en kitty)",
        ))
    return out


def parse_herdr() -> list[Shortcut]:
    out = []
    if not HERDR_CONF.exists():
        return out
    lines = HERDR_CONF.read_text().splitlines()
    in_keys, in_command_block = False, False
    cmd_key_line = None
    cmd_desc = ""
    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == "[keys]":
            in_keys, in_command_block = True, False
            continue
        if stripped == "[[keys.command]]":
            in_command_block = True
            cmd_key_line, cmd_desc = None, ""
            continue
        if stripped.startswith("[") and stripped not in ("[[keys.command]]",):
            in_keys = in_command_block = False
            continue

        if in_command_block:
            m_key = re.match(r'^key\s*=\s*"([^"]+)"', stripped)
            m_desc = re.match(r'^description\s*=\s*"([^"]*)"', stripped)
            if m_key:
                cmd_key_line = i
                combo = m_key.group(1)

                def rewrite(orig_line: str, new_combo: str) -> str:
                    return re.sub(r'^(key\s*=\s*)"[^"]+"', lambda mm: f'{mm.group(1)}"{new_combo}"', orig_line, count=1)

                out.append(Shortcut(
                    app="herdr", combo=combo, action="[[keys.command]]",
                    description="", file=HERDR_CONF, line_no=i, rewrite=rewrite,
                    reload_hint="theme <tema activo> (regenera config.toml) y herdr server reload-config",
                ))
                # la descripción viene en una línea posterior del mismo bloque;
                # se completa cuando aparezca (ver abajo, referencia al último item)
            if m_desc and out and out[-1].file == HERDR_CONF and not out[-1].description:
                out[-1].description = m_desc.group(1)
            continue

        if in_keys:
            m = re.match(r'^(\w+)\s*=\s*"([^"]+)"\s*$', stripped)
            if m and m.group(1) != "prefix":
                name, combo = m.groups()

                def rewrite(orig_line: str, new_combo: str, _name=name) -> str:
                    return re.sub(rf'^({re.escape(_name)}\s*=\s*)"[^"]+"', lambda mm: f'{mm.group(1)}"{new_combo}"', orig_line, count=1)

                out.append(Shortcut(
                    app="herdr", combo=combo, action=name, description=name.replace("_", " "),
                    file=HERDR_CONF, line_no=i, rewrite=rewrite,
                    reload_hint="theme <tema activo> (regenera config.toml) y herdr server reload-config",
                ))
            # los que son lista (next_tab = ["prefix+n", ...]) se muestran
            # solo-lectura: editar un alternate a mano es más seguro
            m_list = re.match(r'^(\w+)\s*=\s*\[(.+)\]\s*$', stripped)
            if m_list and m_list.group(1) != "prefix":
                name, items = m_list.groups()
                out.append(Shortcut(
                    app="herdr", combo=items.replace('"', ""), action=name,
                    description=f"{name.replace('_', ' ')} (alternates, editar a mano)",
                    file=HERDR_CONF, line_no=i, rewrite=lambda o, n: o, editable=False,
                    reload_hint="theme <tema activo> (regenera config.toml) y herdr server reload-config",
                ))
    return out


def parse_qtile() -> list[Shortcut]:
    out = []
    if not QTILE_KEYS.exists():
        return out
    lines = QTILE_KEYS.read_text().splitlines()
    pat = re.compile(r'^(\s*Key\(\[)([^\]]*)(\],\s*)"([^"]+)"(,\s*.+?,\s*desc\s*=\s*")([^"]*)("\),?)\s*$')
    for i, line in enumerate(lines, start=1):
        m = pat.match(line)
        if not m:
            continue
        prefix, mods, mid, key, mid2, desc, suffix = m.groups()
        combo = f"{mods.strip()}, {key}".replace('"', "").strip(", ")

        def rewrite(orig_line: str, new_combo: str) -> str:
            new_mods_raw, _, new_key = new_combo.rpartition(",")
            new_key = new_key.strip()
            # Cada token de modificador que no sea la variable `mod` necesita
            # comillas (es un string de libqtile, ej. "shift") — sin esto
            # queda un identificador Python suelto (NameError al recargar).
            tokens = [t.strip().strip('"') for t in new_mods_raw.split(",") if t.strip()]
            new_mods = ", ".join(t if t == "mod" else f'"{t}"' for t in tokens)
            return re.sub(
                r'^(\s*Key\(\[)([^\]]*)(\],\s*)"([^"]+)"',
                lambda mm: f'{mm.group(1)}{new_mods}{mm.group(3)}"{new_key}"',
                orig_line, count=1,
            )

        out.append(Shortcut(
            app="Qtile", combo=combo, action=desc, description=desc,
            file=QTILE_KEYS, line_no=i, rewrite=rewrite,
            reload_hint="qtile cmd-obj -o cmd -f reload_config",
        ))
    return out


def parse_lazyvim() -> list[Shortcut]:
    """Solo lectura: son defaults del plugin instalado (LazyVim/LazyVim),
    no un archivo de este repo — no hay dónde "guardar" un rebind de forma
    persistente sin correr el riesgo de que una actualización del plugin
    lo pise. Para agregar/pisar un keymap propio de verdad, se edita
    lazy-nvim/lua/config/keymaps.lua (hoy vacío) a mano.

    Parsea llamadas `map(MODE, "LHS", RHS, { ..., desc = "..." })` — RHS
    puede ser un string o una función multilínea, no hace falta parsearlo
    para el cheatsheet (solo mode/lhs/desc). El lookahead negativo evita
    que un `map(...)` sin `desc` le robe la descripción al siguiente.
    """
    out = []
    if not LAZYVIM_DEFAULT_KEYMAPS.exists():
        return out
    text = LAZYVIM_DEFAULT_KEYMAPS.read_text()
    pat = re.compile(
        r'\bmap\(\s*((?:\{[^}]*\})|"[^"]*")\s*,\s*"((?:[^"\\]|\\.)*)"\s*,'
        r'(?:(?!\bmap\().)*?desc\s*=\s*"((?:[^"\\]|\\.)*)"',
        re.DOTALL,
    )
    for m in pat.finditer(text):
        mode_raw, lhs, desc = m.groups()
        if mode_raw.startswith("{"):
            mode = "/".join(re.findall(r'"([^"]+)"', mode_raw))
        else:
            mode = mode_raw.strip('"')
        out.append(Shortcut(
            app="LazyVim", combo=lhs, action=f"[{mode}]", description=desc,
            file=LAZYVIM_DEFAULT_KEYMAPS, line_no=0, rewrite=lambda o, n: o, editable=False,
            reload_hint="no editable — son defaults del plugin, agregar overrides en config/nvim/lua/config/keymaps.lua",
        ))
    return out


APP_ORDER = ["Hyprland", "kitty", "herdr", "Qtile", "LazyVim"]


def load_all() -> list[Shortcut]:
    return (
        parse_hyprland() + parse_kitty() + parse_herdr() + parse_qtile()
        + parse_lazyvim()
    )


def save_shortcut(s: Shortcut, new_combo: str) -> None:
    lines = s.file.read_text().splitlines(keepends=False)
    idx = s.line_no - 1
    lines[idx] = s.rewrite(lines[idx], new_combo)
    s.file.write_text("\n".join(lines) + "\n")


# ── UI ───────────────────────────────────────────────────────────────────

class EditModal(ModalScreen[Optional[str]]):
    DEFAULT_CSS = ("""
    EditModal { align: center middle; }
    #edit-box {
        background: %(chip_battery)s;
        padding: 2 3;
        width: 70;
        height: auto;
    }
    #edit-title { color: %(primary)s; text-style: bold; margin-bottom: 1; }
    #edit-current { color: %(text_muted)s; margin-bottom: 1; }
    #edit-hint { color: %(text_muted)s; margin-bottom: 1; }
    Input { background: %(chip_bluetooth)s; color: %(foreground)s; margin-bottom: 1; }
    """) % THEME

    def __init__(self, shortcut: Shortcut) -> None:
        super().__init__()
        self.shortcut = shortcut

    def compose(self) -> ComposeResult:
        s = self.shortcut
        hint = {
            "Hyprland": "formato: SUPER SHIFT, F  (o SUPER, K)",
            "kitty": "formato: ctrl+shift+enter",
            "herdr": "formato: prefix+alt+g",
            "Qtile": 'formato: mod, shift, f   (las comillas de los mods que no son "mod" se agregan solas)',
        }.get(s.app, "")
        with Vertical(id="edit-box"):
            yield Label(f"Editar atajo — {s.app}", id="edit-title")
            yield Label(f"Actual: {s.combo}  ({s.description or s.action})", id="edit-current")
            yield Label(hint, id="edit-hint")
            yield Input(value=s.combo, id="combo-input")
            yield Label("Enter para guardar · Esc para cancelar", id="edit-hint2")

    def on_mount(self) -> None:
        self.query_one("#combo-input", Input).focus()

    @on(Input.Submitted)
    def _submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def key_escape(self) -> None:
        self.dismiss(None)


def _slug(app: str) -> str:
    return app.lower().replace(" ", "-")


class ShortcutsApp(App):
    TITLE = "Shortcuts"
    ENABLE_COMMAND_PALETTE = False

    CSS = ("""
    Screen { background: %(background)s; }
    Header { background: %(background)s; color: %(primary)s; }
    Footer { background: %(background)s; color: %(text_muted)s; }
    #search { background: %(chip_battery)s; color: %(foreground)s; margin: 1 1 0 1; }
    Tabs { background: %(background)s; }
    Tab { color: %(text_muted)s; }
    Tab:hover { color: %(foreground)s; }
    Tab.-active { color: %(primary)s; text-style: bold; }
    Underline > .underline--bar { color: %(primary)s; background: %(chip_battery)s; }
    TabPane { padding: 1 0 0 0; }
    DataTable { background: %(background)s; color: %(foreground)s; }
    DataTable > .datatable--header { background: %(chip_battery)s; color: %(text_muted)s; }
    DataTable > .datatable--cursor { background: %(chip_wlan)s; color: %(primary)s; }
    DataTable > .datatable--hover  { background: %(chip_battery)s; }
    """) % THEME

    BINDINGS = [
        ("q", "quit", "salir"),
        ("r", "reload", "recargar"),
        ("enter", "edit", "editar"),
        ("/", "focus_search", "buscar"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.shortcuts: list[Shortcut] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Buscar por combo o descripción (en la app actual)...", id="search")
        with TabbedContent(id="tabs"):
            for app in APP_ORDER:
                with TabPane(app, id=f"tab-{_slug(app)}"):
                    yield DataTable(id=f"table-{_slug(app)}")
        yield Footer()

    def on_mount(self) -> None:
        for app in APP_ORDER:
            table = self.query_one(f"#table-{_slug(app)}", DataTable)
            table.cursor_type = "row"
            table.add_columns("Combo", "Descripción/Acción")
        self.action_reload()

    def action_reload(self) -> None:
        self.shortcuts = load_all()
        if self.is_mounted:
            self._refresh_all_tables()
            self.notify(f"{len(self.shortcuts)} shortcuts cargados")

    def _filtered(self, app: str) -> list[Shortcut]:
        q = self.query_one("#search", Input).value.strip().lower()
        rows = [s for s in self.shortcuts if s.app == app]
        if not q:
            return rows
        return [s for s in rows if q in s.combo.lower() or q in (s.description or s.action).lower()]

    def _refresh_all_tables(self) -> None:
        for app in APP_ORDER:
            table = self.query_one(f"#table-{_slug(app)}", DataTable)
            table.clear()
            for s in self._filtered(app):
                label = s.description or s.action
                if not s.editable:
                    label += "  ·  solo-lectura"
                table.add_row(s.combo, label, key=id(s))

    @on(Input.Changed, "#search")
    def _on_search_changed(self) -> None:
        self._refresh_all_tables()

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def _active_app(self) -> str:
        tabs = self.query_one(TabbedContent)
        active_id = tabs.active  # "tab-<slug>"
        slug = active_id.removeprefix("tab-")
        return next((a for a in APP_ORDER if _slug(a) == slug), APP_ORDER[0])

    def _current_shortcut(self) -> Optional[Shortcut]:
        app = self._active_app()
        table = self.query_one(f"#table-{_slug(app)}", DataTable)
        if table.cursor_row is None:
            return None
        rows = self._filtered(app)
        if 0 <= table.cursor_row < len(rows):
            return rows[table.cursor_row]
        return None

    def action_edit(self) -> None:
        s = self._current_shortcut()
        if s is None:
            return
        if not s.editable:
            self.notify("Este atajo es de solo lectura (editalo a mano)", severity="warning")
            return

        def _on_result(new_combo: Optional[str]) -> None:
            if not new_combo or new_combo == s.combo:
                return
            try:
                save_shortcut(s, new_combo)
            except Exception as exc:  # noqa: BLE001 - mostrar cualquier falla al usuario
                self.notify(f"Error guardando: {exc}", severity="error")
                return
            self.notify(f"Guardado. Para aplicar: {s.reload_hint}")
            self.action_reload()

        self.push_screen(EditModal(s), _on_result)


if __name__ == "__main__":
    ShortcutsApp().run()
