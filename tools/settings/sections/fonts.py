"""Fonts & cursor — fuente mono, tamaño base, fuente de interfaz y tema de
íconos (campos font_mono / font_size / font_ui / icon_theme del tema activo,
guardados en su copia de ~/.config/dotfiles/themes/ y reaplicados con
theme-switch.sh) y cursor (tema y tamaño: en vivo con hyprctl setcursor +
gsettings, y guardado como `env = XCURSOR_THEME/XCURSOR_SIZE` en
~/.config/dotfiles/hypr/settings.conf).

A la izquierda los ajustes agrupados; a la derecha una vista previa real:
una imagen dibujada con PIL usando el archivo de cada fuente (fc-match),
íconos del tema (siguiendo su Inherits) y el cursor leído de su archivo
Xcursor, más el tamaño que queda en cada app. La imagen se cachea por
combinación en ~/.local/state/dotfiles/settings/previews/ y se genera en un
worker."""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from common import STATE, THEME_SWITCH, active_theme_dir, editable_theme_dir, env_get, env_set, run
from dtui import THEME, Card, DView, Field, FormModal, ImagePreview, Panel, PickModal, Table, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable

ICON_DIRS = [Path.home() / ".local/share/icons", Path.home() / ".icons", Path("/usr/share/icons")]
PREVIEW_DIR = STATE / "previews"
PREVIEW_ICONS = ["folder", "user-home", "folder-download", "utilities-terminal", "firefox", "text-x-generic"]
DEFAULT_MONO, DEFAULT_SIZE = "Hack Nerd Font", 13

# Qué toca cada ajuste (se muestra al seleccionar la fila)
APPLIES = {
    "font": "kitty, rofi, dunst, waybar, gtklock — and every TUI inside kitty (herdr, opencode, btop…)",
    "fsize": "base size: kitty = size, rofi and waybar workspaces −1, waybar and dunst −3, GTK −3",
    "ui": "GTK apps (Thunar, dialogs…) at font size −3; (unchanged) leaves GTK's font alone",
    "icons": "Thunar and GTK apps; falls back to the themes it inherits from",
    "cursor": "applied live (hyprctl setcursor + gsettings) and saved in ~/.config/dotfiles/hypr/settings.conf",
    "size": "pixels (16–64), live and saved in settings.conf",
}


# ── listas para elegir ──

def mono_fonts() -> list[str]:
    fams = run(["fc-list", ":spacing=100", "family"]).stdout.splitlines()
    names = {f.split(",")[0].strip() for f in fams if f.strip()}
    nerd = sorted(n for n in names if "Nerd Font" in n and not re.search(r"Ita\b|Italic|Propo", n))
    return nerd or sorted(names)


def ui_fonts() -> list[str]:
    """Familias proporcionales (sans/serif) para la interfaz GTK."""
    fams = run(["fc-list", ":", "family", "spacing"]).stdout.splitlines()
    names = {f.split(":")[0].split(",")[0].strip() for f in fams if "spacing=" not in f and f.strip()}
    return sorted(n for n in names if "Nerd Font" not in n and not n.startswith("."))


def icon_themes(cursors: bool) -> list[str]:
    """Temas de íconos (cursors=False) o de cursor (cursors=True) instalados."""
    out = set()
    for base in ICON_DIRS:
        for d in base.iterdir() if base.is_dir() else []:
            has_cursors = (d / "cursors").is_dir()
            if cursors and has_cursors:
                out.add(d.name)
            elif not cursors and (d / "index.theme").is_file() and d.name not in ("default", "hicolor", "locolor") \
                    and not (has_cursors and len(list(d.iterdir())) <= 3):
                out.add(d.name)
    return sorted(out)


# ── vista previa ──

def gtk_font() -> str:
    """Familia de la fuente GTK actual (gsettings da "'Cantarell 11'")."""
    v = run(["gsettings", "get", "org.gnome.desktop.interface", "font-name"]).stdout.strip().strip("'")
    return re.sub(r"\s+\d+(\.\d+)?$", "", v) or "Sans"


def font_file(family: str) -> Optional[str]:
    f = run(["fc-match", "-f", "%{file}", f"{family}:style=Regular"]).stdout.strip()
    return f or None


def theme_dir(name: str) -> Optional[Path]:
    return next((b / name for b in ICON_DIRS if (b / name).is_dir()), None)


