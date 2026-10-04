"""
dtui.py — base común de las TUIs del entorno (Textual), estilo impala/bluetui.

Todas las TUIs propias (settings, backup, modes, webapps, VPN, shortcuts,
agents, expenses) se arman con estas piezas para verse iguales. Los textos
visibles van en inglés; comentarios y docs en español.

- DView: el contenido de una TUI. Se monta solo (ViewApp) o como sección de
  Settings (tools/settings/settings_tui.py); por eso no busca widgets de
  la app: los atajos del pie se publican con `self.update_hints()`.
- Panel: bloque con borde redondeado y título sobre el borde; el panel con
  foco lleva el borde en el color primario del tema, el resto atenuado.
- Table: DataTable con selección de fila completa.
- KeyHints: línea de atajos al pie ("enter upload  a add  q quit").
- FormModal / ConfirmModal / PickModal / TextModal: popups centrados.
- ImagePreview (protocolo gráfico de kitty vía textual-image) y Swatches.
- Colores: $XDG_STATE_HOME/dotfiles/current_theme.json (lo escribe
  scripts/theme-switch.sh), así siguen al tema activo.

Uso:
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # desde tools/
    from dtui import DApp, DView, Panel, KeyHints, FormModal, ...
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label, Select, Static

THEME_FILE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "dotfiles" / "current_theme.json"

# textual-image le pregunta a la terminal qué protocolo de imágenes soporta y
# espera la respuesta: tiene que importarse ANTES de que arranque la app (si
# se importa con Textual ya leyendo la entrada, la respuesta se pierde y la
# TUI queda colgada en blanco). Sin el paquete, ImagePreview muestra un texto.
try:
    from textual_image.widget import Image as _ImageWidget
except Exception:  # noqa: BLE001 - paquete ausente o terminal sin soporte
    _ImageWidget = None


# ── Tema ──────────────────────────────────────────────────

def hex_blend(c1: str, c2: str, pct: int) -> str:
    """Réplica de hex_blend() en scripts/theme-switch.sh."""
    c1, c2 = c1.lstrip("#"), c2.lstrip("#")
    a = [int(c1[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(c2[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{(x * pct + y * (100 - pct)) // 100:02x}" for x, y in zip(a, b))


THEME_KEYS = ("primary", "secondary", "background", "foreground", "chip_battery", "chip_bluetooth",
              "chip_wlan", "chip_audio", "status_ok", "status_warn", "status_error")


def load_theme(path: Path = THEME_FILE) -> dict:
    t = {
        "primary": "#c62828", "secondary": "#8e1a1a",
        "background": "#0f0f10", "foreground": "#c5c8c6",
        "chip_battery": "#1a1515", "chip_bluetooth": "#2a1a1a",
        "chip_wlan": "#3a2020", "chip_audio": "#4a2525",
        "status_ok": "#5cb85c", "status_warn": "#f9a825", "status_error": "#ff1744",
    }
    try:
        data = json.loads(path.read_text())
        t.update({k: v for k, v in data.items() if k in t})
    except (OSError, json.JSONDecodeError):
        pass
    t["muted"] = hex_blend(t["foreground"], t["background"], 45)
    # Borde de panel sin foco: visible pero sin competir con el primario
    t["border"] = hex_blend(t["foreground"], t["background"], 22)
    return t


THEME = load_theme()


def css(template: str) -> str:
    """Rellena %(clave)s con los colores del tema (escapar % como %%)."""
    return template % THEME


BASE_CSS = css("""
Screen { background: %(background)s; color: %(foreground)s; }

/* Panel: borde redondeado, título sobre el borde */
.panel {
    border: round %(border)s;
    border-title-color: %(muted)s;
    border-title-style: bold;
    border-subtitle-color: %(muted)s;
    background: %(background)s;
    padding: 0 1;
}
.panel:focus-within {
    border: round %(primary)s;
    border-title-color: %(primary)s;
}

DataTable { background: %(background)s; color: %(foreground)s; scrollbar-size-vertical: 1; overflow-x: hidden; }
DataTable > .datatable--header { background: %(background)s; color: %(muted)s; text-style: bold; }
/* Fila seleccionada: tenue en paneles sin foco, marcada en el que tiene foco.
   Los colores de cada celda se conservan (Table usa cursor_foreground_priority
   "renderable"), así barras y estados no se pierden en la fila seleccionada. */
