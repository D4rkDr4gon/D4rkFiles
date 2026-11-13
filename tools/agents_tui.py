#!/usr/bin/env python3
"""
agents_tui.py — panel de agentes IA (módulo waybar "custom/claude-agents" y
sección AI Agents de Settings).

Un panel por proveedor activo en ~/.config/dotfiles/agents.conf (claude, opencode,
codex, antigravity): límites de uso (ventanas de 5 h / 7 d o cuota por
modelo) y el contexto de cada sesión abierta, con barras que pasan a
amarillo/rojo al 50/80 %. `c` abre claude, `o` opencode. En Settings se
suma el panel Providers para prender/apagar cada uno (manage=True); el
popup de waybar y el módulo de la barra leen la misma config. También en
Settings, entre Providers y los paneles de uso: Skills y Agents (cuáles se cargan en
Claude Code y opencode, más lo que Claude trae por su cuenta; backend en agent_skills.py).
`f` abre las carpetas de origen (la primera gana). Settings lo muestra en páginas (tab / 1-5):
Usage (Providers + uso), Skills, Agents, MCPs y LSPs (backend de estas dos en agent_tools.py).

Fuentes (las escriben otros programas, acá solo se leen):
- Claude Code: ~/.claude/usage-cache.json (5h/7d) y usage-cache.d/*.json (una
  entrada por sesión), que escribe config/claude/statusline-command.sh.
- opencode: config/waybar/scripts/opencode-context.sh (lee su base SQLite).
- Codex: ~/.codex/sessions/AAAA/MM/DD/rollout-*.jsonl ($CODEX_HOME): eventos
  `token_count` con uso por turno, `model_context_window` y `rate_limits`
  (primary/secondary: used_percent, window_minutes, resets_at o
  resets_in_seconds). La ventana se identifica por window_minutes (~300 =
  5 h, ~10080 = 7 d): según la versión, primary puede ser la semanal.
- Antigravity (agy): ~/.cache/agents/agy/*.json, que escribe
  config/agents/agy-statusline.sh desde el statusLine de ~/.gemini/antigravity-cli/
  settings.json (context_window.used_percentage, quota[modelo]
  .remaining_fraction / reset_in_seconds).

`--rows` imprime cuántas filas necesita la ventana con lo abierto ahora (lo
usa claude-agents-launch.sh para abrirla del alto justo).

Estilo común de las TUIs: tools/dtui.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import THEME, ConfirmModal, DView, Field, FormModal, KeyHints, Panel, Table, ViewApp, css  # noqa: E402
import agent_skills as sk  # noqa: E402
import agent_tools as at  # noqa: E402
import provider_sources as ps  # noqa: E402

from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Vertical, VerticalScroll  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual import work  # noqa: E402
from textual.widgets import ContentSwitcher, DataTable, Label, Static  # noqa: E402

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de tools/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
PROVIDERS_CONF = Path(os.environ.get("AGENTS_PROVIDERS") or CONFIG_HOME / "dotfiles" / "agents.conf")
CLAUDE = Path.home() / ".claude"
CACHE = CLAUDE / "usage-cache.json"
CACHE_DIR = CLAUDE / "usage-cache.d"
OPENCODE_SCRIPT = DOTFILES / "config" / "waybar" / "scripts" / "opencode-context.sh"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
AGY_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "agents" / "agy"
FRESH_SECONDS = 1800   # una sesión sin refrescos en 30 min se da por cerrada
MAX_AGENTS = 12        # filas máximas por sección (el resto: "+N más")
LABEL_W = 34
BAR_W = 14
CODEX_BASELINE = 12000  # tokens fijos del prompt de sistema de Codex (igual que su propia UI)

# id, nombre, ícono, binario (para saber si está instalado)
PROVIDERS = [
    ("claude", "Claude Code", "󰚩", "claude"),
    ("opencode", "opencode", "󰘦", "opencode"),
    ("codex", "Codex", "󰅩", "codex"),
    ("antigravity", "Antigravity", "󰫢", "agy"),
]
DEFAULT_ON = {"claude", "opencode"}
# páginas de Settings (manage=True): id del contenedor, rótulo, tabla que recibe el foco
PAGES = [("body", "Usage", "providers"), ("skills-page", "Skills", "skill-list"),
         ("agents-page", "Agents", "agent-list"), ("mcp-page", "MCPs", "mcp-list"), ("lsp-page", "LSPs", "lsp-list")]
TOOL_PROVIDERS = (("claude", "Claude Code", "󰚩"), ("opencode", "opencode", "󰘦"))   # los que tienen MCP/LSP


# ── providers.conf ────────────────────────────────────────

def enabled_providers() -> set[str]:
    """Proveedores activos (líneas `id=on|off`; sin archivo, los default)."""
    try:
        lines = PROVIDERS_CONF.read_text().splitlines()
    except OSError:
        return set(DEFAULT_ON)
    on = set()
    for l in lines:
        k, _, v = l.strip().partition("=")
        if k and not k.startswith("#") and v.strip() == "on":
            on.add(k.strip())
    return on


def set_provider(pid: str, on: bool) -> None:
    """Cambia una línea de providers.conf conservando comentarios y orden."""
    try:
        lines = PROVIDERS_CONF.read_text().splitlines()
    except OSError:
        lines = [f"{p}={'on' if p in DEFAULT_ON else 'off'}" for p, *_ in PROVIDERS]
    found = False
    for i, l in enumerate(lines):
        if l.split("=", 1)[0].strip() == pid:
            lines[i], found = f"{pid}={'on' if on else 'off'}", True
    if not found:
        lines.append(f"{pid}={'on' if on else 'off'}")
    PROVIDERS_CONF.parent.mkdir(parents=True, exist_ok=True)
    PROVIDERS_CONF.write_text("\n".join(lines) + "\n")


# ── helpers ───────────────────────────────────────────────

# Hyprland (y lo que se abre desde un atajo o desde waybar) arranca con un PATH
# mínimo, sin ~/.local/bin ni las carpetas de instaladores por usuario: además
# del PATH se buscan acá los binarios de los agentes.
USER_BIN_DIRS = [Path.home() / d for d in (".local/bin", ".opencode/bin", ".bun/bin", ".npm-global/bin",
                                           ".cargo/bin", ".claude/local", "go/bin")] + [Path("/opt/bin")]


def find_bin(name: str) -> Optional[str]:
    """Ruta del binario de un agente (PATH + carpetas por usuario) o None."""
    found = shutil.which(name)
    if found:
        return found
    for d in USER_BIN_DIRS:
        f = d / name
        if f.is_file() and os.access(f, os.X_OK):
            return str(f)
    return None


def running_count(name: str) -> int:
    """Procesos vivos de un agente (por comm; opencode y claude incluidos)."""
    n = 0
    for d in Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                n += (d / "comm").read_text().strip() == name
            except OSError:
                pass
    return n


def short_ago(delta: float) -> str:
    d = int(delta)
    return f"{d}s ago" if d < 60 else f"{d // 60}m ago" if d < 3600 else f"{d // 3600}h ago"


def pct_color(pct: float) -> str:
    return THEME["status_error"] if pct >= 80 else THEME["status_warn"] if pct >= 50 else THEME["status_ok"]


def meter(label: str, pct: float | None, detail: str) -> Text:
    """etiqueta  ██████░░░░  42%  detalle (estilo btop)."""
    if len(label) > LABEL_W:
        label = label[:LABEL_W - 1] + "…"
    t = Text(f"{label:<{LABEL_W}} ")
    if pct is None:
        t.append("·" * BAR_W, style=THEME["border"])
        t.append("   no data", style=THEME["muted"])
        if detail:
            t.append(f"  {detail}", style=THEME["muted"])
        return t
    c = pct_color(pct)
    full = min(BAR_W, int(round(pct)) * BAR_W // 100)
    t.append("█" * full, style=c)
    t.append("░" * (BAR_W - full), style=THEME["border"])
    t.append(f" {pct:3.0f}%", style=f"bold {c}")
    if detail:
        t.append(f"  {detail}", style=THEME["muted"])
    return t


def sessions_rows(rows: list) -> list[Text]:
    out = [meter(*r) for r in rows[:MAX_AGENTS]]
    if len(rows) > MAX_AGENTS:
        out.append(Text(f"+ {len(rows) - MAX_AGENTS} more", style=THEME["muted"]))
    return out


def fmt_reset(epoch, day: bool = False) -> str:
    try:
        return time.strftime("%H:%M %a" if day else "%H:%M", time.localtime(int(float(epoch))))
    except (TypeError, ValueError):
        return ""


def window_label(minutes: int) -> str:
    return "5h" if minutes <= 360 else "7d" if minutes >= 9000 else f"{minutes // 60}h"


def proc_cwds(names: tuple[str, ...]) -> dict[int, str]:
    """pid → cwd de los procesos cuyo comm está en `names`."""
    out = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if (d / "comm").read_text().strip() in names:
                out[int(d.name)] = os.readlink(d / "cwd")
        except OSError:
            continue
    return out


# ── Claude Code ───────────────────────────────────────────

def claude_sessions() -> list[tuple[str, float | None, str]]:
    """Sesiones abiertas de Claude Code: (título, %contexto, detalle), la más
    nueva primero. Una entrada cuenta si su proceso sigue vivo, es la más
    reciente de ese pid (tras un /clear el mismo pid deja otro archivo) y se
    actualizó hace menos de FRESH_SECONDS."""
    now = time.time()
    latest: dict[int, dict] = {}
    for f in CACHE_DIR.glob("*.json") if CACHE_DIR.is_dir() else []:
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        pid, upd = d.get("pid"), d.get("updated_epoch")
        if pid is None or upd is None:
            continue
        if pid not in latest or upd > latest[pid]["updated_epoch"]:
            latest[pid] = d
    out = []
    for pid, d in latest.items():
        if not Path(f"/proc/{pid}").exists() or now - d["updated_epoch"] > FRESH_SECONDS:
            continue
        pct = d.get("context_pct")
        out.append((d["updated_epoch"], d.get("title") or d.get("session_dir") or "?",
                    None if pct in (None, -1) else float(pct),
                    f"{d.get('session_dir', '?')} · {short_ago(now - d['updated_epoch'])}"))
    return [x[1:] for x in sorted(out, reverse=True)]


def claude_usage() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def claude_limits() -> list[Text]:
    u = claude_usage()
    rows = []
    for key, label, reset, day in (("five_hour_pct", "5h", "five_hour_reset", False),
                                   ("seven_day_pct", "7d", "seven_day_reset", True)):
        v = u.get(key)
        rows.append(meter(label, None if v in (None, "") else float(v),
                          f"resets {fmt_reset(u[reset], day=day)}" if u.get(reset) else ""))
    return rows


# ── opencode ──────────────────────────────────────────────

def opencode_sessions() -> list[tuple[str, float | None, str]]:
    if not os.access(OPENCODE_SCRIPT, os.X_OK):
        return []
    try:
        out = subprocess.run([str(OPENCODE_SCRIPT)], capture_output=True, text=True, timeout=5).stdout
        data = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [(d.get("label", "?"), None if d.get("pct") in (None, -1) else float(d["pct"]), d.get("detail", ""))
            for d in data]


# ── Codex ─────────────────────────────────────────────────

def codex_rollouts(days: int = 7) -> list[Path]:
    """Rollouts de los últimos `days` días, el más nuevo primero."""
    base = CODEX_HOME / "sessions"
    files: list[Path] = []
    for i in range(days):
        d = time.localtime(time.time() - i * 86400)
        day = base / f"{d.tm_year:04d}" / f"{d.tm_mon:02d}" / f"{d.tm_mday:02d}"
        if day.is_dir():
            files += day.glob("rollout-*.jsonl")
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def codex_scan(path: Path) -> dict:
    """De un rollout: cwd (session_meta), modelo (turn_context) y el último
    token_count (uso por turno + rate_limits)."""
    out: dict = {"cwd": "", "model": "", "info": None, "limits": None, "mtime": path.stat().st_mtime}
    try:
        with path.open(errors="replace") as fh:
            for line in fh:
                if '"session_meta"' not in line and '"token_count"' not in line and '"turn_context"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                p = e.get("payload") or {}
                if e.get("type") == "session_meta":
                    out["cwd"] = p.get("cwd", out["cwd"])
                elif e.get("type") == "turn_context":
                    out["model"] = p.get("model", out["model"])
                elif p.get("type") == "token_count":
                    if p.get("info"):
                        out["info"] = p["info"]
                    if p.get("rate_limits"):
                        out["limits"] = p["rate_limits"]
    except OSError:
        pass
    return out


def codex_context(info: Optional[dict]) -> Optional[float]:
    if not info:
        return None
    last = info.get("last_token_usage") or info.get("lastTokenUsage") or {}
    window = info.get("model_context_window") or info.get("modelContextWindow")
    total = last.get("total_tokens") or last.get("totalTokens")
    if not window or not total or window <= CODEX_BASELINE:
        return None
    return max(0.0, min(100.0, (total - CODEX_BASELINE) / (window - CODEX_BASELINE) * 100))


def codex_limits(scans: list[dict]) -> list[Text]:
    """5h/7d del rate_limits más reciente (de cualquier sesión)."""
    limits = next((s["limits"] for s in scans if s["limits"]), None)
    if not limits:
        return [meter("5h", None, ""), meter("7d", None, "")]
    windows = {}
    for key in ("primary", "secondary"):
        w = limits.get(key)
        if not w:
            continue
        mins = int(w.get("window_minutes") or w.get("windowDurationMins") or 0)
        reset = w.get("resets_at") or w.get("resetsAt")
        if not reset and w.get("resets_in_seconds") is not None:
            reset = time.time() + float(w["resets_in_seconds"])
        windows[window_label(mins)] = (float(w.get("used_percent") or w.get("usedPercent") or 0), reset)
    rows = []
    for label in ("5h", "7d"):
        pct, reset = windows.get(label, (None, None))
        rows.append(meter(label, pct, f"resets {fmt_reset(reset, day=label == '7d')}" if reset else ""))
    return rows


def codex_sessions(scans: list[dict]) -> list[tuple[str, float | None, str]]:
    """Una fila por proceso `codex` abierto: el rollout más nuevo de su cwd."""
    now = time.time()
    out = []
    for _pid, cwd in proc_cwds(("codex",)).items():
        s = next((s for s in scans if s["cwd"] == cwd), None)
        name = Path(cwd).name or cwd
        if not s:
            out.append((name, None, "no session yet"))
            continue
        detail = name + (f" · {s['model']}" if s["model"] else "") + f" · {short_ago(now - s['mtime'])}"
        out.append((name, codex_context(s["info"]), detail))
    return out


# ── Antigravity ───────────────────────────────────────────

def agy_entries() -> list[dict]:
    """Entradas que escribe agents/agy-statusline.sh (una por conversación)."""
    out = []
    for f in AGY_CACHE.glob("*.json") if AGY_CACHE.is_dir() else []:
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda d: d.get("updated_epoch", 0), reverse=True)


def agy_limits(entries: list[dict]) -> list[Text]:
    """Cuota por modelo (la más reciente): % usado = 1 - remaining_fraction."""
    quota = next((e["payload"].get("quota") for e in entries if (e.get("payload") or {}).get("quota")), None)
    if not quota:
        return [meter("quota", None, "")]
    rows = []
    for model, q in sorted(quota.items()):
        rem, secs = q.get("remaining_fraction"), q.get("reset_in_seconds")
        rows.append(meter(model, None if rem is None else (1 - float(rem)) * 100,
                          f"resets {fmt_reset(time.time() + float(secs), day=float(secs) > 86400)}"
                          if secs is not None else ""))
    return rows


def agy_sessions(entries: list[dict]) -> list[tuple[str, float | None, str]]:
    now = time.time()
    out = []
    for e in entries:
        pid, p = e.get("pid"), e.get("payload") or {}
        if not pid or not Path(f"/proc/{pid}").exists() or now - e.get("updated_epoch", 0) > FRESH_SECONDS:
            continue
        pct = (p.get("context_window") or {}).get("used_percentage")
        cwd = (p.get("workspace") or {}).get("current_dir") or p.get("cwd", "")
        model = (p.get("model") or {}).get("display_name", "")
        detail = " · ".join(x for x in (Path(cwd).name, model, short_ago(now - e.get("updated_epoch", now))) if x)
        out.append((Path(cwd).name or "agy", None if pct is None else float(pct), detail))
    return out


# ── Popup de carpetas de skills ───────────────────────────

class FoldersModal(ModalScreen[None]):
    """Carpetas de origen de skills y agentes (skills.conf): a agregar, d sacar, K/J prioridad."""

    DEFAULT_CSS = css("""
    FoldersModal .modal { width: 90%%; }
    FoldersModal DataTable { height: auto; max-height: 12; }
    FoldersModal #detected { margin-top: 1; max-height: 10; }
    FoldersModal .sub { color: %(muted)s; margin-top: 1; }
    """)
    BINDINGS = [
        Binding("escape", "close", "close"),
        Binding("a", "add", "add folder"),
        Binding("d", "remove", "remove folder"),
        Binding("K", "move(-1)", "priority up"),
        Binding("J", "move(1)", "priority down"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal") as box:
            box.border_title = " Skills & agents folders "
            box.border_subtitle = " the first folder wins on repeated names "
            yield Table(id="folders", show_header=False)
            yield Label("Detected in your active providers (read-only: managed by each provider)", classes="sub")
            yield Table(id="detected", show_header=False)
            yield KeyHints([("a", "add"), ("d", "remove"), ("K/J", "priority"), ("esc", "close")])

    def on_mount(self) -> None:
        self.query_one(".modal").styles.width = "90%"   # el .modal global (CSS de la app) pisa el DEFAULT_CSS
        t = self.query_one("#folders", Table)
        t.add_column("", key="n", width=3)
        t.add_column("", key="path", width=58)
        t.add_column("", key="info", width=30)
        d = self.query_one("#detected", Table)
        d.can_focus = False
        d.cursor_type = "none"
        d.add_column("", key="what", width=30)
        d.add_column("", key="path", width=44)
        d.add_column("", key="info", width=24)
        home = str(Path.home())
        rows = []
        for prov, path, kind, n_s, n_a, st in ps.sources(enabled_providers()):
            kind = f"{prov} · {kind}"
            bits = ([f"{n_s} skills"] if n_s else []) + ([f"{n_a} agents"] if n_a else [])
            info = Text(" · ".join(bits) + ("" if st == "on" else " · disabled"),
                        style=THEME["muted"] if st == "off" else THEME["status_ok"])
            # los buckets de sync llevan UUIDs: se acortan para que la ruta se entienda
            short = "/".join(c if len(c) <= 30 else c[:8] + "…" for c in str(path).replace(home, "~", 1).split("/"))
            short = short if len(short) <= 44 else "…" + short[-43:]
            rows.append((str(path), [Text(kind, style=THEME["muted"]), Text(short), info]))
        d.set_rows(rows)
        self.reload()
        t.focus()

    def reload(self, select: str = "") -> None:
        dirs, _ = sk.read_conf()
        found = sk.scan(dirs)
        agents = sk.scan_agents(dirs)
        rows = []
        for i, d in enumerate(dirs, 1):
            if (err := sk.validate_dir(d)):
                info = Text(f"✗ {err}", style=THEME["status_error"])
            else:
                n_s = sum(1 for s in found if s.root == d)
                n_a = sum(1 for a in agents if a.root == d)
                info = Text(f"● {n_s} skills · {n_a} agents", style=THEME["status_ok"])
            rows.append((d, [Text(str(i), style=THEME["muted"]), Text(d.replace(str(Path.home()), "~", 1)), info]))
        t = self.query_one("#folders", Table)
        t.set_rows(rows)
        self.query_one(".modal").border_subtitle = (" the first folder wins on repeated names " if dirs else
                                                    " no folders yet: press a to add one with a SKILLS/ subfolder ")
        if select in dirs:
            t.move_cursor(row=dirs.index(select))

    def changed(self) -> None:
        self.app.folders_changed = True

    def action_close(self) -> None:
        self.dismiss(None)

    def action_add(self) -> None:
        def validate(v: dict) -> Optional[str]:
            p = v.get("path", "").strip()
            if not p:
                return "enter a folder"
            if sk._expand(p) in sk.read_conf()[0]:
                return "already in the list"
            return sk.validate_dir(p)

        def done(vals) -> None:
            if not vals:
                return
            dirs, off = sk.read_conf()
            new = sk._expand(vals["path"])
            sk.write_conf(dirs + [new], off)
            self.changed()
            self.reload(new)
        self.app.push_screen(FormModal("Add folder", [Field("path", "Folder", paths=True,
                                                            placeholder="/path/with/SKILLS/")],
                                       hint="needs a SKILLS/ subfolder · enter add · esc cancel",
                                       validate=validate), done)

    def action_remove(self) -> None:
        t = self.query_one("#folders", Table)
        if (d := t.selected_key()) is None:
            return

        def done(yes: bool) -> None:
            if yes:
                dirs, off = sk.read_conf()
                sk.write_conf([x for x in dirs if x != d], off)
                self.changed()
                self.reload()
        self.app.push_screen(ConfirmModal("Remove folder", f"Stop loading skills and agents from {d}?\n"
                                          "The folder itself is not deleted."), done)

    def action_move(self, delta: int) -> None:
        t = self.query_one("#folders", Table)
        if (d := t.selected_key()) is None:
            return
        dirs, off = sk.read_conf()
        i, j = dirs.index(d), dirs.index(d) + delta
        if not 0 <= j < len(dirs):
            return
        dirs[i], dirs[j] = dirs[j], dirs[i]
        sk.write_conf(dirs, off)
        self.changed()
        self.reload(d)


# ── Vista ─────────────────────────────────────────────────

class AgentsView(DView):
    """Un panel por proveedor activo. manage=True (Settings) suma el panel
    Providers para prender/apagar cada uno en agents/providers.conf."""

    FOCUS = "#body"
    DEFAULT_CSS = css("""
    #body { height: 1fr; scrollbar-size-vertical: 1; }
    AgentsView .panel { height: auto; }
    AgentsView .panel Static { height: auto; }
    #providers { height: auto; }
    #ag-tabs { height: 1; padding: 0 1; }
    #ag-pages { height: 1fr; }
    #skills-panel, #agents-panel, #mcp-panel, #lsp-panel { height: 1fr; }
    #skill-list, #agent-list, #mcp-list, #lsp-list { height: 1fr; }
    #updated { color: %(muted)s; height: 1; padding: 0 2; }
    """)

    BINDINGS = [
        Binding("tab", "next_page(1)", show=False, description="next page"),
        Binding("shift+tab", "next_page(-1)", show=False, description="previous page"),
        Binding("1", "page('body')", show=False, description="usage page"),
        Binding("2", "page('skills-page')", show=False, description="skills page"),
        Binding("3", "page('agents-page')", show=False, description="agents page"),
        Binding("4", "page('mcp-page')", show=False, description="MCPs page"),
        Binding("5", "page('lsp-page')", show=False, description="LSPs page"),
        Binding("c", "run('claude')", "claude code"),
        Binding("o", "run('opencode')", "opencode"),
        Binding("r", "refresh_manual", "refresh"),
        Binding("f", "folders", "skills folders", show=False),
        Binding("A", "items_all(True)", "enable all", show=False),
        Binding("N", "items_all(False)", "disable all", show=False),
        Binding("a", "add_mcp", "add MCP", show=False),
        Binding("d", "remove_mcp", "remove MCP", show=False),
        Binding("h", "health", "check MCP health", show=False),
    ]

    def __init__(self, manage: bool = False, **kw) -> None:
        super().__init__(**kw)
        self.manage = manage
        self.prov_items: dict = {}
        self.tools: dict = {}            # clave → at.Tool (MCPs y LSPs)
        self.busy: set[str] = set()      # claves con un cambio lento en curso
        self.checking = False
        self.page = "body"
        if manage:
            self.FOCUS = "#providers"

    def compose(self) -> ComposeResult:
        if not self.manage:
            with VerticalScroll(id="body"):
                yield from self.usage_panels()
            return
        yield Static(id="ag-tabs")
        with ContentSwitcher(initial="body", id="ag-pages"):
            with VerticalScroll(id="body"):
                yield Panel(Table(id="providers", show_header=False), title="  Providers",
                            id="providers-panel")
                yield from self.usage_panels()
            with Vertical(id="skills-page"):
                yield Panel(Table(id="skill-list", show_header=False), title="󱁤  Skills", id="skills-panel")
            with Vertical(id="agents-page"):
                yield Panel(Table(id="agent-list", show_header=False), title="󰭻  Agents", id="agents-panel")
            with Vertical(id="mcp-page"):
                yield Panel(Table(id="mcp-list", show_header=False), title="\U000f048d  MCP servers", id="mcp-panel")
            with Vertical(id="lsp-page"):
                yield Panel(Table(id="lsp-list", show_header=False), title="\U000f0169  Language servers",
                            id="lsp-panel")

    def usage_panels(self) -> ComposeResult:
        for pid, name, icon, _bin in PROVIDERS:
            yield Panel(Static(id=f"{pid}-text"), title=f"{icon}  {name}", id=f"{pid}-panel")
        yield Static(id="updated")

    def hints(self) -> list[tuple[str, str]]:
        h: list[tuple[str, str]] = []
        if self.manage:
            if self.page in ("skills-page", "agents-page"):
                h = [("enter", "on/off"), ("A", "all on"), ("N", "all off"), ("f", "folders")]
            elif self.page == "mcp-page":
                h = [("enter", "on/off"), ("a", "add"), ("d", "remove"), ("h", "health"), ("A/N", "all on/off")]
            elif self.page == "lsp-page":
                h = [("enter", "on/off · install"), ("A/N", "all on/off")]
            else:
                h = [("enter", "show/hide provider")]
            h = h + [("tab", "page"), ("1-5", "jump")]
        return h + [("c", "claude code"), ("o", "opencode"), ("r", "refresh"), ("q", "quit")]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in ("next_page", "page") and not self.manage:
            return False
        return True

    def on_mount(self) -> None:
        if self.manage:
            t = self.query_one("#providers", Table)
            t.add_column("", key="name", width=26)
            t.add_column("", key="state", width=12)
            t.add_column("", key="inst", width=56)
            k = self.query_one("#skill-list", Table)
            k.add_column("", key="state", width=11)
            k.add_column("", key="name", width=34)
            k.add_column("", key="desc", width=48)
            k.add_column("", key="root", width=34)
            g = self.query_one("#agent-list", Table)
            g.add_column("", key="state", width=11)
            g.add_column("", key="name", width=34)
            g.add_column("", key="desc", width=48)
            g.add_column("", key="root", width=34)
            for tid in ("mcp-list", "lsp-list"):
                m = self.query_one(f"#{tid}", Table)
                m.add_column("", key="state", width=13)
                m.add_column("", key="name", width=26)
                m.add_column("", key="desc", width=46 if tid == "mcp-list" else 40)
                m.add_column("", key="origin", width=24)
                m.add_column("", key="info", width=60 if tid == "mcp-list" else 48)
            self.render_tabs()
            self.refresh_skills()
            self.load_builtin()
        self.action_refresh_all()
        self.set_interval(5, self.tick)

    # ── páginas (solo manage=True) ──

    def render_tabs(self) -> None:
        t = Text()
        for i, (pid, label, _tid) in enumerate(PAGES, 1):
            on = pid == self.page
            t.append(f" {i} {label} ", style=f"bold reverse {THEME['primary']}" if on else THEME["muted"])
            t.append("  ")
        self.query_one("#ag-tabs", Static).update(t)

    def action_page(self, name: str) -> None:
        self.page = name
        self.query_one("#ag-pages", ContentSwitcher).current = name
        self.render_tabs()
        if name in ("mcp-page", "lsp-page"):
            self.refresh_tools()
        elif name in ("skills-page", "agents-page"):
            self.refresh_skills()
        tid = next(t for p, _l, t in PAGES if p == name)
        tbl = self.query_one(f"#{tid}", Table)
        tbl.focus()
        if tid in ("mcp-list", "lsp-list") and tbl.row_count and tbl.cursor_row == 0:
            tbl.first_selectable()
        self.update_hints()

    def action_next_page(self, step: int) -> None:
        ids = [p for p, _l, _t in PAGES]
        self.action_page(ids[(ids.index(self.page) + step) % len(ids)])

    def action_refresh_manual(self) -> None:
        if self.manage:
            self.refresh_skills()
            self.refresh_tools()
        self.action_refresh_all()

    def tick(self) -> None:
        if self.visible_now and self.page == "body":
            self.action_refresh_all()

    def action_refresh_all(self) -> None:
        on = enabled_providers()
        muted = THEME["muted"]
        if self.manage:
            t = self.query_one("#providers", Table)
            row = t.cursor_row or 0
            t.clear()
            for pid, name, icon, binary in PROVIDERS:
                state = Text("● shown", style=f"bold {THEME['status_ok']}") if pid in on else \
                    Text("○ hidden", style=muted)
                path, procs = find_bin(binary), running_count(binary)
                if procs:
                    inst = Text(f"● {procs} running", style=THEME["status_ok"])
                    inst.append(f"  {path or binary}".replace(str(Path.home()), "~"), style=muted)
                elif path:
                    inst = Text(f"installed  {path}".replace(str(Path.home()), "~"), style=muted)
                else:
                    inst = Text(f"not installed ({binary})", style=THEME["status_warn"])
                t.add_row(f"{icon}  {name}", state, inst, key=pid)
            t.move_cursor(row=min(row, t.row_count - 1))
            self.query_one("#providers-panel").border_subtitle = " also applies to the waybar popup and module "

        codex_scans = [codex_scan(p) for p in codex_rollouts()] if "codex" in on else []
        agy = agy_entries() if "antigravity" in on else []
        sessions_title = Text("sessions", style=f"bold {muted}")
        none_open = Text("no open sessions", style=muted)
        for pid, name, _icon, binary in PROVIDERS:
            panel = self.query_one(f"#{pid}-panel")
            panel.display = pid in on
            if pid not in on:
                continue
            if pid == "claude":
                rows = claude_sessions()
                body = claude_limits() + [Text(""), sessions_title] + (sessions_rows(rows) or [none_open])
            elif pid == "opencode":
                rows = opencode_sessions()
                body = sessions_rows(rows) or [none_open]
            elif pid == "codex":
                rows = codex_sessions(codex_scans)
                body = codex_limits(codex_scans) + [Text(""), sessions_title] + (sessions_rows(rows) or [none_open])
            else:
                rows = agy_sessions(agy)
                body = agy_limits(agy) + [Text(""), sessions_title] + (sessions_rows(rows) or [none_open])
                if not agy:
                    body.append(Text("no data yet — set agents/agy-statusline.sh as agy's statusLine "
                                     "(docs/configuration/wayland.md)", style=THEME["status_warn"]))
            sub = f" {len(rows)} open " if rows else ""
            if not find_bin(binary) and not running_count(binary):
                body, sub = [Text(f"{name} is not installed ({binary} not found)", style=THEME["status_warn"])], ""
            self.query_one(f"#{pid}-text", Static).update(Text("\n").join(body))
            panel.border_subtitle = sub
        u = claude_usage()
        self.query_one("#updated", Static).update(
            f"claude updated {u['updated_at']}" if "claude" in on and u.get("updated_at") else "")
        self.update_hints()

    # ── Skills y Agents (solo con manage=True) ──────────────

    def refresh_skills(self) -> None:
        """Relee skills.conf, las carpetas y lo externo, y redibuja Skills y Agents (sin parpadeo)."""
        dirs, off = sk.read_conf()
        agent_off = sk.read_agent_off()
        muted, ok, warn = THEME["muted"], THEME["status_ok"], THEME["status_warn"]
        found = sk.scan(dirs)

        def short(t: str, n: int) -> str:
            return t[:n] + ("…" if len(t) > n else "")

        def row_state(on: bool, shadowed: bool = False) -> Text:
            if shadowed:
                return Text("– shadowed", style=muted)
            return Text("● on", style=f"bold {ok}") if on else Text("○ off", style=muted)

        # skills y agentes propios de los proveedores activos (los que trae o preconfigura cada uno)
        items = ps.discover(enabled_providers())
        self.prov_items = {i.key: i for i in items}
        # una skill que está en tu carpeta y también en el sync de claude.ai se lista una sola vez (la tuya)
        own = {s.name for s in found}
        synced_dup = {i.name for i in items if i.origin == "claude.ai sync" and i.name in own}

        def prov_row(i) -> tuple[str, list]:
            st = row_state(i.on) if i.toggle else Text("● fixed", style=muted)
            return (i.key, [st, Text(i.name, style="" if (i.toggle and i.on) else muted),
                            Text(short(i.desc, 46), style=muted), Text(f"{i.provider} · {i.origin}", style=muted)])

        rows = []
        for s in found:
            on = not s.shadowed_by and s.name not in off
            desc = Text(short(s.desc, 46)) if s.desc else Text("no frontmatter in SKILL.md", style=warn)
            src = Path(s.root).name + (" +claude.ai" if s.name in synced_dup else "")
            rows.append((f"{s.root}|{s.name}", [row_state(on, bool(s.shadowed_by)),
                                               Text(s.name, style="" if on else muted), desc,
                                               Text(src, style=muted)]))
        prov_skills = [i for i in items if i.kind == "skill" and i.name not in synced_dup]
        rows += [prov_row(i) for i in prov_skills]
        self.query_one("#skill-list", Table).set_rows(rows)
        n_on = sum(1 for s in found if not s.shadowed_by and s.name not in off)
        self.query_one("#skills-panel").border_subtitle = \
            f" {n_on} of {len(found)} loaded · {len(prov_skills)} from providers · f folders "

        agents = sk.scan_agents(dirs)
        rows = []
        for a in agents:
            on = a.name not in agent_off
            rows.append((a.name, [row_state(on), Text(a.name, style="" if on else muted),
                                  Text(short(a.desc, 46)), Text(Path(a.root).name + "  " + a.formats, style=muted)]))
        prov_agents = [i for i in items if i.kind == "agent"]
        rows += [prov_row(i) for i in prov_agents]
        self.query_one("#agent-list", Table).set_rows(rows)
        n_on = sum(1 for a in agents if a.name not in agent_off)
        self.query_one("#agents-panel").border_subtitle = \
            f" {n_on} of {len(agents)} loaded · {len(prov_agents)} from providers · f folders "

    @work(thread=True, exclusive=True, group="agents-builtin")
    def load_builtin(self) -> None:
        """Skills integradas de opencode: `opencode debug skill` tarda unos segundos, va en un hilo."""
        if "opencode" in enabled_providers() and not ps.BUILTIN_CACHE.exists():
            ps.opencode_builtin(refresh=True)
            self.app.call_from_thread(self.refresh_skills)

    def skills_apply(self, msg: str) -> None:
        """Escribe los symlinks/config según skills.conf y refresca."""
        try:
            sk.apply()
        except OSError as e:
            self.app.notify_err(f"Could not apply: {e}")
        else:
            self.app.notify_ok(msg)
        self.refresh_skills()

    def action_folders(self) -> None:
        if getattr(self.app.focused, "id", "") not in ("skill-list", "agent-list"):
            return
        self.app.folders_changed = False
        self.app.push_screen(FoldersModal(), lambda _r: self.skills_apply("Folders updated")
                             if getattr(self.app, "folders_changed", False) else self.refresh_skills())

    def action_items_all(self, on: bool) -> None:
        fid = getattr(self.app.focused, "id", "")
        if fid in ("mcp-list", "lsp-list"):
            return self.tools_all(fid, on)
        dirs, off = sk.read_conf()
        if fid == "skill-list":
            sk.write_conf(dirs, set() if on else {s.name for s in sk.scan(dirs)})
            self.skills_apply("All skills enabled" if on else "All skills disabled")
        elif fid == "agent-list":
            sk.write_conf(dirs, off, set() if on else {a.name for a in sk.scan_agents(dirs)})
            self.skills_apply("All agents enabled" if on else "All agents disabled")

    def toggle_item(self, table: str, key: str) -> None:
        if key.count("|") >= 2 and key.split("|", 1)[0] in ps.PROVIDER_IDS:
            item = self.prov_items.get(key)
            if item is None:
                return
            if (err := ps.set_enabled(item, not item.on)):
                return self.app.notify_err(err)
            self.app.notify_ok(f"{item.name} {'disabled' if item.on else 'enabled'} in {item.provider}")
            return self.refresh_skills()
        dirs, off = sk.read_conf()
        if table == "skill-list":
            root, _, name = key.partition("|")
            owner = next((s for s in sk.scan(dirs) if s.name == name and not s.shadowed_by), None)
            if owner is None or owner.root != root:
                return self.app.notify_err(f"{name} is shadowed by {owner.root if owner else 'another folder'}")
            on = name in off
            (off.discard if on else off.add)(name)
            sk.write_conf(dirs, off)
        else:
            name = key
            agent_off = sk.read_agent_off()
            on = name in agent_off
            (agent_off.discard if on else agent_off.add)(name)
            sk.write_conf(dirs, off, agent_off)
        self.skills_apply(f"{name} {'enabled' if on else 'disabled'}")

    # ── MCPs y LSPs (solo con manage=True; backend en agent_tools.py) ──

    def refresh_tools(self) -> None:
        """Relee MCPs y LSPs de los proveedores activos y redibuja las dos tablas (sin parpadeo)."""
        on_prov = enabled_providers()
        muted, ok, warn, err = THEME["muted"], THEME["status_ok"], THEME["status_warn"], THEME["status_error"]
        level = {"ok": ok, "warn": warn, "error": err}

        def short(t: str, n: int) -> str:
            return t[:n - 1] + "…" if len(t) > n else t

        def state(t: at.Tool) -> Text:
            if t.key in self.busy:
                return Text("… working", style=warn)
            if not t.toggle:
                return Text("● fixed" if t.on else "○ off (fixed)", style=muted)
            if t.toggle == "claude-lsp-install":
                return Text("○ available", style=muted)
            return Text("● on", style=f"bold {ok}") if t.on else Text("○ off", style=muted)

        for kind, tid, panel, lister in (("mcp", "mcp-list", "#mcp-panel", at.mcp_list),
                                         ("lsp", "lsp-list", "#lsp-panel", at.lsp_list)):
            try:
                items = lister(on_prov)
            except Exception as e:  # noqa: BLE001 — una config rota no tiene que tirar Settings
                items = []
                self.app.notify_err(f"Could not read {kind.upper()}s: {e}")
            for t in items:
                self.tools[t.key] = t
            rows = []
            for pid, name, icon in TOOL_PROVIDERS:
                mine = [t for t in items if t.provider == pid]
                if pid not in on_prov:
                    continue
                n_on = sum(1 for t in mine if t.on)
                rows.append((f"hdr:{kind}:{pid}", [Text(icon, style=f"bold {THEME['primary']}"),
                                                   Text(name, style=f"bold {THEME['primary']}"),
                                                   Text(f"{n_on} of {len(mine)} on", style=muted),
                                                   Text(""), Text("")]))
                if not mine:
                    rows.append((f"gap:{kind}:{pid}", [Text(""), Text("nothing configured", style=muted),
                                                       Text(""), Text(""), Text("")]))
                for t in mine:
                    if t.warn:
                        info = Text(f"⚠ {t.warn}", style=warn)
                    elif kind == "mcp":
                        lbl, lv = at.health_label(t.extra.get("health", ""))
                        info = Text(lbl, style=level.get(lv, muted))
                    else:
                        info = Text(short(t.extra.get("command", ""), 46), style=muted)
                    rows.append((t.key, [state(t), Text(short(t.name, 26), style="" if t.on else muted),
                                         Text(short(t.desc, 46 if kind == "mcp" else 40), style=muted),
                                         Text(short(t.origin, 24), style=muted), info]))
                rows.append((f"gap:{kind}:{pid}:end", [Text("")] * 5))
            self.query_one(f"#{tid}", Table).set_rows(rows)
            n_on, n = sum(1 for t in items if t.on), len(items)
            if kind == "mcp":
                hc = at.health().get("at")
                sub = f" {n_on} of {n} on · " + ("checking health… " if self.checking else
                                                  (f"health {short_ago(time.time() - hc)} · h recheck " if hc
                                                   else "h checks health "))
            else:
                sub = f" {n_on} of {n} on · opencode starts them when it opens a matching file "
            self.query_one(panel).border_subtitle = sub

    def selected_tool(self, tid: str) -> Optional[at.Tool]:
        if getattr(self.app.focused, "id", "") != tid:
            return None
        k = self.query_one(f"#{tid}", Table).selected_key()
        return self.tools.get(k) if k else None

    def toggle_tool(self, key: str) -> None:
        t = self.tools.get(key)
        if t is None or key in self.busy:
            return
        if not t.toggle:
            return self.app.notify_err(f"{t.name}: {t.why or 'read-only'}")
        if t.toggle == "claude-lsp-install":
            def go(yes: bool) -> None:
                if yes:
                    self.tool_change(t, True)
            return self.app.push_screen(ConfirmModal(
                "Install LSP plugin",
                f"Install {t.ref} for Claude Code (claude plugin install, user scope)?"
                + (f"\n\n{t.extra.get('about')}" if t.extra.get("about") else "")
                + (f"\n\nIt {t.warn}: install it with pacman/yay or Claude Code will not start it."
                   if t.warn else "")), go)
        self.tool_change(t, not t.on)

    def tool_change(self, t: at.Tool, on: bool) -> None:
        if t.slow:
            self.busy.add(t.key)
            self.refresh_tools()
            return self.tool_change_bg(t, on)
        if (e := at.set_enabled(t, on)):
            return self.app.notify_err(e)
        self.app.notify_ok(f"{t.name} {'enabled' if on else 'disabled'} in {t.provider}"
                           + (" · restart open sessions to apply" if t.kind == "mcp" else ""))
        self.refresh_tools()

    @work(thread=True, group="agents-tools")
    def tool_change_bg(self, t: at.Tool, on: bool) -> None:
        e = at.set_enabled(t, on)

        def done() -> None:
            self.busy.discard(t.key)
            if e:
                self.app.notify_err(e)
            elif t.toggle == "claude-lsp-install":
                self.app.notify_ok(f"{t.ref} installed")
            else:
                self.app.notify_ok(f"{t.name} {'enabled' if on else 'disabled'} in {t.provider}")
            self.refresh_tools()
        self.app.call_from_thread(done)

    def tools_all(self, tid: str, on: bool) -> None:
        # nunca instala (eso es de a uno, con confirmación): solo prende/apaga lo que ya está
        todo = [t for t in self.tools.values() if t.kind == tid[:3] and t.toggle
                and t.toggle != "claude-lsp-install" and t.on != on
                and (t.provider in enabled_providers())]
        if not todo:
            return self.app.notify_ok("Nothing to change")
        fast = [t for t in todo if not t.slow]
        errs = [e for t in fast if (e := at.set_enabled(t, on))]
        slow = [t for t in todo if t.slow]
        for t in slow:
            self.busy.add(t.key)
        if slow:
            self.tools_all_bg(slow, on)
        if errs:
            self.app.notify_err(errs[0])
        else:
            self.app.notify_ok(f"{len(todo)} {'enabled' if on else 'disabled'}")
        self.refresh_tools()

    @work(thread=True, group="agents-tools")
    def tools_all_bg(self, items: list, on: bool) -> None:
        errs = [e for t in items if (e := at.set_enabled(t, on))]

        def done() -> None:
            for t in items:
                self.busy.discard(t.key)
            if errs:
                self.app.notify_err(errs[0])
            self.refresh_tools()
        self.app.call_from_thread(done)

    def action_add_mcp(self) -> None:
        if self.page != "mcp-page":
            return
        where = [("Claude Code and opencode", "both"), ("Claude Code", "claude"), ("opencode", "opencode")]

        def validate(v: dict) -> Optional[str]:
            return at.validate_new(v.get("name", "").strip(), v.get("target", ""), v.get("where") or "both",
                                   v.get("header", ""))

        def done(v) -> None:
            if v:
                self.add_mcp_bg(v["name"].strip(), v["target"], v.get("where") or "both", v.get("header", ""))
        self.app.push_screen(FormModal("Add MCP server", [
            Field("name", "Name", placeholder="microsoft-learn"),
            Field("target", "URL or command", placeholder="https://… (remote) or npx -y @scope/server (local)"),
            Field("where", "Add to", value="both", choices=where),
            Field("header", "Header (optional)", placeholder="Authorization: Bearer {env:MY_TOKEN}")],
            hint=f"user scope in Claude Code · {at._oc_mcp_file().name} · ctrl+s save · esc cancel", validate=validate), done)

    @work(thread=True, group="agents-tools")
    def add_mcp_bg(self, name: str, target: str, where: str, header: str) -> None:
        e = at.add_mcp(name, target, where, header)
        self.app.call_from_thread(lambda: (self.app.notify_err(e) if e else
                                           self.app.notify_ok(f"{name} added · h checks its health"),
                                           self.refresh_tools()))

    def action_remove_mcp(self) -> None:
        if self.page != "mcp-page" or (t := self.selected_tool("mcp-list")) is None:
            return
        if not t.removable:
            return self.app.notify_err(f"{t.name}: {t.why or 'cannot be removed from here'}")

        def go(yes: bool) -> None:
            if yes:
                self.busy.add(t.key)
                self.refresh_tools()
                self.remove_mcp_bg(t)
        where = "~/.claude.json (user scope)" if t.provider == "claude" else t.origin
        self.app.push_screen(ConfirmModal("Remove MCP server", f"Remove {t.name} from {where}?\n"
                                          "To keep its config, turn it off instead."), go)

    @work(thread=True, group="agents-tools")
    def remove_mcp_bg(self, t: at.Tool) -> None:
        e = at.remove_mcp(t)

        def done() -> None:
            self.busy.discard(t.key)
            self.tools.pop(t.key, None)
            self.app.notify_err(e) if e else self.app.notify_ok(f"{t.name} removed")
            self.refresh_tools()
        self.app.call_from_thread(done)

    def action_health(self) -> None:
        if self.page != "mcp-page" or self.checking:
            return
        self.checking = True
        self.refresh_tools()
        self.health_bg()

    @work(thread=True, exclusive=True, group="agents-health")
    def health_bg(self) -> None:
        at.check_health()

        def done() -> None:
            self.checking = False
            self.app.notify_ok("MCP health updated")
            self.refresh_tools()
        self.app.call_from_thread(done)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id in ("mcp-list", "lsp-list"):
            return self.toggle_tool(str(event.row_key.value))
        if event.data_table.id in ("skill-list", "agent-list"):
            return self.toggle_item(event.data_table.id, str(event.row_key.value))
        if event.data_table.id == "providers":
            pid = str(event.row_key.value)
            on = pid not in enabled_providers()
            set_provider(pid, on)
            name = next(n for p, n, *_ in PROVIDERS if p == pid)
            self.app.notify_ok(f"{name} {'shown' if on else 'hidden'}")
            self.action_refresh_all()
            self.refresh_skills()
            self.refresh_tools()
            self.load_builtin()

    def action_run(self, cmd: str) -> None:
        # La TUI se reemplaza por el agente en la misma ventana (exec al salir);
        # con la ruta completa, porque el PATH de Hyprland no la incluye
        path = find_bin(cmd)
        if not path:
            return self.app.notify_err(f"{cmd} is not installed")
        self.app.exit(("exec", path))


def AgentsApp() -> ViewApp:
    return ViewApp(AgentsView, title="AI Agents")


def rows_needed() -> int:
    """Alto de la ventana: un panel por proveedor activo (borde 2 + líneas) + pie."""
    on = enabled_providers()

    def n(rows: list) -> int:
        return max(1, min(len(rows), MAX_AGENTS) + (1 if len(rows) > MAX_AGENTS else 0))

    total = 3
    if "claude" in on:
        total += 2 + 2 + 2 + n(claude_sessions())
    if "opencode" in on:
        total += 2 + n(opencode_sessions())
    if "codex" in on:
        total += 2 + (4 + n(codex_sessions([codex_scan(p) for p in codex_rollouts()])) if find_bin("codex")
                      else 1)
    if "antigravity" in on:
        total += 2 + (5 + n(agy_sessions(agy_entries())) if find_bin("agy") else 1)
    return total


if __name__ == "__main__":
    if "--rows" in sys.argv:
        print(rows_needed())
        sys.exit(0)
    result = AgentsApp().run()
    if isinstance(result, tuple) and result[0] == "exec":
        os.execvp(result[1], [result[1]])
