#!/usr/bin/env python3
"""
shortcuts_tui.py — Cheatsheet de shortcuts, ver + editar.

Junta los atajos de Hyprland, kitty, herdr, Qtile (X11), los defaults de
LazyVim y las teclas de las propias TUIs (Settings y sus secciones: keymap
de dtui en ~/.config/dotfiles/keymap.json) en una tab por app (no una lista
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

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import (THEME, KEYMAP_FILE, DView, Field, FormModal, Panel, Table, ViewApp, css,  # noqa: E402
                  key_display, load_keymap, save_keymap)

from rich.text import Text  # noqa: E402
from textual import on  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal  # noqa: E402
from textual.widgets import DataTable, Input  # noqa: E402

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de tools/
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
    default: str = ""   # Settings: tecla por defecto del binding
    section: str = ""   # Settings: sección a la que pertenece


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

    hs_hint = "not editable here — edit hyprshell/config.ron (reloads by itself)"
    _ro("SUPER, W", "hyprshell overview", "workspace overview + launcher", HYPRSHELL_CONF, hs_hint)
    _ro("ALT, Tab", "hyprshell switch", "switch window with previews (release Alt to confirm)", HYPRSHELL_CONF, hs_hint)
    gs_hint = "not editable here — edit the `gesture =` lines in config/hypr/hyprland.conf"
    _ro("3 fingers ← →", "previous/next workspace", "touchpad gesture, follows the finger", HYPR_CONF, gs_hint)
    _ro("3 fingers ↑", "hyprshell overview", "touchpad gesture", HYPR_CONF, gs_hint)
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
            reload_hint="reopen the terminal (or ctrl+shift+F5 in kitty)",
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
                    reload_hint="theme <active theme> (regenerates config.toml), then herdr server reload-config",
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
                    reload_hint="theme <active theme> (regenerates config.toml), then herdr server reload-config",
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
                    reload_hint="theme <active theme> (regenerates config.toml), then herdr server reload-config",
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
    config/nvim/lua/config/keymaps.lua (hoy vacío) a mano.

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
            reload_hint="not editable — plugin defaults, add overrides in config/nvim/lua/config/keymaps.lua",
        ))
    return out


# ── Settings (teclas de las TUIs propias) ──
# Cada binding de Settings y sus secciones tiene un id ("FirewallView.add");
# reasignar = guardar {id: teclas} en el keymap de dtui. Se aplica al instante
# en Settings (set_keymap) y en las TUIs sueltas la próxima vez que se abren.

ACTION_DESC = {"cycle(1)": "next panel", "cycle(-1)": "previous panel", "toggle_focus": "menu ↔ section",
               "menu_move(1)": "menu down", "menu_move(-1)": "menu up", "quit": "quit", "leave": "back / close",
               "switch": "switch panel", "down": "down", "up": "up", "activate": "select card action",
               "focus_search": "search", "refresh": "refresh", "reload": "reload"}
KEY_RE = re.compile(r"^((ctrl|shift|alt|super|meta)\+)*([a-z0-9]|f\d{1,2}|[a-z_]{2,}|[^\w\s,])$")
SETTINGS_GLOBAL = ("Settings menu", "Every TUI")


def binding_desc(b) -> str:
    if b.description:
        return b.description
    return ACTION_DESC.get(b.action, re.sub(r"[_()]", " ", b.action).strip())


def settings_catalog() -> list:
    """(sección, binding) de Settings. Dentro de Settings usa su propio módulo
    (__main__); suelto, lo importa."""
    cat = getattr(sys.modules.get("__main__"), "binding_catalog", None)
    if cat is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "settings"))
        import settings_tui  # noqa: PLC0415 - pesado: solo al abrir la pestaña
        cat = settings_tui.binding_catalog
    return cat()


def parse_settings() -> list[Shortcut]:
    try:
        catalog = settings_catalog()
    except Exception:  # noqa: BLE001 - sin Settings importable, la pestaña queda vacía
        return []
    km = load_keymap()
    out = []
    for section, b in catalog:
        keys = km.get(b.id, b.key)
        desc = f"{section} · {binding_desc(b)}" + ("  (changed)" if b.id in km else "")
        out.append(Shortcut(app="Settings", combo=", ".join(key_display(k) for k in keys.split(",")),
                            action=b.id, description=desc, file=KEYMAP_FILE, line_no=0,
                            rewrite=lambda line, combo: line,
                            reload_hint="applied now in Settings; standalone TUIs on next launch",
                            default=b.key, section=section))
    return out


def save_settings_key(s: Shortcut, combo: str, all_rows: list[Shortcut]) -> Optional[str]:
    """Valida y guarda la tecla nueva en el keymap. Devuelve un error o None.
    Vacío = vuelve al default."""
    km = load_keymap()
    combo = combo.strip().lower().replace(" ", "")
    if not combo:
        km.pop(s.action, None)
        save_keymap(km)
        return None
    keys = [k for k in combo.split(",") if k]
    bad = [k for k in keys if not KEY_RE.match(k)]
    if bad:
        return f"Not a key: {', '.join(bad)} (examples: a, ctrl+s, f5, slash, left)"
    mine = {key_display(k) for k in keys}
    for o in all_rows:
        if o is s or o.app != "Settings":
            continue
        same_scope = o.section == s.section or o.section in SETTINGS_GLOBAL or s.section in SETTINGS_GLOBAL
        if same_scope and mine & {k.strip() for k in o.combo.split(",")}:
            return f"Already used by {o.description.split('  (')[0]} ({o.combo})"
    if ",".join(keys) == s.default:
        km.pop(s.action, None)
    else:
        km[s.action] = ",".join(keys)
    save_keymap(km)
    return None


APP_ORDER = ["Hyprland", "kitty", "herdr", "Qtile", "LazyVim", "Settings"]


def load_all() -> list[Shortcut]:
    return (
        parse_hyprland() + parse_kitty() + parse_herdr() + parse_qtile()
        + parse_lazyvim() + parse_settings()
    )


def save_shortcut(s: Shortcut, new_combo: str) -> None:
    lines = s.file.read_text().splitlines(keepends=False)
    idx = s.line_no - 1
    lines[idx] = s.rewrite(lines[idx], new_combo)
    s.file.write_text("\n".join(lines) + "\n")


# ── UI ───────────────────────────────────────────────────────────────────

FORMATS = {
    "Hyprland": "format: SUPER SHIFT, F  (or SUPER, K)",
    "kitty": "format: ctrl+shift+enter",
    "herdr": "format: prefix+alt+g",
    "Qtile": 'format: mod, shift, f   (quotes for mods other than "mod" are added automatically)',
    "Settings": "format: a · ctrl+s · f5 · slash · left — several: left,minus · empty = back to default",
}


class ShortcutsView(DView):
    """Buscar + apps + atajos de la app elegida. Se usa sola (ShortcutsApp) o en Settings."""

    FOCUS = "#apps"
    DEFAULT_CSS = css("""
    #search-panel { height: 3; }
    #search { background: %(background)s; padding: 0; }
    #search:focus { background: %(background)s; }
    #body { height: 1fr; }
    #apps-panel { width: 22; }
    #list-panel { width: 1fr; }
    """)

    BINDINGS = [
        Binding("/", "focus_search", "search"),
        Binding("tab", "switch", show=False),
        Binding("shift+tab", "switch", show=False),
        Binding("r", "reload", "reload"),
        Binding("escape", "back", show=False),
        Binding("j", "down", show=False),
        Binding("k", "up", show=False),
    ]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.shortcuts: list[Shortcut] = []
        self.rows: list[Shortcut] = []

    def compose(self) -> ComposeResult:
        yield Panel(Input(placeholder="combo or description…", id="search"), title="  Search", id="search-panel")
        with Horizontal(id="body"):
            yield Panel(Table(show_header=False, id="apps"), title="Apps", id="apps-panel")
            yield Panel(Table(id="list"), title="Shortcuts", id="list-panel")

    def on_mount(self) -> None:
        apps = self.query_one("#apps", DataTable)
        apps.add_column("App", key="app", width=12)
        apps.add_column("N", key="n", width=4)
        for app in APP_ORDER:
            apps.add_row(app, "", key=app)
        lst = self.query_one("#list", DataTable)
        lst.add_column("Combo", key="combo", width=26)
        lst.add_column("Description / action", key="desc", width=70)
        self.action_reload()

    # ── datos ──

    def query_text(self) -> str:
        return self.query_one("#search", Input).value.strip().lower()

    def matches(self, app: str) -> list[Shortcut]:
        q = self.query_text()
        rows = [s for s in self.shortcuts if s.app == app]
        return [s for s in rows if not q or q in s.combo.lower() or q in (s.description or s.action).lower()]

    def active_app(self) -> str:
        t = self.query_one("#apps", DataTable)
        return APP_ORDER[t.cursor_row] if t.cursor_row is not None and t.cursor_row < len(APP_ORDER) else APP_ORDER[0]

    def refresh_tables(self) -> None:
        apps = self.query_one("#apps", DataTable)
        for app in APP_ORDER:
            apps.update_cell(app, "n", Text(str(len(self.matches(app))), style=THEME["muted"]))
        app = self.active_app()
        lst = self.query_one("#list", DataTable)
        lst.clear()
        self.rows = self.matches(app)
        for s in self.rows:
            label = Text(s.description or s.action)
            if not s.editable:
                label.append("  · read only", style=THEME["muted"])
            lst.add_row(Text(s.combo, style=f"bold {THEME['primary']}"), label)
        panel = self.query_one("#list-panel")
        panel.border_title = f" {app} "
        panel.border_subtitle = f" {len(self.rows)} shortcut{'' if len(self.rows) == 1 else 's'} "
        self.update_hints()

    def hints(self) -> list[tuple[str, str]]:
        if self.app.focused is self.query_one("#list", DataTable):
            return [("enter", "edit"), ("/", "search"), ("tab", "apps"), ("r", "reload"), ("q", "quit")]
        if self.app.focused is self.query_one("#search", Input):
            return [("enter", "go to list"), ("esc", "back")]
        return [("enter", "show shortcuts"), ("/", "search"), ("tab", "shortcuts"), ("r", "reload"), ("q", "quit")]

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "apps":
            self.refresh_tables()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "apps":
            self.query_one("#list", DataTable).focus()
        elif event.data_table.id == "list":
            self.action_edit()

    @on(Input.Changed, "#search")
    def _on_search_changed(self) -> None:
        # Si la app actual no tiene resultados, saltar a la primera que sí
        if not self.matches(self.active_app()):
            first = next((i for i, a in enumerate(APP_ORDER) if self.matches(a)), None)
            if first is not None:
                self.query_one("#apps", DataTable).move_cursor(row=first)
        self.refresh_tables()

    @on(Input.Submitted, "#search")
    def _on_search_submitted(self) -> None:
        self.query_one("#list", DataTable).focus()

    # ── acciones ──

    def action_reload(self) -> None:
        self.shortcuts = load_all()
        if self.is_mounted:
            self.refresh_tables()
            self.query_one("#search-panel").border_subtitle = f" {len(self.shortcuts)} shortcuts in total "

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_back(self) -> None:
        # Desde la búsqueda vuelve a la lista; si no, lo que haga la app
        # (salir la TUI suelta, volver al menú en Settings)
        if self.app.focused is self.query_one("#search", Input):
            self.query_one("#list", DataTable).focus()
        else:
            self.app.action_leave()

    def action_switch(self) -> None:
        target = "#apps" if self.app.focused is self.query_one("#list", DataTable) else "#list"
        self.query_one(target, DataTable).focus()

    def action_down(self) -> None:
        if isinstance(self.app.focused, DataTable):
            self.app.focused.action_cursor_down()

    def action_up(self) -> None:
        if isinstance(self.app.focused, DataTable):
            self.app.focused.action_cursor_up()

    def action_edit(self) -> None:
        t = self.query_one("#list", DataTable)
        if t.cursor_row is None or not (0 <= t.cursor_row < len(self.rows)):
            return
        s = self.rows[t.cursor_row]
        if not s.editable:
            self.app.notify(f"Read only: {s.reload_hint}", severity="warning")
            return

        if s.app == "Settings":
            return self.edit_settings_key(s)

        def done(v: Optional[dict]) -> None:
            new_combo = (v or {}).get("combo", "").strip()
            if not new_combo or new_combo == s.combo:
                return
            try:
                save_shortcut(s, new_combo)
            except Exception as exc:  # noqa: BLE001 - mostrar cualquier falla al usuario
                self.app.notify_err(f"Error saving: {exc}")
                return
            self.app.notify_ok(f"Saved. To apply: {s.reload_hint}")
            self.action_reload()

        hint = f"Current: {s.combo}  ({s.description or s.action})\n{FORMATS.get(s.app, '')}"
        self.app.push_screen(FormModal(f"Edit shortcut · {s.app}", [Field("combo", "Combo", s.combo)],
                                       hint=hint), done)

    def edit_settings_key(self, s: Shortcut) -> None:
        """Reasigna una tecla de Settings (keymap de dtui) y la aplica en vivo."""
        def done(v: Optional[dict]) -> None:
            if v is None:
                return
            err = save_settings_key(s, v.get("combo", ""), self.shortcuts)
            if err:
                return self.app.notify_err(err)
            self.app.set_keymap(load_keymap())     # en Settings: al instante
            self.app.notify_ok("Saved. " + ("Back to default" if not v.get("combo", "").strip() else s.reload_hint))
            self.action_reload()

        cur = load_keymap().get(s.action, s.default)
        hint = (f"{s.description}\nDefault: {s.default}   ·   id: {s.action}\n"
                f"{FORMATS['Settings']}")
        self.app.push_screen(FormModal(f"Edit key · {s.section}", [Field("combo", "Keys", cur)],
                                       hint=hint), done)



def ShortcutsApp() -> ViewApp:
    return ViewApp(ShortcutsView, title="Shortcuts")


if __name__ == "__main__":
    ShortcutsApp().run()
