"""Theme editor — editar los colores de un tema con preview en vivo.

Se trabaja sobre un borrador basado en un tema (por defecto el activo; b
elige otro). enter edita un campo (los colores con validación #rrggbb y
muestra), n guarda el borrador como tema NUEVO en
~/.config/dotfiles/themes/<nombre>/ y lo aplica, s guarda el tema base (pide
confirmación) y lo aplica. Nunca se escribe en themes/ del repo: guardar un
tema del repo crea su copia en ~/.config/dotfiles/themes/, que theme-switch.sh
usa antes que la original. Aplicar corre theme-switch.sh y reabre Settings
para tomar los colores.

w arma el borrador desde un wallpaper (wallpalette.py: fondo, rampa de
superficies, acentos y estados sacados de la imagen, con contraste mínimo),
conservando la forma del tema base (radio, blur, fuentes…). Al guardarlo con n
se genera también su preview.png (el wallpaper con la paleta abajo).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from common import (THEME_SWITCH, USER_THEMES_DIR, active_theme_dir, current_theme, editable_theme_dir,
                    is_user_theme, resolve_wallpaper, theme_dirs, tilde, wallpaper_dirs)
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, PickModal, Table, css, swatches
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static
from wallpalette import theme_from, write_preview

COLOR_KEYS = [("primary", "accent: focus, selection, bars"), ("secondary", "second accent"),
              ("background", "base surface"), ("foreground", "text"),
              ("chip_battery", "surface 1 (darkest)"), ("chip_bluetooth", "surface 2"),
              ("chip_wlan", "surface 3"), ("chip_audio", "surface 4 (lightest)"),
              ("status_ok", "success / good"), ("status_warn", "warning"), ("status_error", "error")]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class ThemeEditorView(DView):
    FOCUS = "#editor"
    DEFAULT_CSS = css("""
    #editor-preview-panel { height: auto; }
    #editor-preview { height: auto; }
    #editor-panel { height: 1fr; }
    """)
    BINDINGS = [Binding("b", "base", "base theme"), Binding("w", "wallpaper", "theme from a wallpaper"),
                Binding("n", "save_new", "save as new"), Binding("s", "save", "save")]

    def compose(self) -> ComposeResult:
        yield Panel(Static(id="editor-preview"), title="󰏘  Theme editor", id="editor-preview-panel")
        yield Panel(Table(id="editor"), title="Draft", id="editor-panel")

    def on_mount(self) -> None:
        t = self.query_one("#editor", Table)
        t.add_column("", key="sw", width=8)
        t.add_column("Field", key="name", width=18)
        t.add_column("Value", key="value", width=40)
        t.add_column("", key="desc", width=36)
        self.load_base(active_theme_dir())

    def load_base(self, d: Optional[Path]) -> None:
        if not d:
            d = theme_dirs()[0]
        self.base = d
        self.draft = json.loads((d / "theme.json").read_text())
        self.dirty = False
        self.from_wallpaper: Optional[str] = None
        self.reload()

    def reload(self) -> None:
        t = self.query_one("#editor", Table)
        row = t.cursor_row or 0
        t.clear()
        muted = THEME["muted"]
        for key, label in (("name", "Name"), ("icon", "Icon"), ("wallpaper", "Wallpaper")):
            t.add_row("", label, str(self.draft.get(key, "")).replace(str(Path.home()), "~"), "", key=key)
        for key, desc in COLOR_KEYS:
            val = self.draft.get(key, "")
            t.add_row(Text("██████", style=val) if HEX.match(val or "") else "", key, val,
                      Text(desc, style=muted), key=key)
        t.move_cursor(row=min(row, t.row_count - 1))
        d = self.draft
        p = Text()
        p.append(f" {d.get('icon', '')}  {d.get('name', '')} ", style=f"bold {d.get('background')} on {d.get('primary')}")
        p.append("  ")
        p.append(" text on base ", style=f"{d.get('foreground')} on {d.get('background')}")
        p.append(" selection ", style=f"bold {d.get('foreground')} on {d.get('chip_audio')}")
        p.append(" ok ", style=f"bold {d.get('background')} on {d.get('status_ok')}")
        p.append(" warn ", style=f"bold {d.get('background')} on {d.get('status_warn')}")
        p.append(" error ", style=f"bold {d.get('background')} on {d.get('status_error')}")
        p.append("\n\n")
        p.append_text(swatches(d, width=6))
        self.query_one("#editor-preview", Static).update(p)
        origin = f"wallpaper {Path(self.from_wallpaper).name} + shape of {self.base.name}" if self.from_wallpaper \
            else self.base.name
        self.query_one("#editor-panel").border_subtitle = (f" based on {origin}"
                                                           f"{' · unsaved changes' if self.dirty else ''} ")

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "edit"), ("b", "base theme"), ("w", "from wallpaper"), ("n", "save as new"),
                ("s", "save"), ("q", "quit")]

    def action_wallpaper(self) -> None:
        cur = resolve_wallpaper(current_theme().get("wallpaper", "") or "-")
        current = str(cur) if cur else ""
        files = sorted({p for d in wallpaper_dirs() if d.is_dir() for p in d.iterdir()
                        if p.suffix.lower() in IMAGE_EXT}, key=lambda p: p.name.lower())
        rows = [("other", ["󰉋  Other image…", Text("any file", style=THEME["muted"])])]
        if current:
            rows.append((current, [f"\uf03e  {Path(current).name}", Text("current wallpaper", style=THEME["primary"])]))
        rows += [(str(p), [f"\uf03e  {p.name}", ""]) for p in files if str(p) != current]

        def use(path: str) -> None:
            try:
                colors = theme_from(path)
            except (OSError, ValueError) as e:
                return self.app.notify_err(f"Could not read the image: {e}")
            name = re.sub(r"[-_]+", " ", Path(path).stem).strip().upper()
            p = Path(path)
            # En una carpeta de wallpapers basta el nombre (como los temas del repo)
            wall = p.name if resolve_wallpaper(p.name) == p else path
            self.draft = dict(self.draft, **colors, name=name, icon="󰸉", wallpaper=wall)
            self.from_wallpaper, self.dirty = path, True
            self.reload()
            self.app.notify_ok("Palette taken from the wallpaper: n saves it as a new theme")

        def picked(key: Optional[str]) -> None:
            if key == "other":
                self.app.push_screen(FormModal("Theme from an image", [Field("path", "Image", str(Path.home()) + "/",
                                                                              files=True)],
                                               validate=lambda v: None if Path(v["path"]).expanduser().is_file()
                                               else "File not found"),
                                     lambda v: use(str(Path(v["path"]).expanduser())) if v else None)
            elif key:
                use(key)

        self.app.push_screen(PickModal("Theme from a wallpaper", ["Image", ""], rows), picked)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "editor":
            return
        key = str(event.row_key.value)
        is_color = key in dict(COLOR_KEYS)

        def check(v: dict) -> Optional[str]:
            if is_color and not HEX.match(v["value"]):
                return "Use a #rrggbb color"
            if key == "wallpaper" and not resolve_wallpaper(v["value"]):
                return "Not found (a file path, or a name in your wallpaper folders)"
            return None if v["value"] or key == "icon" else "Can't be empty"

        def done(v: Optional[dict]) -> None:
            if v is None:
                return
            val = v["value"]
            if key == "wallpaper" and "/" in val:
                val = str(Path(val).expanduser())
            self.draft[key] = val.lower() if is_color else val
            self.dirty = True
            self.reload()

        self.app.push_screen(FormModal(f"Edit {key}", [Field("value", dict(COLOR_KEYS).get(key, key),
                                                             str(self.draft.get(key, "")),
                                                             files=key == "wallpaper")],
                                       hint="Color picker (Tools) copies hex colors you can paste here."
                                       if is_color else "", validate=check), done)

    def action_base(self) -> None:
        rows = []
        dirs = {d.name: d for d in theme_dirs()}
        for d in dirs.values():
            th = json.loads((d / "theme.json").read_text())
            rows.append((d.name, [f"{th.get('icon', '')}  {th.get('name', d.name)}"
                                  + ("  · yours" if is_user_theme(d) else ""), swatches(th, width=2)]))

        def picked(name: Optional[str]) -> None:
            if name:
                self.load_base(dirs[name])

        self.app.push_screen(PickModal("Base theme", ["Theme", "Palette"], rows), picked)

    def action_save_new(self) -> None:
        def done(v: Optional[dict]) -> None:
            if not v:
                return
            d = USER_THEMES_DIR / slug(v["name"])
            d.mkdir(parents=True)
            draft = dict(self.draft, name=v["name"].upper())
            (d / "theme.json").write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n")
            if self.from_wallpaper:
                try:
                    write_preview(self.from_wallpaper, draft, d / "preview.png")
                except (OSError, ValueError):
                    pass
            self.base, self.draft, self.dirty, self.from_wallpaper = d, draft, False, None
            self.apply(d.name)

        def check(v: dict) -> Optional[str]:
            if not slug(v["name"]):
                return "The name is missing"
            taken = {d.name for d in theme_dirs()}
            return f"A theme called {slug(v['name'])} already exists" if slug(v["name"]) in taken else None

        self.app.push_screen(FormModal("Save as a new theme", [Field("name", "Theme name",
                                                                          self.draft.get("name", "").title()
                                                                          if self.from_wallpaper else "",
                                                                          placeholder="e.g. Deep Ocean")],
                                       hint="Created in ~/.config/dotfiles/themes/<name>/ and applied.", validate=check), done)

    def action_save(self) -> None:
        def done(yes: bool) -> None:
            if yes:
                d = editable_theme_dir(self.base)
                (d / "theme.json").write_text(json.dumps(self.draft, indent=2, ensure_ascii=False) + "\n")
                self.base, self.dirty = d, False
                self.apply(d.name)

        target = USER_THEMES_DIR / self.base.name
        extra = "" if is_user_theme(self.base) else "\n(your copy is used instead of the repo's theme)"
        self.app.push_screen(ConfirmModal("Save theme", f"Save to {tilde(target)} and apply it?{extra}"), done)

    @work(thread=True, exclusive=True)
    def apply(self, theme_dir: str) -> None:
        self.app.call_from_thread(setattr, self.query_one("#editor-panel"), "border_subtitle", " applying… ")
        subprocess.run(["bash", str(THEME_SWITCH), theme_dir], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)
        self.app.call_from_thread(self.app.restart, "themeeditor")
