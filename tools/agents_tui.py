#!/usr/bin/env python3
"""
agents_tui.py — panel de agentes IA (módulo waybar "custom/claude-agents" y
sección AI Agents de Settings).

Un panel por proveedor activo en ~/.config/dotfiles/agents.conf (claude, opencode,
codex, antigravity): límites de uso (ventanas de 5 h / 7 d o cuota por
modelo) y el contexto de cada sesión abierta, con barras que pasan a
amarillo/rojo al 50/80 %. `c` abre claude, `o` opencode. En Settings se
suma el panel Providers para prender/apagar cada uno (manage=True); el
popup de waybar y el módulo de la barra leen la misma config.

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
from dtui import THEME, DView, Panel, Table, ViewApp, css  # noqa: E402

from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import VerticalScroll  # noqa: E402
from textual.widgets import DataTable, Static  # noqa: E402

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
    #updated { color: %(muted)s; height: 1; padding: 0 2; }
    """)

    BINDINGS = [
        Binding("c", "run('claude')", "claude code"),
        Binding("o", "run('opencode')", "opencode"),
        Binding("r", "refresh_all", "refresh"),
    ]

    def __init__(self, manage: bool = False, **kw) -> None:
        super().__init__(**kw)
        self.manage = manage
        if manage:
            self.FOCUS = "#providers"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="body"):
            if self.manage:
                yield Panel(Table(id="providers", show_header=False), title="  Providers",
                            id="providers-panel")
            for pid, name, icon, _bin in PROVIDERS:
                yield Panel(Static(id=f"{pid}-text"), title=f"{icon}  {name}", id=f"{pid}-panel")
            yield Static(id="updated")

    def hints(self) -> list[tuple[str, str]]:
        h = [("enter", "show/hide provider")] if self.manage else []
        return h + [("c", "claude code"), ("o", "opencode"), ("r", "refresh"), ("q", "quit")]

    def on_mount(self) -> None:
        if self.manage:
            t = self.query_one("#providers", Table)
            t.add_column("", key="name", width=26)
            t.add_column("", key="state", width=12)
            t.add_column("", key="inst", width=56)
        self.action_refresh_all()
        self.set_interval(5, self.tick)

    def tick(self) -> None:
        if self.visible_now:
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "providers":
            pid = str(event.row_key.value)
            on = pid not in enabled_providers()
            set_provider(pid, on)
            name = next(n for p, n, *_ in PROVIDERS if p == pid)
            self.app.notify_ok(f"{name} {'shown' if on else 'hidden'}")
            self.action_refresh_all()

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