def inherit_chain(theme: str) -> list[Path]:
    """El tema y los que hereda (Inherits=), sin repetir, terminando en hicolor."""
    chain, todo = [], [theme]
    while todo:
        d = theme_dir(todo.pop(0))
        if not d or d in chain:
            continue
        chain.append(d)
        try:
            m = re.search(r"^Inherits=(.*)$", (d / "index.theme").read_text(), re.M)
            todo += [x.strip() for x in m.group(1).split(",")] if m else []
        except OSError:
            pass
    hicolor = theme_dir("hicolor")
    return chain + ([hicolor] if hicolor and hicolor not in chain else [])


def icon_file(chain: list[Path], name: str) -> Optional[Path]:
    for d in chain:
        for pat in (f"48x48/*/{name}.*", f"64x64/*/{name}.*", f"scalable/*/{name}.*", f"*/48x48/{name}.*",
                    f"*/scalable/{name}.*", f"256x256/*/{name}.*", f"*/256x256/{name}.*", f"192x192/*/{name}.*"):
            hit = next((p for p in d.glob(pat) if p.suffix in (".svg", ".png")), None)
            if hit:
                return hit
    return None


def load_icon(path: Path, px: int):
    from PIL import Image
    if path.suffix == ".png":
        return Image.open(path).convert("RGBA").resize((px, px))
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        if run(["rsvg-convert", "-w", str(px), "-h", str(px), "-o", tmp.name, str(path)]).returncode:
            return None
        return Image.open(tmp.name).convert("RGBA")


def cursor_image(theme: str, size: int):
    """Imagen `left_ptr` del tema de cursor (formato Xcursor), del tamaño más cercano."""
    from PIL import Image
    d = theme_dir(theme)
    f = d / "cursors" / "left_ptr" if d else None
    try:
        data = f.read_bytes() if f else b""
    except OSError:
        return None
    if data[:4] != b"Xcur":
        return None
    ntoc = struct.unpack_from("<I", data, 12)[0]
    best = None
    for i in range(ntoc):
        typ, sub, pos = struct.unpack_from("<III", data, 16 + i * 12)
        if typ == 0xFFFD0002 and (best is None or abs(sub - size) < abs(best[0] - size)):
            best = (sub, pos)
    if not best:
        return None
    w, h = struct.unpack_from("<II", data, best[1] + 16)
    px = data[best[1] + 36: best[1] + 36 + w * h * 4]
    return Image.frombuffer("RGBA", (w, h), px, "raw", "BGRA", 0, 1)


