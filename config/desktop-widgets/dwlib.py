"""dwlib.py — lógica pura de los widgets de escritorio (sin GTK).

La usan desktop-widgets.py (el daemon) y Settings → Desktop widgets
(tools/settings/sections/deskwidgets.py). La config del usuario vive fuera del
repo, en ~/.config/dotfiles/desktop-widgets.conf (sin ese archivo rigen los
defaults); el todo y los caches, en ~/.local/state/dotfiles/desktop-widgets/.
Para probar sin tocar lo real: DESKTOP_WIDGETS_CONF y DESKTOP_WIDGETS_STATE.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
# Raíz del repo: DOTFILES_DIR si está exportado; si no, dos niveles arriba de config/desktop-widgets
REPO = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[2])
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or HOME / ".local/state")
CONF = Path(os.environ.get("DESKTOP_WIDGETS_CONF") or CONFIG_HOME / "dotfiles" / "desktop-widgets.conf")
STATE = Path(os.environ.get("DESKTOP_WIDGETS_STATE") or STATE_HOME / "dotfiles" / "desktop-widgets")
TODO = STATE / "todo.json"
WEATHER_CACHE = STATE / "weather.json"
ART_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache") / "dotfiles" / "desktop-widgets" / "art"

# (id, ícono, nombre visible) — el orden es el de las tarjetas en pantalla.
WIDGETS = [
    ("clock", "󰥔", "Clock & date"),
    ("music", "󰎆", "Now playing"),
    ("weather", "󰖐", "Weather"),
    ("system", "󰍛", "System"),
    ("agents", "󰚩", "AI agents"),
    ("status", "󰄬", "Status"),
    ("todo", "󰄲", "Todo"),
    ("agenda", "󰃭", "Agenda"),
    ("pomodoro", "󱎫", "Pomodoro"),
    ("phone", "󰏲", "Phone"),
    ("network", "󰛳", "Network"),
]
# Arrancan apagados (se prenden en Settings → Desktop widgets)
OFF_BY_DEFAULT = {"agenda", "pomodoro", "phone", "network"}
# Posiciones en la pantalla: grilla de 3×3 (fila arriba/medio/abajo × columna
# izquierda/centro/derecha). Varios widgets en la misma zona se apilan en el
# orden de la clave `order`.
POSITIONS = [("top-left", "Top left"), ("top", "Top"), ("top-right", "Top right"),
             ("left", "Left"), ("center", "Center"), ("right", "Right"),
             ("bottom-left", "Bottom left"), ("bottom", "Bottom"), ("bottom-right", "Bottom right")]
POS_IDS = [p for p, _ in POSITIONS]

# Presets: ubicación de todos de una vez (Settings → Presets). "custom" = el
# usuario movió alguno a mano.
PRESETS = {
    "dashboard": ("Dashboard (centered)", {w: "center" for w, _, _ in WIDGETS}),
    "column-left": ("Column (left)", {w: "left" for w, _, _ in WIDGETS}),
    "column-right": ("Column (right)", {w: "right" for w, _, _ in WIDGETS}),
    "spread": ("Spread (corners)", {"clock": "center", "music": "bottom-left", "weather": "top-right",
                                    "system": "bottom-right", "agents": "right", "status": "left",
                                    "todo": "top-left", "agenda": "top-left", "pomodoro": "bottom",
                                    "phone": "bottom-right", "network": "right"}),
}
LAYOUTS = [(k, v[0]) for k, v in PRESETS.items()]
DEFAULTS = {"layout": "dashboard", **{w: "off" if w in OFF_BY_DEFAULT else "on" for w, _, _ in WIDGETS},
            "order": ",".join(w for w, _, _ in WIDGETS),
            "weather_city": "", "weather_lat": "", "weather_lon": "",   # se elige en Settings
            "units": "metric",
            # Agenda: obsidian (calendarios de Full Calendar de agenda_vault) | ics (agenda_ics)
            "agenda_source": "ics", "agenda_vault": "", "agenda_ics": "",
            "agenda_days": "7",
            # Pomodoro: minutos de foco / pausa corta / pausa larga, pausa larga cada N focos,
            # y si se activa No molestar (dunst) durante el foco
            "pomo_work": "25", "pomo_short": "5", "pomo_long": "15", "pomo_every": "4", "pomo_dnd": "off",
            # Teléfono (KDE Connect): id del dispositivo; vacío = el primero conectado
            "phone_device": "",
            # Red: consultar la IP pública (api.ipify.org, cada 30 min)
            "net_public_ip": "off"}
CONF_HEADER = """# Widgets de escritorio (config/desktop-widgets/): se muestran en los
# workspaces sin ventanas. Lo escribe Settings → Desktop → Desktop widgets; el
# daemon lo relee solo. Claves: <widget>=on|off, pos_<widget>=<zona>
# (top-left|top|top-right|left|center|right|bottom-left|bottom|bottom-right),
# order=<widgets en orden de apilado>, layout=<último preset|custom>,
# weather_city/lat/lon, units=metric|imperial, agenda_source=ics|obsidian,
# agenda_ics=<URLs o archivos .ics>, agenda_vault, agenda_days, pomo_*,
# phone_device, net_public_ip.
"""


# ── Escritura atómica ─────────────────────────────────────

def write_atomic(path: Path, text: str) -> None:
    """Temporal en la misma carpeta + os.replace (inode nuevo, nunca a medias)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


