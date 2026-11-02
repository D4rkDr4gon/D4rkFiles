#!/usr/bin/env python3
"""
launcher_tui.py — lanzador y menús rápidos con la estética de las TUIs propias.
Reemplaza a rofi (config/rofi/scripts/*): una sola TUI con un buscador arriba y una
lista abajo, que se abre en frío en una kitty centrada (center-tui-launch.sh).

Modos (primer argumento):
  apps        Mod+Space. Apps de los .desktop (favoritas y más usadas arriba) y,
              según lo que se escriba: resultado de una cuenta (enter lo copia),
              un comando de $PATH con argumentos y búsqueda web (workspace 5).
  emoji       Mod+E. Busca por nombre en inglés; enter copia el emoji.
  power       Mod+L. Bloquear, suspender, cerrar sesión, reiniciar, apagar
              (los tres últimos piden confirmación).
  workspaces  Clic en los workspaces de waybar. Lista 1..N con sus ventanas.
  dmenu       Menú genérico para scripts (lo usa scripts/dmenu.sh, reemplazo de
              `rofi -dmenu`): --input F (una opción por línea), --output F (la
              elegida; con --index, su número), --prompt, --placeholder,
              --no-custom (sin ella, enter sobre algo que no está devuelve lo escrito).

Lo que lanza se desprende de la kitty: en Hyprland por hypr-dispatch exec, si no
con setsid. Estado (uso de cada app, para ordenar) en
~/.local/state/dotfiles/launcher-history.json; favoritas en
~/.config/dotfiles/launcher-favorites.txt (f en la lista, a la que se pasa con tab,
o ctrl+f desde el buscador las agregan/sacan). El navegador de la búsqueda web es
BROWSER de ~/.config/dotfiles/user.conf. Estilo común: tools/dtui.py. Textos
visibles en inglés.
"""

from __future__ import annotations

import ast
import json
import math
import operator
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import THEME, ConfirmModal, DView, Panel, Table, ViewApp, css  # noqa: E402

from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.widgets import DataTable, Input  # noqa: E402

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de tools/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
HYPRLAND = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
HYPR_DISPATCH = str(Path.home() / ".config" / "hypr" / "scripts" / "hypr-dispatch")
EMOJI_FILE = Path(__file__).resolve().parent / "launcher_emoji.txt"
CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dotfiles"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "dotfiles"
FAVORITES = Path(os.environ.get("LAUNCHER_FAVORITES") or CONF_DIR / "launcher-favorites.txt")
HISTORY = Path(os.environ.get("LAUNCHER_HISTORY") or STATE_DIR / "launcher-history.json")
WS_CONF = CONF_DIR / "hypr" / "workspaces.conf"
BROWSER_WS = "5"          # workspace reservado al navegador (como el web-search de rofi)
MAX_ROWS = 200            # filas visibles como mucho (la lista entera de apps entra igual)


# ── Ítems y búsqueda ──────────────────────────────────────

@dataclass
class Item:
    key: str
    label: str
    icon: str = ""
    detail: str = ""
    terms: str = ""                 # texto extra donde se busca (no se ve)
    boost: float = 0.0              # favoritas / uso
    data: dict = field(default_factory=dict)
    style: str = ""


def score(q: str, item: Item) -> float:
    """0 = no matchea. Todas las palabras de la búsqueda tienen que aparecer;
    pesa más en el nombre (exacto > prefijo > inicio de palabra > adentro >
    letras en orden) que en el resto de los términos."""
    name = item.label.lower()
    rest = f"{item.detail} {item.terms}".lower()
    total = 0.0
    for tok in q.split():
        if name == tok:
            s = 100
        elif name.startswith(tok):
            s = 80
        elif re.search(r"(^|[\s\-_./(])" + re.escape(tok), name):
            s = 60
        elif tok in name:
            s = 40
        elif tok in rest:
            s = 15
        elif len(tok) > 1 and _subseq(tok, name):
            s = 10
        else:
            return 0.0
        total += s
    return total + item.boost


def _subseq(tok: str, text: str) -> bool:
    it = iter(text)
    return all(c in it for c in tok)