DataTable > .datatable--cursor { background: %(chip_battery)s; color: %(foreground)s; text-style: none; }
DataTable:focus > .datatable--cursor { background: %(chip_audio)s; color: %(foreground)s; text-style: bold; }
DataTable > .datatable--hover { background: %(chip_battery)s; }

KeyHints { dock: bottom; height: 1; padding: 0 2; background: %(background)s; color: %(muted)s; }

Input {
    background: %(chip_battery)s; color: %(foreground)s;
    border: none; padding: 0 1; height: 1;
}
Input:focus { background: %(chip_wlan)s; }
Input > .input--cursor { background: %(primary)s; color: %(background)s; }
Input > .input--suggestion { color: %(muted)s; }
Input > .input--placeholder { color: %(muted)s; }

Select { height: auto; }
Select > SelectCurrent {
    background: %(chip_battery)s; color: %(foreground)s;
    border: none; padding: 0 1; height: 1;
}
Select:focus > SelectCurrent { background: %(chip_wlan)s; border: none; }
Select > SelectOverlay {
    background: %(chip_battery)s; color: %(foreground)s;
    border: round %(primary)s;
}
Select > SelectOverlay > .option-list--option-highlighted { background: %(chip_audio)s; text-style: bold; }

DView { height: 1fr; }
ImagePreview { height: auto; align: center top; }
ImagePreview Image { width: auto; height: auto; }
ImagePreview .no-preview { color: %(muted)s; }

/* Popups */
ModalScreen { align: center middle; background: %(background)s 60%%; }
.modal {
    width: 76; height: auto; max-height: 90%%; overflow-y: auto;
    border: round %(primary)s;
    border-title-color: %(primary)s; border-title-style: bold;
    border-subtitle-color: %(muted)s;
    background: %(background)s; padding: 1 2;
}
.modal .field-label { color: %(muted)s; margin-top: 1; }
.modal .field-label.first { margin-top: 0; }
.modal .hint { color: %(muted)s; margin-top: 1; }
.modal .error { color: %(status_error)s; margin-top: 1; height: auto; }
.modal .message { margin-bottom: 1; }