# ── Config ────────────────────────────────────────────────

def load_conf(path: Path = CONF) -> dict:
    conf = dict(DEFAULTS)
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                conf[k.strip()] = v.strip()
    except OSError:
        pass
    if conf["layout"] not in PRESETS and conf["layout"] != "custom":
        conf["layout"] = "dashboard"
    # Sin pos_<widget> (config vieja o widget nuevo): la del preset elegido
    base = PRESETS.get(conf["layout"], PRESETS["dashboard"])[1]
    for w, _, _ in WIDGETS:
        if conf.get(f"pos_{w}") not in POS_IDS:
            conf[f"pos_{w}"] = base.get(w, "center")
    return conf


def order(conf: dict) -> list[str]:
    """Orden de apilado: el de la config, con los que falten al final."""
    ids = [w for w, _, _ in WIDGETS]
    seen = [w for w in (x.strip() for x in conf.get("order", "").split(",")) if w in ids]
    return list(dict.fromkeys(seen + ids))


def placement(conf: dict) -> dict[str, list[str]]:
    """Zona → widgets prendidos que van ahí, en orden."""
    out: dict[str, list[str]] = {p: [] for p in POS_IDS}
    for w in order(conf):
        if enabled(conf, w):
            out[conf[f"pos_{w}"]].append(w)
    return out


def apply_preset(name: str, path: Path = CONF) -> None:
    pos = PRESETS[name][1]
    save_conf({"layout": name, **{f"pos_{w}": pos.get(w, "center") for w, _, _ in WIDGETS}}, path)


def set_position(widget: str, pos: str, path: Path = CONF) -> None:
    # Se escriben todas: con layout=custom las que falten ya no tendrían de
    # qué preset salir
    conf = load_conf(path)
    save_conf({"layout": "custom", **{f"pos_{w}": conf[f"pos_{w}"] for w, _, _ in WIDGETS},
               f"pos_{widget}": pos}, path)


def move(widget: str, step: int, path: Path = CONF) -> bool:
    """Sube (-1) o baja (+1) un widget dentro de su zona. False si ya está en la punta."""
    conf = load_conf(path)
    seq = order(conf)
    # Solo cuentan los prendidos (cambiar de lugar con uno apagado no se vería)
    zone = [w for w in seq if conf[f"pos_{w}"] == conf[f"pos_{widget}"] and (enabled(conf, w) or w == widget)]
    i = zone.index(widget)
    if not 0 <= i + step < len(zone):
        return False
    other = zone[i + step]
    a, b = seq.index(widget), seq.index(other)
    seq[a], seq[b] = seq[b], seq[a]
    save_conf({"order": ",".join(seq)}, path)
    return True