# ── Lanzar cosas ──────────────────────────────────────────

def spawn(cmd: str) -> None:
    """Lanza un comando de shell desprendido de esta kitty."""
    if HYPRLAND and Path(HYPR_DISPATCH).exists():
        subprocess.Popen([HYPR_DISPATCH, "exec", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        env = {k: v for k, v in os.environ.items() if not k.startswith("KITTY_")}
        subprocess.Popen(["setsid", "-f", "sh", "-c", cmd], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def goto_workspace(ws: str) -> None:
    if HYPRLAND:
        subprocess.run([HYPR_DISPATCH, "workspace", ws], capture_output=True)


def copy_text(text: str, osd: str = "Copied") -> None:
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text.encode())
    if shutil.which("swayosd-client") and os.environ.get("WAYLAND_DISPLAY"):
        subprocess.Popen(["swayosd-client", "--custom-message", osd, "--custom-icon", "edit-copy-symbolic"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["notify-send", "-t", "1500", osd, text[:80]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def browser() -> str:
    """BROWSER del entorno o de user.conf; si no, el primero instalado."""
    b = os.environ.get("BROWSER", "")
    if not b:
        try:
            m = re.search(r"^\s*BROWSER=[\"']?([^\"'\n]+)", (CONF_DIR / "user.conf").read_text(), re.M)
            b = m.group(1).strip() if m else ""
        except OSError:
            pass
    return b or next((c for c in ("firefox", "chromium", "brave-browser", "google-chrome-stable", "librewolf")
                      if shutil.which(c)), "xdg-open")


def web_search(q: str) -> None:
    goto_workspace(BROWSER_WS)
    spawn(browser() + " " + shlex.quote("https://www.google.com/search?q=" + urllib.parse.quote_plus(q)))


# ── Calculadora (sin eval: solo números, operadores y math.*) ──

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_NAMES = {k: getattr(math, k) for k in ("pi", "e", "tau")}
_FUNCS = {k: getattr(math, k) for k in ("sqrt", "sin", "cos", "tan", "log", "log10", "log2", "exp",
                                        "floor", "ceil", "factorial", "radians", "degrees")} | {"abs": abs,
                                                                                                "round": round}


def calc(q: str) -> Optional[str]:
    """Resultado de una cuenta, o None si no es una. Acepta `x` y `^`, y coma decimal."""
    s = q.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    s = re.sub(r"(?<=[\d)\s])x(?=[\d(\s])", "*", s)
    if not re.search(r"\d", s) or not re.search(r"[-+*/%()]|[a-z]\(", s) or len(s) > 200:
        return None

    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 1000:
                raise ValueError("too big")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Name) and n.id in _NAMES:
            return _NAMES[n.id]
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS
                and not n.keywords):
            vals = [ev(a) for a in n.args]
            if n.func.id == "factorial" and any(abs(v) > 500 for v in vals):
                raise ValueError("too big")
            return _FUNCS[n.func.id](*vals)
        raise ValueError("unsupported")

    try:
        r = ev(ast.parse(s, mode="eval"))
    except Exception:  # noqa: BLE001 - cualquier cosa que no sea una cuenta válida
        return None
    if isinstance(r, float):
        if math.isnan(r) or math.isinf(r):
            return None
        if r.is_integer() and abs(r) < 1e15:
            return str(int(r))
        return f"{r:.10g}"
    return str(r)


# ── Fuentes de ítems ──────────────────────────────────────

class Source:
    title = ""
    list_title = ""
    placeholder = "type to search…"
    enter_label = "select"

    def items(self) -> list[Item]:
        return []

    def extra(self, q: str) -> tuple[list[Item], list[Item]]:
        """Filas que dependen de lo escrito: (antes de la lista, después)."""
        return [], []

    def act(self, item: Optional[Item], query: str, view: "LauncherView") -> None:
        view.app.exit()

    def subtitle(self, shown: int, total: int, q: str) -> str:
        return f" {shown} of {total} " if q else f" {total} "

    # Favoritas: solo las fuentes que las soportan (apps) las pisan
    can_favorite = False

    def toggle_favorite(self, item: Item) -> Optional[bool]:
        """Agrega o saca el ítem de favoritas: True = quedó favorita, False = se sacó,
        None = no se puede (ítem que no es una app)."""
        return None


# Apps ─────────────────────────────────────────────────────

CATEGORY_ICONS = [
    ("TerminalEmulator", ""), ("WebBrowser", "󰖟"), ("Email", "󰇮"), ("Chat", "󰭹"),
    ("InstantMessaging", "󰭹"), ("Development", "󰅨"), ("IDE", "󰅨"), ("TextEditor", "󰷈"),
    ("Office", "󰈙"), ("Graphics", "󰋩"), ("Audio", "󰝚"), ("Video", "󰕧"), ("AudioVideo", "󰝚"),
    ("Game", "󰊗"), ("Security", "󰒃"), ("FileManager", "󰉋"), ("Settings", "󰒓"), ("System", "󰒓"),
    ("Network", "󰖟"), ("Education", "󰑴"), ("Science", "󰑴"), ("Utility", "󰘔"),
]
FIELD_CODE = re.compile(r"\s*%[fFuUdDnNickvm]")


def data_dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    rest = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return [home / "applications"] + [Path(d) / "applications" for d in rest if d]


def parse_desktop(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    d: dict[str, str] = {}
    in_main = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_main = line == "[Desktop Entry]"
            continue
        if in_main and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            d.setdefault(k.strip(), v.strip())
    return d


def desktop_apps() -> list[dict]:
    """Entradas visibles de los .desktop (la del usuario pisa a la del sistema)."""
    desktops = set(filter(None, (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower().split(":")))
    seen: dict[str, dict] = {}
    for base in data_dirs():
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.desktop")):
            did = str(p.relative_to(base)).replace("/", "-")
            if did in seen:
                continue
            d = parse_desktop(p)
            seen[did] = d or {}
            if not d or d.get("Type") != "Application" or not d.get("Name") or not d.get("Exec"):
                continue
            if d.get("NoDisplay", "").lower() == "true" or d.get("Hidden", "").lower() == "true":
                seen[did] = {}
                continue
            only = {x.lower() for x in d.get("OnlyShowIn", "").split(";") if x}
            never = {x.lower() for x in d.get("NotShowIn", "").split(";") if x}
            if (only and desktops and not only & desktops) or (never & desktops):
                seen[did] = {}
                continue
            if d.get("TryExec") and not shutil.which(os.path.expanduser(d["TryExec"])):
                seen[did] = {}
                continue
            d["_id"] = did
    return [d for d in seen.values() if d.get("_id")]


def app_icon(d: dict) -> str:
    if "firefoxpwa" in d.get("Exec", "") or d.get("StartupWMClass", "").startswith("FFPWA"):
        return "󰖟"
    cats = d.get("Categories", "").split(";")
    return next((icon for cat, icon in CATEGORY_ICONS if cat in cats), "󰀻")


def app_command(d: dict) -> str:
    cmd = FIELD_CODE.sub("", d["Exec"]).replace("%%", "%").strip()
    if d.get("Terminal", "").lower() == "true":
        cmd = f"kitty -e {cmd}"
    if d.get("Path"):
        cmd = f"cd {shlex.quote(d['Path'])} && {cmd}"
    return cmd


def load_history() -> dict:
    try:
        h = json.loads(HISTORY.read_text())
        return h if isinstance(h, dict) else {}
    except (OSError, ValueError):
        return {}


def bump_history(key: str) -> None:
    h = load_history()
    count, _ = h.get(key, [0, 0])
    h[key] = [count + 1, int(time.time())]
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY.with_name(HISTORY.name + ".tmp")
    tmp.write_text(json.dumps(h))
    os.replace(tmp, HISTORY)


def frecency(entry: list, now: float) -> float:
    """Uso con decaimiento: lo usado esta semana pesa más que lo de hace meses."""
    count, last = entry
    age_days = max(0.0, (now - last) / 86400)
    return min(count, 50) * (1.0 if age_days < 7 else 0.5 if age_days < 30 else 0.2)


def read_favorites() -> list[str]:
    """Nombres favoritos (en minúsculas) de launcher/favorites.txt."""
    try:
        return [l.strip().lower() for l in FAVORITES.read_text().splitlines()
                if l.strip() and not l.lstrip().startswith("#")]
    except OSError:
        return []


def set_favorite(name: str, on: bool) -> None:
    """Agrega `name` al final o saca sus líneas (sin distinguir mayúsculas),
    respetando comentarios y el resto. Escritura atómica."""
    try:
        lines = FAVORITES.read_text().splitlines()
    except OSError:
        lines = ["# Apps favoritas del lanzador (Mod+Space): una por línea, el Name del .desktop.",
                 "# Se agregan y sacan con f (lista) o ctrl+f (buscador)."]
    lines = [l for l in lines if l.lstrip().startswith("#") or l.strip().lower() != name.lower()]
    while lines and not lines[-1].strip():
        lines.pop()
    if on:
        lines.append(name)
    FAVORITES.parent.mkdir(parents=True, exist_ok=True)
    tmp = FAVORITES.with_name(FAVORITES.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, FAVORITES)


class AppsSource(Source):
    title = "  Launch"
    list_title = "Apps"
    placeholder = "apps, commands, math or a web search…"
    enter_label = "launch"
    can_favorite = True

    def toggle_favorite(self, item: Item) -> Optional[bool]:
        if not item.key.startswith("app:"):
            return None
        on = not item.data.get("fav")
        set_favorite(item.label, on)
        return on

    def items(self) -> list[Item]:
        favs = read_favorites()
        hist, now = load_history(), time.time()
        out = []
        for d in desktop_apps():
            name = d["Name"]
            fav = name.lower() in favs
            boost = frecency(hist.get(d["_id"], [0, 0]), now) + (30 if fav else 0)
            out.append(Item(
                key=f"app:{d['_id']}", label=name, icon=("★" if fav else app_icon(d)),
                detail=d.get("GenericName") or d.get("Comment", ""),
                terms=" ".join([d.get("Keywords", "").replace(";", " "), d.get("Categories", "").replace(";", " "),
                                Path(d["Exec"].split()[0]).name, d["_id"]]),
                boost=boost, data={"cmd": app_command(d), "id": d["_id"], "fav": fav},
                style=THEME["primary"] if fav else ""))
        # Sin búsqueda: favoritas, después las más usadas, después alfabético
        out.sort(key=lambda i: (-i.boost, i.label.lower()))
        return out

    def extra(self, q: str) -> tuple[list[Item], list[Item]]:
        q = q.strip()
        if not q:
            return [], []
        before, after = [], []
        result = calc(q)
        if result is not None:
            before.append(Item(key="calc", label=f"= {result}", icon="󰃬", detail="enter copies the result",
                               data={"result": result}, style=f"bold {THEME['status_ok']}"))
        first = q.split()[0]
        if result is None and shutil.which(first):
            after.append(Item(key="run", label=q, icon="", detail="run command", data={"cmd": q}))
        after.append(Item(key="web", label=q, icon="󰖟", detail="search the web", data={"q": q},
                          style=THEME["muted"]))
        return before, after

    def act(self, item: Optional[Item], query: str, view: "LauncherView") -> None:
        if item is None:
            if query.strip():
                web_search(query.strip())
            return view.app.exit()
        if item.key == "calc":
            copy_text(item.data["result"], f"Copied {item.data['result']}")
        elif item.key == "run":
            spawn(item.data["cmd"])
        elif item.key == "web":
            web_search(item.data["q"])
        else:
            bump_history(item.data["id"])
            spawn(item.data["cmd"])
        view.app.exit()


# Emoji ────────────────────────────────────────────────────

class EmojiSource(Source):
    title = "󰞅  Emoji"
    list_title = "Emoji"
    placeholder = "search emoji (in English)…"
    enter_label = "copy"

    def items(self) -> list[Item]:
        out = []
        try:
            lines = EMOJI_FILE.read_text().splitlines()
        except OSError:
            return out
        for i, line in enumerate(lines):
            emoji, _, name = line.partition(" ")
            if emoji and name:
                out.append(Item(key=f"e{i}", label=name, icon=emoji, data={"emoji": emoji}))
        return out

    def act(self, item: Optional[Item], query: str, view: "LauncherView") -> None:
        if item is not None:
            copy_text(item.data["emoji"], f"Copied {item.data['emoji']}")
        view.app.exit()


# Power ────────────────────────────────────────────────────

POWER = [("lock", "󰌾", "Lock", "lock the screen", False),
         ("suspend", "󰒲", "Suspend", "sleep, keeps the session", False),
         ("logout", "󰍃", "Log out", "close the session", True),
         ("reboot", "󰜉", "Reboot", "restart the computer", True),
         ("poweroff", "󰐥", "Power off", "shut down the computer", True)]


class PowerSource(Source):
    title = "󰐥  Session"
    placeholder = "lock, suspend, log out, reboot, power off…"

    def items(self) -> list[Item]:
        return [Item(key=k, label=name, icon=icon, detail=desc, data={"confirm": confirm},
                     style=THEME["status_error"] if k == "poweroff" else "")
                for k, icon, name, desc, confirm in POWER]

    def subtitle(self, shown: int, total: int, q: str) -> str:
        return ""

    def act(self, item: Optional[Item], query: str, view: "LauncherView") -> None:
        if item is None:
            return

        def go() -> None:
            k = item.key
            if k == "lock":
                spawn(f"bash {DOTFILES / 'scripts' / 'lock-screen.sh'}")
            elif k == "suspend":
                subprocess.Popen(["systemctl", "suspend"])
            elif k == "logout":
                subprocess.Popen([HYPR_DISPATCH, "exit"])
            elif subprocess.run(["systemctl", k], capture_output=True).returncode != 0:
                # polkit no lo dejó: con sudo en esta misma terminal
                with view.app.suspend():
                    os.system("clear")
                    subprocess.run(["sudo", "systemctl", k])
            view.app.exit()

        if not item.data["confirm"]:
            return go()
        view.app.push_screen(ConfirmModal(item.label, f"{item.label} now? Unsaved work in open apps will be lost."),
                             lambda yes: yes and go())


# Workspaces ───────────────────────────────────────────────

def workspace_count() -> int:
    if not HYPRLAND:
        return 6
    try:
        m = re.search(r"^# count:\s*(\d+)", WS_CONF.read_text(), re.M)
        return int(m.group(1)) if m else 9
    except OSError:
        return 9


def hypr_json(*args: str):
    try:
        return json.loads(subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True,
                                         timeout=3).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


class WorkspacesSource(Source):
    title = "  Workspaces"
    list_title = "Workspaces"
    placeholder = "number or window name…"
    enter_label = "go"

    def items(self) -> list[Item]:
        n = workspace_count()
        wins: dict[str, list[str]] = {}
        active = ""
        if HYPRLAND:
            for c in hypr_json("clients") or []:
                ws = str((c.get("workspace") or {}).get("id", ""))
                wins.setdefault(ws, []).append(c.get("class") or c.get("title") or "?")
            active = str((hypr_json("activeworkspace") or {}).get("id", ""))
        out = []
        for i in range(1, n + 1):
            ws = str(i)
            apps = wins.get(ws, [])
            here = ws == active
            out.append(Item(key=ws, label=f"Workspace {ws}", icon="●" if here else ("◆" if apps else "○"),
                            detail=", ".join(dict.fromkeys(apps)) or "empty", terms=ws,
                            style=f"bold {THEME['primary']}" if here else ("" if apps else THEME["muted"])))
        return out

    def act(self, item: Optional[Item], query: str, view: "LauncherView") -> None:
        if item is None and query.strip().isdigit():
            goto_workspace(query.strip())
        elif item is not None:
            goto_workspace(item.key)
        view.app.exit()


# Dmenu ────────────────────────────────────────────────────

class DmenuSource(Source):
    def __init__(self, lines: list[str], output: Optional[Path], prompt: str = "", placeholder: str = "",
                 custom: bool = True, index: bool = False) -> None:
        self.lines, self.output, self.custom, self.index = lines, output, custom, index
        self.title = prompt or "Select"
        if placeholder:
            self.placeholder = placeholder

    def items(self) -> list[Item]:
        return [Item(key=str(i), label=l) for i, l in enumerate(self.lines)]

    def write(self, text: str) -> None:
        if self.output is not None:
            self.output.write_text(text + "\n")
        else:
            sys.stdout.write(text + "\n")

    def act(self, item: Optional[Item], query: str, view: "LauncherView") -> None:
        if item is not None:
            self.write(item.key if self.index else self.lines[int(item.key)])
        elif self.custom and query.strip() and not self.index:
            self.write(query)
        else:
            return
        view.app.exit()


# ── Vista ─────────────────────────────────────────────────

class LauncherView(DView):
    """Buscador + lista. Escribir filtra, ↑↓ mueven, enter elige, esc cierra.
    tab pasa a la lista (ahí las letras no se escriben: f marca/desmarca favorita,
    j/k mueven, cualquier otra letra vuelve al buscador y se escribe)."""

    FOCUS = "#ln-search"
    BINDINGS = [
        Binding("down,ctrl+n", "move(1)", show=False, priority=True, description="next item"),
        Binding("up,ctrl+p", "move(-1)", show=False, priority=True, description="previous item"),
        Binding("pagedown", "move(10)", show=False, description="ten down"),
        Binding("pageup", "move(-10)", show=False, description="ten up"),
        Binding("tab", "switch", show=False, description="search ↔ list"),
        Binding("f", "favorite", show=False, description="add/remove favorite (in the list)"),
        # priority: con el buscador enfocado el Input se comería ctrl+f
        Binding("ctrl+f", "favorite_search", show=False, priority=True, description="add/remove favorite (from search)"),
    ]

    def __init__(self, source: Source, query: str = "", **kw) -> None:
        super().__init__(**kw)
        self.source = source
        self.initial = query
        self.all: list[Item] = []
        self.shown: list[Item] = []

    def compose(self) -> ComposeResult:
        yield Panel(Input(placeholder=self.source.placeholder, id="ln-search", value=self.initial),
                    title=self.source.title, id="ln-search-panel")
        yield Panel(Table(id="ln-list", show_header=False), title=self.source.list_title, id="ln-list-panel")

    def on_mount(self) -> None:
        t = self.query_one("#ln-list", Table)
        t.add_column("", key="icon", width=2)
        t.add_column("", key="label")
        t.add_column("", key="detail")
        self.all = self.source.items()
        self.filter()

    def in_list(self) -> bool:
        return self.app.focused is self.query_one("#ln-list", Table)

    def hints(self) -> list[tuple[str, str]]:
        h = [("enter", self.source.enter_label), ("↑↓", "move")]
        if self.source.can_favorite:
            fav = (self.current() or Item("", "")).data.get("fav")
            h.append(("f" if self.in_list() else "ctrl+f", "unfavorite" if fav else "favorite"))
        return h + [("tab", "search" if self.in_list() else "list"), ("esc", "close")]

    # ── datos ──

    def filter(self) -> None:
        q = self.query_one("#ln-search", Input).value
        ql = q.strip().lower()
        if ql:
            scored = [(s, i) for i in self.all if (s := score(ql, i)) > 0]
            scored.sort(key=lambda p: (-p[0], p[1].label.lower()))
            matches = [i for _, i in scored]
        else:
            matches = list(self.all)
        before, after = self.source.extra(q)
        self.shown = before + matches[:MAX_ROWS] + after
        t = self.query_one("#ln-list", Table)
        t.clear()
        muted = THEME["muted"]
        for n, it in enumerate(self.shown):
            t.add_row(Text(it.icon, style=it.style or THEME["primary"]),
                      Text(it.label, style=it.style, no_wrap=True, overflow="ellipsis"),
                      Text(it.detail, style=muted, no_wrap=True, overflow="ellipsis"), key=str(n))
        self.query_one("#ln-list-panel").border_subtitle = self.source.subtitle(len(matches), len(self.all), ql)

    def current(self) -> Optional[Item]:
        t = self.query_one("#ln-list", Table)
        if not self.shown or t.cursor_row is None or t.cursor_row >= len(self.shown):
            return None
        return self.shown[t.cursor_row]

    # ── eventos ──

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "ln-search":
            self.filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "ln-search":
            event.stop()
            self.choose()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "ln-list":
            self.choose()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "ln-list" and self.source.can_favorite:
            self.update_hints()   # "favorite" / "unfavorite" según la fila

    def on_key(self, event) -> None:
        # En la lista, una letra que no es atajo vuelve al buscador y se escribe ahí
        if self.in_list() and event.is_printable and event.character and event.character not in "fjkq":
            event.stop()
            inp = self.query_one("#ln-search", Input)
            inp.focus()
            inp.insert_text_at_cursor(event.character)

    def action_switch(self) -> None:
        target = "#ln-search" if self.in_list() else "#ln-list"
        self.query_one(target).focus()

    def action_favorite_search(self) -> None:
        self.action_favorite()   # id propio en el keymap (f y ctrl+f se reasignan por separado)

    def action_favorite(self) -> None:
        it = self.current()
        if it is None or not self.source.can_favorite:
            return
        on = self.source.toggle_favorite(it)
        if on is None:
            return self.app.notify_err("Only apps can be favorites")
        self.all = self.source.items()
        self.filter()
        # Volver a la misma app, que cambió de lugar (las favoritas van arriba)
        row = next((n for n, i in enumerate(self.shown) if i.key == it.key), 0)
        self.query_one("#ln-list", Table).move_cursor(row=row)
        self.update_hints()
        self.app.notify_ok(f"{it.label} {'added to' if on else 'removed from'} favorites")

    def action_move(self, step: int) -> None:
        t = self.query_one("#ln-list", Table)
        if t.row_count:
            t.move_cursor(row=max(0, min(t.row_count - 1, (t.cursor_row or 0) + step)))

    def choose(self) -> None:
        self.source.act(self.current(), self.query_one("#ln-search", Input).value, self)


# ── Arranque ──────────────────────────────────────────────

class LauncherApp(ViewApp):
    # En el CSS de la app (no DEFAULT_CSS de la vista) para ganarle a BASE_CSS:
    # el buscador sin fondo propio y la fila elegida marcada aunque el foco
    # esté en el buscador (la lista nunca recibe foco).
    CSS = ViewApp.CSS + css("""
    #ln-search-panel { height: 3; }
    #ln-search, #ln-search:focus { background: %(background)s; padding: 0; }
    #ln-list-panel { height: 1fr; }
    #ln-list > .datatable--cursor { background: %(chip_audio)s; text-style: bold; }
    """)


SOURCES: dict[str, Callable[[], Source]] = {
    "apps": AppsSource, "emoji": EmojiSource, "power": PowerSource, "workspaces": WorkspacesSource,
}
TITLES = {"apps": "Launcher", "emoji": "Emoji", "power": "Session", "workspaces": "Workspaces", "dmenu": "Menu"}


def opt(args: list[str], name: str, default: str = "") -> str:
    return args[args.index(name) + 1] if name in args[:-1] else default


def build(args: list[str]) -> ViewApp:
    mode = args[0] if args and not args[0].startswith("-") else "apps"
    if mode == "dmenu":
        inp = opt(args, "--input")
        out = opt(args, "--output")
        lines = (Path(inp).read_text() if inp else "").splitlines()
        src: Source = DmenuSource([l for l in lines if l.strip()], Path(out) if out else None,
                                  prompt=opt(args, "--prompt"), placeholder=opt(args, "--placeholder"),
                                  custom="--no-custom" not in args, index="--index" in args)
    elif mode in SOURCES:
        src = SOURCES[mode]()
    else:
        sys.exit(f"usage: {Path(__file__).name} [apps|emoji|power|workspaces|dmenu …]")
    return LauncherApp(LauncherView, title=TITLES.get(mode, "Launcher"), source=src, query=opt(args, "--query"))


if __name__ == "__main__":
    build(sys.argv[1:]).run()