PickModal .modal { width: 90%%; }
PickModal DataTable { height: auto; max-height: 20; }
TextModal .modal { width: 90%%; height: 90%%; }
TextModal VerticalScroll { background: %(background)s; scrollbar-size-vertical: 1; }
""")


# ── Piezas ────────────────────────────────────────────────

class KeyHints(Static):
    """Línea de atajos al pie: [("enter", "upload"), ("q", "quit")]."""

    def __init__(self, hints: list[tuple[str, str]] | None = None, **kw) -> None:
        super().__init__("", **kw)
        self.set_hints(hints or [])

    def set_hints(self, hints: list[tuple[str, str]]) -> None:
        t = Text()
        for i, (key, label) in enumerate(hints):
            if i:
                t.append("   ")
            t.append(key, style=f"bold {THEME['primary']}")
            t.append(f" {label}", style=THEME["muted"])
        self.update(t)


class Table(DataTable):
    """DataTable con los defaults de estas TUIs: selección de fila completa,
    la fila seleccionada conserva los colores propios de cada celda y j/k
    se mueven igual que las flechas (saltando encabezados de grupo)."""

    BINDINGS = [Binding("j", "cursor_down", show=False), Binding("k", "cursor_up", show=False)]

    def __init__(self, **kw) -> None:
        kw.setdefault("cursor_type", "row")
        kw.setdefault("cursor_foreground_priority", "renderable")
        super().__init__(**kw)

    def selected_key(self) -> Optional[str]:
        """Clave de la fila seleccionada (None si la tabla está vacía)."""
        if not self.row_count or self.cursor_row is None:
            return None
        return self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value

    # Filas de encabezado de grupo: su clave empieza con "hdr:" o "gap:" y el
    # cursor las saltea al moverse con flechas / j / k.
    SKIP = ("hdr:", "gap:")

    def _skippable(self, row: int) -> bool:
        try:
            return str(self.ordered_rows[row].key.value).startswith(self.SKIP)
        except IndexError:
            return False

    def _step(self, d: int) -> None:
        nxt = (self.cursor_row or 0) + d
        while 0 <= nxt < self.row_count and self._skippable(nxt):
            nxt += d
        if 0 <= nxt < self.row_count:
            self.move_cursor(row=nxt)

    def action_cursor_down(self) -> None:
        self._step(1)

    def action_cursor_up(self) -> None:
        self._step(-1)

    def first_selectable(self, start: int = 0) -> None:
        """Lleva el cursor a la primera fila seleccionable desde `start`."""
        row = max(0, min(start, self.row_count - 1))
        while row < self.row_count and self._skippable(row):
            row += 1
        if row < self.row_count:
            self.move_cursor(row=row)


def Panel(*children, title: str = "", subtitle: str = "", id: str | None = None,
          classes: str = "") -> Vertical:
    """Bloque con borde redondeado y título (estilo ratatui Block)."""
    v = Vertical(*children, id=id, classes=f"panel {classes}".strip())
    v.border_title = f" {title} " if title else ""
    v.border_subtitle = subtitle
    return v


def bar(pct: float, width: int = 20) -> Text:
    """Barra de avance en bloques, con el color primario."""
    pct = max(0.0, min(100.0, pct))
    full = int(round(pct * width / 100))
    t = Text()
    t.append("█" * full, style=THEME["primary"])
    t.append("░" * (width - full), style=THEME["border"])
    return t


def level_color(pct: float) -> str:
    """Verde < 50 %, amarillo < 80 %, rojo desde 80 % (igual que el statusline)."""
    return THEME["status_error"] if pct >= 80 else THEME["status_warn"] if pct >= 50 else THEME["status_ok"]


def meter10(pct: float, label: bool = True) -> Text:
    """Barra de 10 bloques estilo statusline de Claude Code: ▓▓▓░░░░░░░ 34%."""
    pct = max(0.0, min(100.0, pct))
    full = min(10, int(pct // 10))
    c = level_color(pct)
    t = Text()
    t.append("▓" * full, style=c)
    t.append("░" * (10 - full), style=THEME["border"])
    if label:
        t.append(f" {pct:3.0f}%", style=f"bold {c}")
    return t


def charge10(pct: float, label: bool = True) -> Text:
    """Como meter10 pero para cargas (batería): lleno es bueno. Verde desde
    50 %, amarillo desde 20 %, rojo debajo."""
    pct = max(0.0, min(100.0, pct))
    full = min(10, int(pct // 10))
    c = THEME["status_ok"] if pct >= 50 else THEME["status_warn"] if pct >= 20 else THEME["status_error"]
    t = Text()
    t.append("▓" * full, style=c)
    t.append("░" * (10 - full), style=THEME["border"])
    if label:
        t.append(f" {pct:3.0f}%", style=f"bold {c}")
    return t


def swatches(theme: dict, keys: tuple[str, ...] = THEME_KEYS, width: int = 4) -> Text:
    """Muestras de color de una paleta (un bloque por clave)."""
    t = Text()
    for k in keys:
        if k in theme:
            t.append("█" * width, style=theme[k])
            t.append(" ")
    return t


def human(n: float | int | str | None) -> str:
    """Tamaño legible; sin decimales a partir de 100 (ej. 285 MB, 1.2 GB)."""
    try:
        n = float(n or 0)
    except ValueError:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" or n >= 100 else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.0f} TB"


def ago(epoch: int | str | None, now: float | None = None) -> str:
    try:
        d = int((now or time.time()) - int(epoch))
    except (TypeError, ValueError):
        return "never"
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{d // 60} min ago"
    if d < 86400:
        return f"{d // 3600} h ago"
    return f"{d // 86400} d ago"


def duration(s: int | str | None) -> str:
    try:
        s = int(s)
    except (TypeError, ValueError):
        return "--:--"
    if s < 0:
        return "--:--"
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class PathSuggester(Suggester):
    """Autocompleta rutas locales (→ o fin acepta la sugerencia). Por
    defecto solo carpetas; con files=True también archivos."""

    def __init__(self, files: bool = False) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.files = files

    async def get_suggestion(self, value: str) -> Optional[str]:
        if not value:
            return None
        path = Path(value).expanduser()
        parent, stem = (path, "") if value.endswith("/") else (path.parent, path.name)
        try:
            for child in sorted(parent.iterdir()):
                if not (child.is_dir() or self.files) or not child.name.startswith(stem):
                    continue
                if not stem and child.name.startswith("."):
                    continue
                rest = child.name[len(stem):] + ("/" if child.is_dir() else "")
                return value + rest if rest else None
        except OSError:
            return None
        return None


class ImagePreview(Vertical):
    """Imagen en la terminal con textual-image (protocolo gráfico de kitty;
    en otras terminales cae a bloques Unicode). Sin el paquete muestra un
    texto, así la TUI anda igual."""

    def __init__(self, path: Optional[Path] = None, **kw) -> None:
        super().__init__(**kw)
        self._path = path

    def compose(self) -> ComposeResult:
        if _ImageWidget is None:
            yield Static("no preview", classes="no-preview")
        else:
            yield _ImageWidget(str(self._path) if self._path else None)

    def set_image(self, path: Optional[Path]) -> None:
        if path == self._path:
            return
        self._path = path
        if _ImageWidget is not None:
            self.query_one(_ImageWidget).image = str(path) if path and path.exists() else None


# ── Vistas ────────────────────────────────────────────────

class DView(Vertical):
    """Contenido de una TUI. Se monta solo (ViewApp) o como sección de
    Settings. Las subclases definen:
      FOCUS   selector del widget que recibe el foco al entrar
      hints() atajos del pie según el panel con foco
    y usan `self.visible_now` para pausar timers cuando la sección de
    Settings que las contiene no se está mostrando."""

    FOCUS = "Table"

    def hints(self) -> list[tuple[str, str]]:
        return []

    def update_hints(self) -> None:
        # Solo publica sus atajos si el foco está adentro de la vista (en
        # Settings el pie lo comparten el menú y la sección activa)
        f = self.app.focused
        if f is not None and self in f.ancestors_with_self:
            self.app.set_hints(self.hints())

    def on_descendant_focus(self, _event) -> None:
        self.update_hints()

    def focus_first(self) -> None:
        try:
            self.query(self.FOCUS).first().focus()
        except Exception:  # noqa: BLE001 - vista sin widgets enfocables todavía
            pass

    @property
    def visible_now(self) -> bool:
        node: Widget | None = self
        while node is not None and isinstance(node, Widget):
            if not node.display:
                return False
            node = node.parent if isinstance(node.parent, Widget) else None
        return True


# ── Popups ────────────────────────────────────────────────

@dataclass
class Field:
    key: str
    label: str
    value: str = ""
    placeholder: str = ""
    paths: bool = False          # autocompletar carpetas
    files: bool = False          # autocompletar también archivos
    password: bool = False       # ocultar lo que se escribe
    choices: list[tuple[str, str]] | None = None   # [(etiqueta, valor)] → selector


class FormModal(ModalScreen[Optional[dict]]):
    """Formulario en popup. `validate(valores) -> mensaje de error | None`."""

    BINDINGS = [Binding("escape", "cancel", "cancel"),
                Binding("tab", "app.focus_next", show=False),
                Binding("shift+tab", "app.focus_previous", show=False),
                Binding("ctrl+s", "submit", show=False)]

    def __init__(self, title: str, fields: list[Field], hint: str = "",
                 validate: Callable[[dict], Optional[str]] | None = None,
                 enter_advances: bool = False, focus: str = "") -> None:
        """enter_advances: enter pasa al campo siguiente y guarda en el último
        (para usuario → contraseña). focus: clave del campo con foco inicial."""
        super().__init__()
        self.form_title, self.fields, self.hint, self.validate = title, fields, hint, validate
        self.enter_advances, self.initial_focus = enter_advances, focus

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal") as box:
            box.border_title = f" {self.form_title} "
            if self.enter_advances:
                box.border_subtitle = " enter next · esc cancel "
            elif any(f.choices is not None for f in self.fields):
                # En un selector enter abre la lista: se guarda con ctrl+s
                box.border_subtitle = " ctrl+s save · tab next · esc cancel "
            else:
                box.border_subtitle = " enter save · tab next · esc cancel "
            for i, f in enumerate(self.fields):
                yield Label(f.label, classes="field-label" + (" first" if i == 0 else ""))
                if f.choices is not None:
                    yield Select(f.choices, value=f.value if any(v == f.value for _, v in f.choices)
                                 else f.choices[0][1], allow_blank=False, id=f"f-{f.key}")
                else:
                    yield Input(f.value, placeholder=f.placeholder, id=f"f-{f.key}", password=f.password,
                                suggester=PathSuggester(files=f.files) if (f.paths or f.files) else None)
            if self.hint:
                yield Label(self.hint, classes="hint")
            yield Label("", id="form-error", classes="error")

    def values(self) -> dict:
        out = {}
        for f in self.fields:
            w = self.query_one(f"#f-{f.key}")
            out[f.key] = str(w.value) if isinstance(w, Select) else w.value.strip()
        return out

    def action_submit(self) -> None:
        """ctrl+s guarda desde cualquier campo (también desde un selector)."""
        vals = self.values()
        err = self.validate(vals) if self.validate else None
        if err:
            self.query_one("#form-error", Label).update(f"✗ {err}")
            return
        self.dismiss(vals)

    def on_mount(self) -> None:
        if self.initial_focus:
            self.query_one(f"#f-{self.initial_focus}", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self.enter_advances and event.input.id != f"f-{self.fields[-1].key}":
            self.focus_next()
            return
        self.action_submit()

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [Binding("escape,n", "no", "no"), Binding("y,enter", "yes", "yes")]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.c_title, self.message = title, message

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal") as box:
            box.border_title = f" {self.c_title} "
            yield Label(self.message, classes="message")
            yield KeyHints([("y", "yes"), ("n", "no")])

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class PickModal(ModalScreen[Optional[str]]):
    """Elegir una fila de una tabla en popup. rows: [(clave, [celdas...])]."""

    BINDINGS = [Binding("escape", "cancel", "cancel")]

    def __init__(self, title: str, columns: list[str], rows: list[tuple[str, list]],
                 hint: str = "enter select · esc cancel") -> None:
        super().__init__()
        self.p_title, self.columns, self.rows, self.hint = title, columns, rows, hint

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal") as box:
            box.border_title = f" {self.p_title} "
            box.border_subtitle = f" {self.hint} "
            yield Table(id="pick")

    def on_mount(self) -> None:
        t = self.query_one("#pick", DataTable)
        t.add_columns(*self.columns)
        for key, cells in self.rows:
            t.add_row(*cells, key=key)
        t.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()   # que no le llegue también a la vista de atrás
        self.dismiss(event.row_key.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextModal(ModalScreen[None]):
    """Texto largo de solo lectura (logs). end=True arranca abajo de todo."""

    BINDINGS = [Binding("escape,q", "close", "close")]

    def __init__(self, title: str, text: str | Text, end: bool = True) -> None:
        super().__init__()
        self.t_title, self.text, self.end = title, text, end

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal") as box:
            box.border_title = f" {self.t_title} "
            box.border_subtitle = " ↑↓ scroll · esc close "
            with VerticalScroll():
                yield Static(self.text)

    def on_mount(self) -> None:
        scroll = self.query_one(VerticalScroll)
        scroll.focus()
        if self.end:
            self.call_after_refresh(scroll.scroll_end, animate=False)

    def action_close(self) -> None:
        self.dismiss(None)


# ── Apps ──────────────────────────────────────────────────

class DApp(App):
    """App base: aplica BASE_CSS + el CSS propio de cada TUI. `q` sale y
    `esc` llama a action_leave (salir; Settings lo pisa para volver al menú)."""

    CSS = BASE_CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("q", "quit", "quit", show=False),
                Binding("escape", "leave", "back", show=False)]

    def check_action(self, action: str, parameters) -> Optional[bool]:
        # Con un popup abierto, las teclas de la pantalla principal (las
        # BINDINGS de la app) no hacen nada; las de Textual siguen andando.
        if isinstance(self.screen, ModalScreen) and action in {
                b.action for b in self.BINDINGS if isinstance(b, Binding)}:
            return False
        return True

    def set_hints(self, hints: list[tuple[str, str]]) -> None:
        """Atajos del pie de la pantalla principal (no de un popup)."""
        try:
            self.screen_stack[0].query_one("#hints", KeyHints).set_hints(hints)
        except Exception:  # noqa: BLE001 - todavía sin montar
            pass

    def action_leave(self) -> None:
        self.exit()

    def notify_ok(self, msg: str) -> None:
        self.notify(msg, timeout=3)

    def notify_err(self, msg: str) -> None:
        self.notify(msg, severity="error", timeout=5)


class ViewApp(DApp):
    """Una DView sola como app (las TUIs sueltas: `ViewApp(BackupView).run()`)."""

    def __init__(self, view_cls: type[DView], title: str = "", **view_kw) -> None:
        super().__init__()
        self.view = view_cls(**view_kw)
        self.title = title

    def compose(self) -> ComposeResult:
        yield self.view
        yield KeyHints(id="hints")

    def on_mount(self) -> None:
        self.view.focus_first()
        self.call_after_refresh(self.view.update_hints)
