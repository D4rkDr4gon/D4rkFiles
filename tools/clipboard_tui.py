#!/usr/bin/env python3
"""
clipboard_tui.py — historial del portapapeles (Mod+V), reemplaza al menú rofi.

Lista de cliphist con búsqueda al escribir y preview de la entrada (texto
completo o la imagen, con el protocolo gráfico de kitty). enter copia (y
cierra, como el menú de antes), del borra la entrada, shift+del vacía todo.
Se usa sola (config/waybar/scripts/clipboard-launch.sh, ventana centrada) o como
sección Clipboard de Settings, donde copiar no cierra.

Pasa siempre por scripts/cliphist.sh: la base vive en $XDG_RUNTIME_DIR
(RAM) y el store de wl-paste usa la misma. Las miniaturas de imágenes van
a $XDG_RUNTIME_DIR/cliphist-thumbs y se limpian solas.

Estilo común de las TUIs: tools/dtui.py. Textos visibles en inglés.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import THEME, ConfirmModal, DView, ImagePreview, Panel, Table, ViewApp, css  # noqa: E402

from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, VerticalScroll  # noqa: E402
from textual.widgets import DataTable, Input, Static  # noqa: E402

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de tools/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
CLIPHIST = DOTFILES / "scripts" / "cliphist.sh"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
THUMBS = RUNTIME / "cliphist-thumbs"
IMAGE_RE = re.compile(r"^\[\[ binary data .* (png|jpg|jpeg|bmp|gif|webp) ")


def clip(*args: str, data: bytes | None = None) -> bytes:
    try:
        return subprocess.run(["bash", str(CLIPHIST), *args], input=data, capture_output=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return b""


def entries() -> list[dict]:
    """[{line, id, preview, image (ext|None)}] del más nuevo al más viejo."""
    out = []
    for line in clip("list").decode(errors="replace").splitlines():
        cid, _, preview = line.partition("\t")
        if not cid:
            continue
        m = IMAGE_RE.match(preview)
        out.append({"line": line, "id": cid, "preview": preview, "image": m.group(1) if m else None})
    return out


def thumb(e: dict) -> Optional[Path]:
    """Decodifica una imagen del historial a tmpfs (una vez por entrada)."""
    THUMBS.mkdir(mode=0o700, parents=True, exist_ok=True)
    p = THUMBS / f"{e['id']}.{e['image']}"
    if not p.exists():
        data = clip("decode", data=e["line"].encode())
        if not data:
            return None
        p.write_bytes(data)
    return p


def prune_thumbs(items: list[dict]) -> None:
    keep = {f"{e['id']}.{e['image']}" for e in items if e["image"]}
    for f in THUMBS.glob("*") if THUMBS.is_dir() else []:
        if f.name not in keep:
            f.unlink(missing_ok=True)


class ClipboardView(DView):
    """Búsqueda + lista + preview. exit_on_copy: la TUI suelta se cierra al
    copiar (como el menú rofi); en Settings se queda."""

    FOCUS = "#clip-search"
    DEFAULT_CSS = css("""
    #clip-search-panel { height: 3; }
    #clip-search { background: %(background)s; padding: 0; }
    #clip-search:focus { background: %(background)s; }
    #clip-body { height: 1fr; }
    #clip-list-panel { width: 3fr; }
    #clip-preview-panel { width: 2fr; }
    #clip-text { height: auto; }
    #clip-image { height: 1fr; }
    """)
    BINDINGS = [
        Binding("down", "move(1)", show=False, priority=True),
        Binding("up", "move(-1)", show=False, priority=True),
        Binding("pagedown", "move(10)", show=False),
        Binding("pageup", "move(-10)", show=False),
        Binding("delete", "delete", "delete"),
        Binding("shift+delete", "wipe", "clear all"),
    ]

    def __init__(self, exit_on_copy: bool = False, **kw) -> None:
        super().__init__(**kw)
        self.exit_on_copy = exit_on_copy
        self.items: list[dict] = []
        self.shown: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Panel(Input(placeholder="type to search…", id="clip-search"), title="󰅌  Clipboard",
                    id="clip-search-panel")
        with Horizontal(id="clip-body"):
            yield Panel(Table(id="clip-list", show_header=False), title="History", id="clip-list-panel")
            with VerticalScroll(id="clip-preview-panel", classes="panel") as box:
                box.border_title = " Preview "
                yield Static(id="clip-text")
                yield ImagePreview(id="clip-image")

    def on_mount(self) -> None:
        self.query_one("#clip-list", Table).add_column("", key="text", width=200)
        self.reload()

    def on_show(self) -> None:
        # En Settings: recargar al volver a la sección (el historial cambia solo)
        if self.items is not None and self.is_mounted:
            self.reload()

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "copy"), ("↑↓", "move"), ("del", "delete"), ("shift+del", "clear all"),
                ("esc", "close" if self.exit_on_copy else "menu")]

    # ── datos ──

    def reload(self) -> None:
        self.items = entries()
        prune_thumbs(self.items)
        self.filter()

    def filter(self) -> None:
        q = self.query_one("#clip-search", Input).value.strip().lower()
        t = self.query_one("#clip-list", Table)
        self.shown = [e for e in self.items if not q or q in e["preview"].lower()]
        t.clear()
        for i, e in enumerate(self.shown):
            icon, style = ("󰋩", THEME["primary"]) if e["image"] else ("󰈙", THEME["muted"])
            label = Text()
            label.append(f"{icon}  ", style=style)
            label.append(" ".join(e["preview"].split())[:200])
            t.add_row(label, key=str(i))
        panel = self.query_one("#clip-list-panel")
        panel.border_subtitle = (f" {len(self.shown)} of {len(self.items)} " if q else
                                 f" {len(self.items)} items · in memory, cleared at logout " if self.items
                                 else " empty — copy something first ")
        self.show_preview()

    def current(self) -> Optional[dict]:
        t = self.query_one("#clip-list", Table)
        if not self.shown or t.cursor_row is None or t.cursor_row >= len(self.shown):
            return None
        return self.shown[t.cursor_row]

    def show_preview(self) -> None:
        e = self.current()
        text = self.query_one("#clip-text", Static)
        img = self.query_one("#clip-image", ImagePreview)
        if not e:
            text.update("")
            img.set_image(None)
            img.display = False
            return
        if e["image"]:
            img.display = True
            img.set_image(thumb(e))
            text.update(Text(e["preview"], style=THEME["muted"]))
        else:
            img.display = False
            img.set_image(None)
            full = clip("decode", data=e["line"].encode()).decode(errors="replace")
            text.update(Text(full[:5000] + ("\n…" if len(full) > 5000 else "")))

    # ── eventos ──

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "clip-search":
            self.filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "clip-search":
            event.stop()
            self.copy()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "clip-list":
            self.show_preview()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "clip-list":
            self.copy()

    def action_move(self, step: int) -> None:
        t = self.query_one("#clip-list", Table)
        if t.row_count:
            t.move_cursor(row=max(0, min(t.row_count - 1, (t.cursor_row or 0) + step)))

    # ── acciones ──

    def copy(self) -> None:
        e = self.current()
        if not e:
            return
        data = clip("decode", data=e["line"].encode())
        subprocess.run(["wl-copy"], input=data)
        if self.exit_on_copy:
            if shutil.which("swayosd-client"):
                subprocess.Popen(["swayosd-client", "--custom-message", "Copied", "--custom-icon",
                                  "edit-copy-symbolic"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.app.exit()
        else:
            self.app.notify_ok("Copied to the clipboard")

    def action_delete(self) -> None:
        e = self.current()
        if e:
            row = self.query_one("#clip-list", Table).cursor_row or 0
            clip("delete", data=e["line"].encode())
            self.reload()
            t = self.query_one("#clip-list", Table)
            if t.row_count:
                t.move_cursor(row=min(row, t.row_count - 1))

    def action_wipe(self) -> None:
        def done(yes: bool) -> None:
            if yes:
                clip("wipe")
                prune_thumbs([])
                self.app.notify_ok("Clipboard history cleared")
                self.reload()

        self.app.push_screen(ConfirmModal("Clear clipboard history", "Delete the whole clipboard history?"), done)


def ClipboardApp() -> ViewApp:
    return ViewApp(ClipboardView, title="Clipboard", exit_on_copy=True)


if __name__ == "__main__":
    ClipboardApp().run()