def save_conf(updates: dict, path: Path = CONF) -> None:
    """Cambia claves conservando comentarios y orden; las nuevas van al final."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = CONF_HEADER.splitlines()
    pending = dict(updates)
    out = []
    for line in lines:
        k = line.partition("=")[0].strip()
        if not line.lstrip().startswith("#") and "=" in line and k in pending:
            out.append(f"{k}={pending.pop(k)}")
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in pending.items()]
    write_atomic(path, "\n".join(out) + "\n")


def enabled(conf: dict, wid: str) -> bool:
    return conf.get(wid, "off" if wid in OFF_BY_DEFAULT else "on") == "on"


# ── Todo ──────────────────────────────────────────────────

def load_todo(path: Path | None = None) -> list[dict]:
    try:
        items = json.loads((path or TODO).read_text())
        return [i for i in items if isinstance(i, dict) and i.get("text")]
    except (OSError, ValueError):
        return []


def save_todo(items: list[dict], path: Path | None = None) -> None:
    write_atomic(path or TODO, json.dumps(items, ensure_ascii=False, indent=1) + "\n")


def todo_add(text: str, path: Path | None = None) -> list[dict]:
    items = load_todo(path)
    text = text.strip()
    if text:
        items.append({"text": text, "done": False, "ts": int(time.time())})
        save_todo(items, path)
    return items


def todo_toggle(idx: int, path: Path | None = None) -> list[dict]:
    items = load_todo(path)
    if 0 <= idx < len(items):
        items[idx]["done"] = not items[idx].get("done")
        save_todo(items, path)
    return items


def todo_remove(idx: int, path: Path | None = None) -> list[dict]:
    items = load_todo(path)
    if 0 <= idx < len(items):
        del items[idx]
        save_todo(items, path)
    return items


def todo_clear_done(path: Path | None = None) -> list[dict]:
    items = [i for i in load_todo(path) if not i.get("done")]
    save_todo(items, path)
    return items


# ── Hyprland ──────────────────────────────────────────────

def hypr_socket(name: str) -> str | None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return f"{run}/hypr/{sig}/{name}"


def hypr_json(cmd: str):
    """`hyprctl -j <cmd>` por el socket (sin lanzar procesos)."""
    path = hypr_socket(".socket.sock")
    if not path:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(path)
            s.sendall(f"j/{cmd}".encode())
            data = b""
            while chunk := s.recv(65536):
                data += chunk
        return json.loads(data or b"null")
    except (OSError, ValueError):
        return None


def empty_monitors(monitors: list[dict], workspaces: list[dict]) -> set[str]:
    """Nombres de los monitores cuyo workspace activo no tiene ventanas (y que
    no tienen un workspace especial abierto encima)."""
    count = {w.get("id"): w.get("windows", 0) for w in workspaces or []}
    out = set()
    for m in monitors or []:
        if (m.get("specialWorkspace") or {}).get("id"):
            continue
        ws = (m.get("activeWorkspace") or {}).get("id")
        if count.get(ws, 0) == 0:
            out.add(m.get("name"))
    return out


# Eventos de socket2 que pueden cambiar si un workspace quedó vacío.
VIS_EVENTS = {"workspace", "workspacev2", "focusedmon", "focusedmonv2", "openwindow", "closewindow",
              "movewindow", "movewindowv2", "changefloatingmode", "activespecial", "activespecialv2",
              "moveworkspace", "moveworkspacev2", "createworkspace", "destroyworkspace",
              "monitoradded", "monitoraddedv2", "monitorremoved", "monitorremovedv2"}


# ── Sistema ───────────────────────────────────────────────

def cpu_times() -> tuple[int, int]:
    with open("/proc/stat") as f:
        vals = [int(x) for x in f.readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return idle, sum(vals)


def cpu_pct(prev: tuple[int, int], cur: tuple[int, int]) -> float:
    di, dt = cur[0] - prev[0], cur[1] - prev[1]
    return 0.0 if dt <= 0 else max(0.0, min(100.0, 100.0 * (1 - di / dt)))


def mem_info() -> tuple[float, int, int]:
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0]) * 1024
    total, avail = info.get("MemTotal", 1), info.get("MemAvailable", 0)
    return 100.0 * (total - avail) / total, total - avail, total


def disk_info(path: str = "/") -> tuple[float, int, int]:
    st = os.statvfs(path)
    total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    return (100.0 * (total - free) / total if total else 0.0), total - free, total


def battery() -> tuple[int, str] | None:
    for d in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            return int((d / "capacity").read_text()), (d / "status").read_text().strip()
        except (OSError, ValueError):
            continue
    return None


def human(n: float) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if abs(n) < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in "BK" else f"{n:.1f}{unit}"
        n /= 1024
    return str(n)


def level(pct: float) -> str:
    """Clase CSS de una barra según el nivel (como meter10 de dtui)."""
    return "error" if pct >= 90 else "warn" if pct >= 70 else ""


def ago(epoch: float | int | None, now: float | None = None) -> str:
    if not epoch:
        return "never"
    d = int((now or time.time()) - float(epoch))
    if d < 60:
        return "just now"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if d >= size:
            return f"{d // size}{unit} ago"
    return "just now"


def until(epoch: float | int | None, now: float | None = None) -> str:
    if not epoch:
        return ""
    d = int(float(epoch) - (now or time.time()))
    if d <= 0:
        return "now"
    h, m = divmod(d // 60, 60)
    return f"{h // 24}d {h % 24}h" if h >= 24 else f"{h}h {m:02d}m" if h else f"{m}m"


# ── Agentes IA ────────────────────────────────────────────

def providers() -> set[str]:
    conf = Path(os.environ.get("AGENTS_PROVIDERS") or CONFIG_HOME / "dotfiles" / "agents.conf")
    try:
        return {k.strip() for k, _, v in (l.partition("=") for l in conf.read_text().splitlines())
                if not k.startswith("#") and v.strip() == "on"}
    except OSError:
        return {"claude", "opencode"}


def pid_alive(pid) -> bool:
    try:
        return bool(pid) and Path(f"/proc/{int(pid)}").exists()
    except (TypeError, ValueError):
        return False


def claude_usage(base: Path | None = None) -> dict | None:
    """Uso de Claude Code desde lo que escribe claude/statusline-command.sh:
    ventanas de 5 h / 7 días y las sesiones vivas (con su % de contexto)."""
    base = base or HOME / ".claude"
    try:
        u = json.loads((base / "usage-cache.json").read_text())
    except (OSError, ValueError):
        return None
    sessions = []
    d = base / "usage-cache.d"
    for f in d.glob("*.json") if d.is_dir() else []:
        try:
            s = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if pid_alive(s.get("pid")):
            sessions.append({"label": s.get("title") or s.get("session_dir") or "?",
                             "pct": s.get("context_pct") or 0, "dir": s.get("session_dir") or ""})
    num = lambda v: None if v in (None, "") else float(v)  # noqa: E731
    return {"five": num(u.get("five_hour_pct")), "seven": num(u.get("seven_day_pct")),
            "five_reset": u.get("five_hour_reset"), "seven_reset": u.get("seven_day_reset"),
            "sessions": sorted(sessions, key=lambda s: -float(s["pct"] or 0))}


def opencode_sessions() -> list[dict]:
    script = REPO / "config" / "waybar" / "scripts" / "opencode-context.sh"
    try:
        r = subprocess.run([str(script)], capture_output=True, text=True, timeout=8)
        return json.loads(r.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


# ── Estado (updates, VPN) ─────────────────────────────────

def pending_updates(cache: Path | None = None) -> dict | None:
    """Cache de Settings → Update (solo se lee: no sale a la red)."""
    f = cache or STATE_HOME / "dotfiles" / "settings" / "update.json"
    try:
        data = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    pkgs = data.get("pkgs") or []
    return {"count": len(pkgs), "aur": sum(p.get("src") == "AUR" for p in pkgs), "time": data.get("time")}


def vpn_status() -> list[str]:
    """VPNs conectadas, desde el modo rápido de la TUI de VPN."""
    try:
        r = subprocess.run(["python3", str(REPO / "tools" / "vpn_tui.py"), "--waybar-status"],
                           capture_output=True, text=True, timeout=10)
        data = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return parse_vpn_status(data)


def parse_vpn_status(data: dict) -> list[str]:
    """{"class": "connected", "tooltip": "VPN: a, b\\n…"} → ["a", "b"]."""
    if data.get("class") != "connected":
        return []
    first = (data.get("tooltip") or "").splitlines()[0] if data.get("tooltip") else ""
    return [x.strip() for x in first.removeprefix("VPN:").split(",") if x.strip()]


# ── Pomodoro ──────────────────────────────────────────────
# Estado en STATE/pomodoro.json: así sobrevive a reinicios del daemon y lo
# puede leer Settings. phase: idle | work | short | long; ends: epoch de fin
# (corriendo) o None; left: segundos restantes si está en pausa.

POMO = STATE / "pomodoro.json"
PHASE_NAMES = {"idle": "Ready", "work": "Focus", "short": "Short break", "long": "Long break"}


def pomo_minutes(conf: dict, phase: str) -> int:
    key = {"work": "pomo_work", "short": "pomo_short", "long": "pomo_long"}.get(phase, "pomo_work")
    try:
        return max(1, int(conf.get(key, DEFAULTS[key])))
    except ValueError:
        return int(DEFAULTS[key])


def pomo_load() -> dict:
    try:
        st = json.loads(POMO.read_text())
    except (OSError, ValueError):
        st = {}
    today = time.strftime("%Y-%m-%d")
    if st.get("day") != today:                 # la cuenta de focos es por día
        st.update({"day": today, "done": 0})
    st.setdefault("phase", "idle")
    st.setdefault("ends", None)
    st.setdefault("left", None)
    return st


def pomo_save(st: dict) -> None:
    write_atomic(POMO, json.dumps(st))


def pomo_remaining(st: dict, conf: dict, now: float | None = None) -> float:
    if st.get("ends"):
        return max(0.0, st["ends"] - (now or time.time()))
    if st.get("left") is not None:
        return float(st["left"])
    return pomo_minutes(conf, "work" if st["phase"] == "idle" else st["phase"]) * 60.0


def pomo_start(st: dict, conf: dict, phase: str | None = None) -> dict:
    """Arranca (o retoma) la fase actual, o `phase` desde cero."""
    if phase:
        st.update({"phase": phase, "left": None})
    if st["phase"] == "idle":
        st["phase"] = "work"
    secs = st["left"] if st.get("left") is not None else pomo_minutes(conf, st["phase"]) * 60
    st.update({"ends": time.time() + secs, "left": None})
    return st


def pomo_pause(st: dict, conf: dict) -> dict:
    if st.get("ends"):
        st.update({"left": pomo_remaining(st, conf), "ends": None})
    return st


def pomo_next(st: dict, conf: dict, finished: bool) -> dict:
    """Pasa a la fase siguiente. Después de un foco la pausa arranca sola; después
    de una pausa queda el foco listo, esperando a que se arranque."""
    if st["phase"] == "work":
        if finished:
            st["done"] = st.get("done", 0) + 1
        every = max(1, int(conf.get("pomo_every", "4") or 4))
        brk = "long" if finished and st["done"] % every == 0 else "short"
        return pomo_start(st, conf, brk)
    st.update({"phase": "work", "ends": None, "left": None})
    return st


def pomo_reset(st: dict) -> dict:
    st.update({"phase": "idle", "ends": None, "left": None})
    return st


# ── Red ───────────────────────────────────────────────────

def default_iface() -> str | None:
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 2 and f[1] == "00000000":
                return f[0]
    except OSError:
        pass
    return None


def net_bytes(iface: str | None) -> tuple[int, int] | None:
    """(recibidos, enviados) de una interfaz, de /proc/net/dev."""
    if not iface:
        return None
    try:
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            name, _, rest = line.partition(":")
            if name.strip() == iface:
                f = rest.split()
                return int(f[0]), int(f[8])
    except (OSError, ValueError, IndexError):
        pass
    return None


def net_info() -> dict:
    """Interfaz por defecto, su IPv4, y la Wi-Fi activa (SSID + señal) si hay."""
    iface = default_iface()
    ip = None
    if iface:
        try:
            r = subprocess.run(["ip", "-j", "-4", "addr", "show", "dev", iface], capture_output=True,
                               text=True, timeout=3)
            for a in (json.loads(r.stdout or "[]") or [{}])[0].get("addr_info", []):
                ip = a.get("local")
        except (OSError, ValueError, subprocess.TimeoutExpired, IndexError):
            pass
    wifi = None
    try:
        r = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"], capture_output=True,
                           text=True, timeout=5)
        for line in r.stdout.splitlines():
            parts = line.replace("\\:", "\x00").split(":")
            if parts[0] == "yes" and len(parts) >= 3:
                wifi = {"ssid": parts[1].replace("\x00", ":"), "signal": int(parts[2] or 0)}
                break
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    kind = "wifi" if iface and iface.startswith(("wl", "wlan")) else "ethernet" if iface else None
    return {"iface": iface, "ip": ip, "wifi": wifi, "kind": kind}


PUBLIC_IP_TTL = 30 * 60


def public_ip(force: bool = False) -> str | None:
    cache = STATE / "public-ip.json"
    try:
        c = json.loads(cache.read_text())
        if not force and time.time() - c.get("time", 0) < PUBLIC_IP_TTL:
            return c.get("ip")
    except (OSError, ValueError):
        c = {}
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
            ip = r.read().decode().strip()
        write_atomic(cache, json.dumps({"time": time.time(), "ip": ip}))
        return ip
    except OSError:
        return c.get("ip")


def rate(n: float) -> str:
    """Bytes/s legibles: 1.2M/s, 340K/s."""
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}/s" if unit in "BK" else f"{n:.1f}{unit}/s"
        n /= 1024
    return f"{n:.1f}G/s"


# ── Clima (Open-Meteo) ────────────────────────────────────

WEATHER_TTL = 30 * 60

# Códigos WMO → (ícono Nerd Font de día, de noche, descripción en inglés)
WMO = {
    0: ("󰖙", "󰖔", "Clear"), 1: ("󰖙", "󰖔", "Mostly clear"), 2: ("󰖕", "󰼱", "Partly cloudy"),
    3: ("󰖐", "󰖐", "Overcast"), 45: ("󰖑", "󰖑", "Fog"), 48: ("󰖑", "󰖑", "Rime fog"),
    51: ("󰖗", "󰖗", "Light drizzle"), 53: ("󰖗", "󰖗", "Drizzle"), 55: ("󰖗", "󰖗", "Heavy drizzle"),
    56: ("󰖗", "󰖗", "Freezing drizzle"), 57: ("󰖗", "󰖗", "Freezing drizzle"),
    61: ("󰖗", "󰖗", "Light rain"), 63: ("󰖖", "󰖖", "Rain"), 65: ("󰖖", "󰖖", "Heavy rain"),
    66: ("󰙿", "󰙿", "Freezing rain"), 67: ("󰙿", "󰙿", "Freezing rain"),
    71: ("󰖘", "󰖘", "Light snow"), 73: ("󰖘", "󰖘", "Snow"), 75: ("󰼶", "󰼶", "Heavy snow"),
    77: ("󰖘", "󰖘", "Snow grains"), 80: ("󰖗", "󰖗", "Showers"), 81: ("󰖖", "󰖖", "Showers"),
    82: ("󰖖", "󰖖", "Violent showers"), 85: ("󰖘", "󰖘", "Snow showers"), 86: ("󰼶", "󰼶", "Snow showers"),
    95: ("󰖓", "󰖓", "Thunderstorm"), 96: ("󰖓", "󰖓", "Thunderstorm, hail"), 99: ("󰖓", "󰖓", "Thunderstorm, hail"),
}


def wmo(code, day: bool = True) -> tuple[str, str]:
    d, n, desc = WMO.get(int(code or 0), ("󰖐", "󰖐", "Unknown"))
    return (d if day else n), desc


def weather_url(lat: str, lon: str, units: str) -> str:
    q = {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 4,
         "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
         "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}
    if units == "imperial":
        q |= {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"}
    return "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q)


def parse_weather(data: dict, units: str = "metric") -> dict:
    cur, daily = data.get("current") or {}, data.get("daily") or {}
    icon, desc = wmo(cur.get("weather_code"), bool(cur.get("is_day", 1)))
    days = []
    for i, date in enumerate(daily.get("time") or []):
        try:
            dicon, ddesc = wmo(daily["weather_code"][i])
            days.append({"date": date, "icon": dicon, "desc": ddesc,
                         "max": round(daily["temperature_2m_max"][i]), "min": round(daily["temperature_2m_min"][i]),
                         "rain": (daily.get("precipitation_probability_max") or [None] * 99)[i]})
        except (KeyError, IndexError, TypeError):
            continue
    return {"temp": round(cur.get("temperature_2m", 0)), "feels": round(cur.get("apparent_temperature", 0)),
            "humidity": cur.get("relative_humidity_2m"), "wind": round(cur.get("wind_speed_10m", 0)),
            "icon": icon, "desc": desc, "days": days,
            "deg": "°F" if units == "imperial" else "°C", "speed": "mph" if units == "imperial" else "km/h"}


def fetch_weather(conf: dict, force: bool = False) -> dict | None:
    """Clima con cache de 30 min (por coordenadas/unidades). Sin red, devuelve
    el último cacheado aunque esté viejo."""
    if not conf.get("weather_lat") or not conf.get("weather_lon"):
        return {"unset": True}
    key = f"{conf['weather_lat']},{conf['weather_lon']},{conf['units']}"
    try:
        cached = json.loads(WEATHER_CACHE.read_text())
    except (OSError, ValueError):
        cached = None
    if cached and cached.get("key") == key and not force and time.time() - cached.get("time", 0) < WEATHER_TTL:
        return cached["data"]
    try:
        req = urllib.request.Request(weather_url(conf["weather_lat"], conf["weather_lon"], conf["units"]),
                                     headers={"User-Agent": "desktop-widgets"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = parse_weather(json.load(r), conf["units"])
    except (OSError, ValueError):
        return cached["data"] if cached and cached.get("key") == key else None
    write_atomic(WEATHER_CACHE, json.dumps({"key": key, "time": time.time(), "data": data}))
    return data


def geocode(city: str, count: int = 5) -> list[dict]:
    """Ciudades que coinciden (Open-Meteo geocoding): [{name, label, lat, lon}]."""
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": city, "count": count, "language": "en", "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": "desktop-widgets"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    out = []
    for g in data.get("results") or []:
        label = ", ".join(x for x in (g.get("name"), g.get("admin1"), g.get("country")) if x)
        out.append({"name": g.get("name", city), "label": label,
                    "lat": f"{g['latitude']:.4f}", "lon": f"{g['longitude']:.4f}"})
    return out
