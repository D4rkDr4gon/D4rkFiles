"""Screenshots — capturas en $(xdg-user-dir PICTURES)/Screenshots con preview.

Arriba las acciones (región, ventana, pantalla y, si está wf-recorder, grabar
la pantalla); abajo la galería: enter copia la imagen, o la abre, d la borra.
Mientras se captura, Settings se esconde (common.settings_hidden) para no
salir en la imagen. Cada captura se guarda Y se copia al portapapeles.
(El atajo de captura sigue siendo scripts/screenshot.sh, que guarda en la misma carpeta.)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from common import detach, run, settings_hidden, tilde
from dtui import THEME, ConfirmModal, DView, ImagePreview, Panel, Table, css, human
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable



def user_dir(kind: str, fallback: str) -> Path:
    """Carpeta XDG del usuario (xdg-user-dir), como scripts/screenshot.sh."""
    out = run(["xdg-user-dir", kind]).stdout.strip()
    return Path(out) if out and out != str(Path.home()) else Path.home() / fallback


SHOTS = user_dir("PICTURES", "Pictures") / "Screenshots"
VIDEOS = user_dir("VIDEOS", "Videos") / "Recordings"


def window_boxes() -> str:
    """Rectángulos de las ventanas visibles, en el formato de `slurp` (x,y wxh)."""
    try:
        ws = {m["activeWorkspace"]["id"] for m in json.loads(run(["hyprctl", "monitors", "-j"]).stdout)}
        clients = json.loads(run(["hyprctl", "clients", "-j"]).stdout)
    except (ValueError, KeyError):
        return ""
    return "\n".join(f"{c['at'][0]},{c['at'][1]} {c['size'][0]}x{c['size'][1]}"
                     for c in clients if c["workspace"]["id"] in ws and c.get("mapped", True))


class ScreenshotsView(DView):
    FOCUS = "#shot-actions"
    DEFAULT_CSS = css("""
    #shot-actions-panel { height: auto; }
    #shot-actions { height: auto; }
    #shot-body { height: 1fr; }
    #shot-list-panel { width: 2fr; }
    #shot-preview-panel { width: 3fr; }
    #shot-preview { height: 1fr; }
    """)
    BINDINGS = [Binding("tab", "switch", show=False), Binding("shift+tab", "switch", show=False),
                Binding("d", "delete", "delete"), Binding("o", "open", "open")]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="shot-actions", show_header=False), title="󰄀  Capture", id="shot-actions-panel")
        with Horizontal(id="shot-body"):
            yield Panel(Table(id="shot-list", show_header=False), title="Gallery", id="shot-list-panel")
            yield Panel(ImagePreview(id="shot-preview"), title="Preview", id="shot-preview-panel")

    def on_mount(self) -> None:
        a = self.query_one("#shot-actions", Table)
        a.add_column("", key="name", width=30)
        a.add_column("", key="desc", width=70)
        self.files: list[Path] = []
        self.reload()

    def actions(self) -> None:
        a = self.query_one("#shot-actions", Table)
        a.clear()
        rows = [("region", "󰩭  Region", "select an area with the mouse"),
                ("window", "  Window", "click on a window"),
                ("screen", "󰍹  Screen", "the monitor under the cursor")]
        if shutil.which("wf-recorder"):
            rec = run(["pgrep", "-x", "wf-recorder"]).returncode == 0
            rows.append(("record", "󰑋  Stop recording" if rec else "󰑋  Record region",
                         f"saved to {VIDEOS}" if not rec else "recording… enter to stop"))
        else:
            rows.append(("norecord", "󰑋  Record screen", "install wf-recorder to enable it"))
        for key, name, desc in rows:
            a.add_row(name, Text(desc, style=THEME["muted"]), key=key)

    def reload(self, select: Optional[Path] = None) -> None:
        self.actions()
        t = self.query_one("#shot-list", Table)
        if not t.columns:
            t.add_column("", key="name", width=40)
        t.clear()
        self.files = sorted(SHOTS.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if SHOTS.is_dir() else []
        for f in self.files:
            st = f.stat()
            label = Text(f.stem)
            label.append(f"  {human(st.st_size)}", style=THEME["muted"])
            t.add_row(label, key=str(f))
        if select and select in self.files:
            t.move_cursor(row=self.files.index(select))
        self.query_one("#shot-list-panel").border_subtitle = (f" {len(self.files)} in {tilde(SHOTS)} "
                                                              if self.files else " no screenshots yet ")
        self.show_preview()

    def current(self) -> Optional[Path]:
        key = self.query_one("#shot-list", Table).selected_key()
        return Path(key) if key else None

    def show_preview(self) -> None:
        self.query_one(ImagePreview).set_image(self.current())

    def hints(self) -> list[tuple[str, str]]:
        if self.app.focused is self.query_one("#shot-list", Table):
            return [("enter", "copy"), ("o", "open"), ("d", "delete"), ("tab", "capture"), ("q", "quit")]
        return [("enter", "capture"), ("tab", "gallery"), ("q", "quit")]

    def action_switch(self) -> None:
        target = "#shot-actions" if self.app.focused is self.query_one("#shot-list", Table) else "#shot-list"
        self.query_one(target, Table).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "shot-list":
            self.show_preview()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        if event.data_table.id == "shot-list":
            subprocess.run(["wl-copy", "--type", "image/png"], input=Path(key).read_bytes())
            self.app.notify_ok("Image copied to the clipboard")
        elif event.data_table.id == "shot-actions":
            if key in ("region", "window", "screen"):
                self.capture(key)
            elif key == "record":
                self.record()
            elif key == "norecord":
                self.app.notify_err("wf-recorder is not installed")

    def capture(self, mode: str) -> None:
        SHOTS.mkdir(parents=True, exist_ok=True)
        out = SHOTS / time.strftime("screenshot_%Y-%m-%d_%H-%M-%S.png")
        with settings_hidden(self.app):
            if mode == "screen":
                mon = next((m["name"] for m in json.loads(run(["hyprctl", "monitors", "-j"]).stdout or "[]")
                            if m.get("focused")), None)
                r = run(["grim", *(["-o", mon] if mon else []), str(out)])
            else:
                sel = run(["slurp"] if mode == "region" else ["slurp", "-r"],
                          input=None if mode == "region" else window_boxes(), timeout=60)
                geom = sel.stdout.strip()
                r = run(["grim", "-g", geom, str(out)]) if geom else sel
        if r.returncode == 0 and out.exists():
            subprocess.run(["wl-copy", "--type", "image/png"], input=out.read_bytes())
            self.app.notify_ok(f"Saved and copied: {out.name}")
            self.reload(select=out)
        else:
            self.app.notify_err("Capture cancelled")

    def record(self) -> None:
        if run(["pgrep", "-x", "wf-recorder"]).returncode == 0:
            run(["pkill", "-INT", "-x", "wf-recorder"])
            self.app.notify_ok(f"Recording saved in {VIDEOS}")
        else:
            VIDEOS.mkdir(parents=True, exist_ok=True)
            with settings_hidden(self.app):
                geom = run(["slurp"], timeout=60).stdout.strip()
            if not geom:
                return self.app.notify_err("Recording cancelled")
            out = VIDEOS / time.strftime("recording_%Y-%m-%d_%H-%M-%S.mp4")
            detach(["wf-recorder", "-g", geom, "-f", str(out)])
            self.app.notify_ok("Recording… open Settings → Screenshots and press enter to stop")
        self.set_timer(0.5, self.actions)

    def action_open(self) -> None:
        if f := self.current():
            detach(["xdg-open", str(f)])

    def action_delete(self) -> None:
        f = self.current()
        if not f:
            return

        def done(yes: bool) -> None:
            if yes:
                f.unlink(missing_ok=True)
                self.reload()

        self.app.push_screen(ConfirmModal("Delete screenshot", f"Delete {f.name}?"), done)