def render_preview(info: dict) -> Optional[Path]:
    """Dibuja la vista previa (cacheada por combinación de ajustes y colores)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    key = hashlib.sha1(json.dumps(info, sort_keys=True).encode()).hexdigest()[:16]
    out = PREVIEW_DIR / f"fonts-{key}.png"
    if out.exists():
        return out
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    scale = 2.6                                  # px por punto: la imagen se achica al panel
    W = 1200
    img = Image.new("RGBA", (W, 900), THEME["background"])   # se recorta al final
    dr = ImageDraw.Draw(img)

    def font(family: str, pt: float):
        f = font_file(family)
        try:
            return ImageFont.truetype(f, int(pt * scale)) if f else ImageFont.load_default()
        except OSError:
            return ImageFont.load_default()

    mono, ui = font(info["mono"], info["size"]), font(info["ui"], max(8, info["size"] - 3))
    small = font(info["mono"], 8)   # leyendas: la mono tiene ·, - y demás (una fuente UI decorativa quizás no)
    y = 24
    dr.text((28, y), "fn main() { let x = 0O1lI; } → ≠ ==", font=mono, fill=THEME["foreground"])
    y += int(info["size"] * scale * 1.6)
    if "Nerd" in info["mono"]:
        dr.text((28, y), "        ~/projects  main +2", font=mono, fill=THEME["primary"])
        y += int(info["size"] * scale * 1.6)
    dr.text((28, y), "The quick brown fox jumps over the lazy dog", font=ui, fill=THEME["foreground"])
    y += int(max(8, info["size"] - 3) * scale * 1.7)
    dr.text((28, y), f"{info['mono']} {info['size']} pt  ·  interface: {info['ui']} {max(8, info['size'] - 3)} pt",
            font=small, fill=THEME["muted"])

    # íconos y cursor en una franja abajo
    strip_y = y + int(8 * scale * 1.6) + 40
    H = strip_y + 110
    dr.line((28, strip_y - 16, W - 28, strip_y - 16), fill=THEME["border"], width=2)
    chain = inherit_chain(info["icons"])
    x = 28
    if not chain or chain[0].name != info["icons"]:
        dr.text((x, strip_y + 30), f"icon theme '{info['icons']}' is not installed", font=small,
                fill=THEME["status_warn"])
    else:
        for name in PREVIEW_ICONS:
            p = icon_file(chain, name)
            ic = load_icon(p, 80) if p else None
            if ic:
                img.alpha_composite(ic, (x, strip_y))
                x += 100
    cur = cursor_image(info["cursor"], info["cursor_size"])
    if cur:
        cur = cur.resize((cur.width * 2, cur.height * 2))   # al doble, para que se distinga
        cx = W - 40 - cur.width
        img.alpha_composite(cur, (cx, strip_y))
        label = f"{info['cursor']}\n{info['cursor_size']} px"
        lw = max(dr.textlength(x, font=small) for x in label.splitlines())
        dr.text((cx - 30 - lw, strip_y + 20), label, font=small, fill=THEME["muted"], align="right")
    tmp = out.with_suffix(".tmp.png")
    img.crop((0, 0, W, H)).convert("RGB").save(tmp)
    os.replace(tmp, out)
    return out


class FontsView(DView):
    FOCUS = "#fonts"
    DEFAULT_CSS = css("""
    #fonts-panel { width: 56; }
    #fonts-right { width: 1fr; }
    #font-preview-panel { height: 1fr; }
    #font-img { height: 1fr; }
    #font-info-panel { height: auto; }
    """)
    BINDINGS = [Binding("r", "refresh", "refresh preview")]

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Panel(Table(id="fonts", show_header=False), title="󰛖  Fonts & cursor", id="fonts-panel")
            with Vertical(id="fonts-right"):
                yield Panel(ImagePreview(id="font-img"), title="Preview", id="font-preview-panel")
                yield Panel(Card(id="font-info"), title="Where it applies", id="font-info-panel")

    def on_mount(self) -> None:
        t = self.query_one("#fonts", Table)
        t.add_column("", key="name", width=18)
        t.add_column("", key="value", width=32)
        self.th: dict = {}
        self.reload()

    def on_show(self) -> None:
        if self.is_mounted:
            self.reload()

    def theme_data(self) -> tuple[Optional[Path], dict]:
        d = active_theme_dir()
        return d, (json.loads((d / "theme.json").read_text()) if d else {})

    def current(self) -> dict:
        _d, th = self.theme_data()
        return {"mono": th.get("font_mono") or DEFAULT_MONO, "size": int(th.get("font_size") or DEFAULT_SIZE),
                "ui_set": th.get("font_ui") or "", "icons": th.get("icon_theme") or "Papirus-Dark",
                "cursor": env_get("XCURSOR_THEME") or "Adwaita", "cursor_size": int(env_get("XCURSOR_SIZE") or 24)}

    def reload(self) -> None:
        d, _th = self.theme_data()
        c = self.cur = self.current()
        muted = THEME["muted"]

        def hdr(name: str) -> tuple[str, list]:
            return (f"hdr:{name}", [Text(name.upper(), style=f"bold {muted}"), ""])

        def val(v: str, dim: bool = False) -> Text:
            return Text(v, style=muted if dim else "bold")

        self.query_one("#fonts", Table).set_rows([
            hdr("fonts"),
            ("font", ["Monospace", val(c["mono"])]),
            ("fsize", ["Size", val(f"{c['size']} pt")]),
            ("ui", ["Interface", val(c["ui_set"] or "(unchanged)", dim=not c["ui_set"])]),
            ("gap:1", ["", ""]),
            hdr("icons"),
            ("icons", ["Theme", val(c["icons"])]),
            ("gap:2", ["", ""]),
            hdr("cursor"),
            ("cursor", ["Theme", val(c["cursor"])]),
            ("size", ["Size", val(f"{c['cursor_size']} px")]),
        ])
        t = self.query_one("#fonts", Table)
        if t.cursor_row is None or t._skippable(t.cursor_row):
            t.first_selectable(0)
        self.query_one("#fonts-panel").border_subtitle = (f" saved in theme {d.name} " if d else "")
        self.show_info()
        self.query_one("#font-preview-panel").border_subtitle = " rendering… "
        self.make_preview(c | {"ui": c["ui_set"] or gtk_font(), "colors": [THEME[k] for k in
                                                                          ("background", "foreground", "primary")]})

    @work(thread=True, exclusive=True, group="font-preview")
    def make_preview(self, info: dict) -> None:
        try:
            path = render_preview(info)
        except Exception:  # noqa: BLE001 - sin vista previa la sección anda igual
            path = None
        self.app.call_from_thread(self.set_preview, path)

    def set_preview(self, path: Optional[Path]) -> None:
        self.query_one("#font-img", ImagePreview).set_image(path)
        self.query_one("#font-preview-panel").border_subtitle = (
            " real fonts, icons and cursor " if path else " preview needs python-pillow ")

    def show_info(self) -> None:
        key = self.query_one("#fonts", Table).selected_key() or "font"
        c, muted = self.cur, THEME["muted"]
        t = Text()
        t.append(APPLIES.get(key, "") + "\n\n", style=muted)
        s, ui = c["size"], c["ui_set"]
        for app, pt, note in [("kitty", s, "base"), ("rofi", s - 1, ""), ("waybar workspaces", s - 1, ""),
                              ("waybar", s - 3, ""), ("dunst", s - 3, ""),
                              ("GTK", s - 3, ui if ui else "(unchanged)")]:
            t.append(f"{app:<20}", style=muted)
            t.append(f"{pt:>3} pt", style="bold")
            if note:
                t.append(f"   {note}", style=muted)
            t.append("\n")
        t.append(f"{'cursor':<20}", style=muted)
        t.append(f"{c['cursor_size']:>3} px", style="bold")
        t.append(f"   {c['cursor']}", style=muted)
        self.query_one("#font-info", Card).update(t)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "fonts" and hasattr(self, "cur"):
            self.show_info()

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "change"), ("r", "refresh preview"), ("q", "quit")]

    def action_refresh(self) -> None:
        self.reload()

    def set_cursor(self, theme: str, size: str) -> None:
        run(["hyprctl", "setcursor", theme, size])
        run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", theme])
        run(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", size])
        env_set("XCURSOR_THEME", theme)
        env_set("XCURSOR_SIZE", size)
        self.app.notify_ok(f"Cursor: {theme} {size}px")
        self.reload()

    def set_theme_field(self, key: str, value) -> None:
        """Guarda el campo en la copia editable del tema (~/.config/dotfiles/themes;
        None = lo borra, vuelve al default)."""
        d = editable_theme_dir()
        if not d:
            return self.app.notify_err("No active theme found")
        th = json.loads((d / "theme.json").read_text())
        if value is None:
            th.pop(key, None)
        else:
            th[key] = value
        f = d / "theme.json"
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(th, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, f)
        self.query_one("#fonts-panel").border_subtitle = " applying… "
        self.apply(d.name)

    @work(thread=True, exclusive=True)
    def apply(self, theme_dir_name: str) -> None:
        subprocess.run(["bash", str(THEME_SWITCH), theme_dir_name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)
        self.app.call_from_thread(self.app.restart, "fonts")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "fonts":
            return
        key = str(event.row_key.value)
        if key.startswith(("hdr:", "gap:")):
            return
        if key == "fsize":
            def done_fs(v: Optional[dict]) -> None:
                if v:
                    self.set_theme_field("font_size", int(v["value"]))
            return self.app.push_screen(FormModal("Font size", [Field("value", "Points (8–24)", str(self.cur["size"]))],
                                                  hint="Saved in the theme's theme.json and applied to every app.",
                                                  validate=lambda v: None if v["value"].isdigit()
                                                  and 8 <= int(v["value"]) <= 24 else "From 8 to 24"), done_fs)
        if key == "ui":
            rows = [("-", [Text("(unchanged · don't touch GTK's font)", style=THEME["muted"])])]
            rows += [(o, [Text(o)]) for o in ui_fonts()]
            return self.app.push_screen(PickModal("Interface font", ["Interface font"], rows),
                                        lambda v: v and self.set_theme_field("font_ui", None if v == "-" else v))
        if key == "size":
            def done(v: Optional[dict]) -> None:
                if v:
                    self.set_cursor(self.cur["cursor"], v["value"])
            return self.app.push_screen(FormModal("Cursor size", [Field("value", "Pixels",
                                                                       str(self.cur["cursor_size"]))],
                                                  validate=lambda v: None if v["value"].isdigit()
                                                  and 16 <= int(v["value"]) <= 64 else "From 16 to 64"), done)
        options = {"font": mono_fonts(), "icons": icon_themes(False), "cursor": icon_themes(True)}[key]
        title = {"font": "Monospace font", "icons": "Icon theme", "cursor": "Cursor theme"}[key]
        rows = [(o, [Text(o, style="bold" if key != "font" else "")]) for o in options]

        def picked(v: Optional[str]) -> None:
            if not v:
                return
            if key == "cursor":
                self.set_cursor(v, str(self.cur["cursor_size"]))
            else:
                self.set_theme_field("font_mono" if key == "font" else "icon_theme", v)

        self.app.push_screen(PickModal(title, [title], rows), picked)
