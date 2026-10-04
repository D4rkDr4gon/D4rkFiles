#!/usr/bin/env python3
"""Widgets de escritorio para los workspaces vacíos (Hyprland).

Una ventana layer-shell (capa BOTTOM) por monitor que se muestra solo cuando
el workspace activo de ese monitor no tiene ventanas: reloj y fecha, lo que
suena (MPRIS vía playerctl), clima (Open-Meteo), sistema, uso de los agentes
IA, estado (updates, VPN) y una lista de pendientes rápida.

- Visibilidad: eventos del socket2 de Hyprland + `j/monitors` y
  `j/workspaces` por el socket de comandos (sin lanzar procesos).
- Mientras ningún monitor lo muestra, no hace polling (solo escucha eventos).
- Ubicación: cada widget va en una de 9 zonas (grilla 3×3, pos_<widget> en
  widgets.conf); los que comparten zona se apilan según `order`. La capa
  cubre el monitor (menos waybar) pero solo las zonas reciben clicks.
- Config: ~/.config/dotfiles/desktop-widgets.conf (Settings → Desktop →
  Desktop widgets; sin ese archivo rigen los defaults); estilo: style.css,
  generado desde style.css.tpl por scripts/theme-switch.sh. Los dos se releen
  en caliente (GFileMonitor).
- Lógica sin GTK (config, todo, datos): dwlib.py y agenda.py, al lado.

Doc: docs/components.md (Widgets de escritorio).
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except ValueError:
    # La typelib existe pero la .so todavía no está cargada en el proceso.
    import ctypes

    ctypes.CDLL("libgtk-layer-shell.so.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agenda  # noqa: E402
import dwlib  # noqa: E402

HERE = Path(__file__).resolve().parent
STYLE_PATH = Path(os.environ.get("DESKTOP_WIDGETS_STYLE", HERE / "style.css"))
NAMESPACE = "desktop-widgets"
ART_SIZE = 72
TODO_MAX = 8
COLUMN_MARGIN = 24          # separación de las zonas con los bordes (waybar ya reserva su zona)
BAR_RESERVE = 40            # alto de waybar (+ aire) que no pueden usar las columnas


def log(*a) -> None:
    print("desktop-widgets:", *a, file=sys.stderr, flush=True)


def in_thread(fn, done) -> None:
    """Corre fn() en un hilo y entrega el resultado a done() en el hilo de GTK."""
    def work():
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001 - un widget no tumba el daemon
            log("error:", e)
            res = None
        GLib.idle_add(lambda: (done(res), False)[1])
    threading.Thread(target=work, daemon=True).start()


# ── Datos ─────────────────────────────────────────────────

class Hub:
    """Estado compartido entre las ventanas (una por monitor). Cada fuente
    publica con set(clave, valor) y las tarjetas se suscriben con on()."""

    def __init__(self):
        self.data: dict = {}
        self.subs: dict[str, list] = {}
        self.active = False
        self.conf = dwlib.load_conf()
        self._busy: set[str] = set()
        self._cpu_prev = dwlib.cpu_times()
        self._music_pos = (0.0, 0.0)          # (posición en s, time.monotonic())
        self._music_proc = None
        self._music_stream = None
        self._net_prev = None                 # (bytes rx, bytes tx, time.monotonic())
        self.net_hist: list[tuple[float, float]] = []
        self.pomo = dwlib.pomo_load()
        self._pomo_timer = None

    def on(self, key: str, fn) -> None:
        self.subs.setdefault(key, []).append(fn)
        if key in self.data:
            fn(self.data[key])

    def clear_subs(self) -> None:
        self.subs.clear()

    def set(self, key: str, value) -> None:
        self.data[key] = value
        for fn in list(self.subs.get(key, [])):
            try:
                fn(value)
            except Exception as e:  # noqa: BLE001
                log(f"widget {key}:", e)

    def background(self, key: str, fn) -> None:
        """Una sola corrida a la vez por clave."""
        if key in self._busy:
            return
        self._busy.add(key)

        def done(res):
            self._busy.discard(key)
            self.set(key, res)
        in_thread(fn, done)

    # Arranque de timers: todos chequean self.active y no hacen nada si los
    # widgets no se ven. set_active(True) fuerza un refresco inmediato.
    def start(self) -> None:
        GLib.timeout_add_seconds(1, self.tick_clock)
        GLib.timeout_add_seconds(3, self.tick_system)
        GLib.timeout_add_seconds(1, self.tick_music_pos)
        GLib.timeout_add_seconds(10, self.tick_agents)
        GLib.timeout_add_seconds(60, self.tick_status)
        GLib.timeout_add_seconds(300, self.tick_weather)
        GLib.timeout_add_seconds(300, self.tick_agenda)
        GLib.timeout_add_seconds(2, self.tick_net_rate)
        GLib.timeout_add_seconds(15, self.tick_net_info)
        GLib.timeout_add_seconds(15, self.tick_phone)
        self.start_music()
        self.watch_todo()
        self.refresh_todo()
        self.pomo_schedule()

    def set_active(self, active: bool) -> None:
        if active and not self.active:
            self.active = True
            self.refresh_all()
        self.active = active

    def refresh_all(self) -> None:
        self.tick_clock()
        self.tick_system()
        self.tick_agents()
        self.tick_status()
        self.tick_weather()
        self.tick_agenda()
        self.tick_net_info()
        self.tick_phone()
        self.resync_music()

    def tick_clock(self) -> bool:
        if self.active:
            self.set("clock", datetime.now())
            if dwlib.enabled(self.conf, "pomodoro"):
                self.set("pomodoro", self.pomo)
        return True

    # Agenda: la arma agenda.py (ICS con cache + notas de Full Calendar)
    def tick_agenda(self, force: bool = False) -> bool:
        if self.active and dwlib.enabled(self.conf, "agenda"):
            conf = dict(self.conf)
            try:
                days = max(1, int(conf.get("agenda_days", "7")))
            except ValueError:
                days = 7
            self.background("agenda", lambda: agenda.upcoming(conf, dwlib.STATE / "agenda", days=days,
                                                              force=force))
        return True

    # Red: el ritmo sale de /proc/net/dev cada 2 s (barato, en el hilo de GTK);
    # SSID/IP cada 15 s en un hilo (nmcli tarda).
    NET_HIST = 60

    def tick_net_rate(self) -> bool:
        if not dwlib.enabled(self.conf, "network"):
            return True
        iface = (self.data.get("net_info") or {}).get("iface") or dwlib.default_iface()
        cur = dwlib.net_bytes(iface)
        now = time.monotonic()
        if cur and self._net_prev and self._net_prev[3] == iface:
            dt = max(0.1, now - self._net_prev[2])
            rx, tx = max(0, cur[0] - self._net_prev[0]) / dt, max(0, cur[1] - self._net_prev[1]) / dt
            self.net_hist = (self.net_hist + [(rx, tx)])[-self.NET_HIST:]
            if self.active:
                self.set("net_rate", (rx, tx))
        self._net_prev = (cur[0], cur[1], now, iface) if cur else None
        return True

    def tick_net_info(self) -> bool:
        if self.active and dwlib.enabled(self.conf, "network"):
            want_ip = self.conf.get("net_public_ip") == "on"
            self.background("net_info", lambda: {**dwlib.net_info(),
                                                 "public": dwlib.public_ip() if want_ip else None})
        return True

    def tick_phone(self) -> bool:
        if self.active and dwlib.enabled(self.conf, "phone"):
            dev = self.conf.get("phone_device", "")
            self.background("phone", lambda: phone_status(dev))
        return True

    # Pomodoro: el fin de fase se agenda con un timeout propio (corre aunque los
    # widgets no se vean); el estado vive en STATE/pomodoro.json.
    def pomo_schedule(self) -> None:
        if self._pomo_timer:
            GLib.source_remove(self._pomo_timer)
            self._pomo_timer = None
        if self.pomo.get("ends"):
            secs = max(0.0, self.pomo["ends"] - time.time())
            self._pomo_timer = GLib.timeout_add(int(secs * 1000) + 50, self.pomo_finished)
        self.pomo_dnd()
        self.set("pomodoro", self.pomo)

    def pomo_action(self, action: str) -> None:
        st, conf = self.pomo, self.conf
        if action == "toggle":
            dwlib.pomo_pause(st, conf) if st.get("ends") else dwlib.pomo_start(st, conf)
        elif action == "skip":
            dwlib.pomo_next(st, conf, finished=False)
        elif action == "reset":
            dwlib.pomo_reset(st)
        dwlib.pomo_save(st)
        self.pomo_schedule()

    def pomo_finished(self) -> bool:
        self._pomo_timer = None
        st = self.pomo
        if not st.get("ends") or st["ends"] - time.time() > 1:
            return False
        was = st["phase"]
        dwlib.pomo_next(st, self.conf, finished=True)
        dwlib.pomo_save(st)
        if was == "work":
            mins = dwlib.pomo_minutes(self.conf, st["phase"])
            notify("Focus session done", f"Take a {mins} min {'long ' if st['phase'] == 'long' else ''}break.")
        else:
            notify("Break is over", "Ready for the next focus session.")
        self.pomo_schedule()
        return False

    def pomo_dnd(self) -> None:
        """No molestar de dunst mientras corre un foco (si pomo_dnd=on)."""
        focus = (self.conf.get("pomo_dnd") == "on" and self.pomo["phase"] == "work"
                 and bool(self.pomo.get("ends")))
        if not focus and getattr(self, "_dnd_on", None) is None:
            return                        # nunca lo prendió: no tocar el DND del usuario
        if focus != getattr(self, "_dnd_on", None):
            self._dnd_on = focus
            subprocess.Popen(["dunstctl", "set-paused", "true" if focus else "false"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def tick_system(self) -> bool:
        if self.active and dwlib.enabled(self.conf, "system"):
            cur = dwlib.cpu_times()
            cpu = dwlib.cpu_pct(self._cpu_prev, cur)
            self._cpu_prev = cur
            self.set("system", {"cpu": cpu, "mem": dwlib.mem_info(), "disk": dwlib.disk_info("/"),
                                "bat": dwlib.battery()})
        return True

    def tick_agents(self) -> bool:
        if self.active and dwlib.enabled(self.conf, "agents"):
            def get():
                prov = dwlib.providers()
                return {"claude": dwlib.claude_usage() if "claude" in prov else None,
                        "opencode": dwlib.opencode_sessions() if "opencode" in prov else []}
            self.background("agents", get)
        return True

    def tick_status(self) -> bool:
        if self.active and dwlib.enabled(self.conf, "status"):
            self.background("status", lambda: {"updates": dwlib.pending_updates(),
                                               "vpn": dwlib.vpn_status()})
        return True

    def tick_weather(self, force: bool = False) -> bool:
        if self.active and dwlib.enabled(self.conf, "weather"):
            conf = dict(self.conf)
            self.background("weather", lambda: dwlib.fetch_weather(conf, force=force))
        return True

    # Música: `playerctl metadata --follow` avisa cada cambio (sin polling);
    # la posición se interpola mientras suena y se resincroniza al mostrarse.
    MUSIC_FMT = "\t".join(["{{status}}", "{{playerName}}", "{{artist}}", "{{title}}", "{{album}}",
                           "{{mpris:artUrl}}", "{{mpris:length}}", "{{position}}", "{{playerInstance}}",
                           "{{xesam:url}}"])

    def start_music(self) -> None:
        if not dwlib.enabled(self.conf, "music") or self._music_proc:
            return
        try:
            self._music_proc = Gio.Subprocess.new(
                ["playerctl", "metadata", "--follow", "--format", self.MUSIC_FMT],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as e:
            log("playerctl:", e.message)
            return
        self._music_stream = Gio.DataInputStream.new(self._music_proc.get_stdout_pipe())
        self._music_stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._music_line)

    def stop_music(self) -> None:
        if self._music_proc:
            self._music_proc.force_exit()
            self._music_proc = None
        self.set("music", None)

    def _music_line(self, stream, res) -> None:
        try:
            line, _ = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if stream is not self._music_stream:   # de un playerctl que ya se cortó
            return
        if line is None:                     # playerctl terminó: reintentar en 5 s
            self._music_proc = None
            GLib.timeout_add_seconds(5, lambda: (self.start_music(), False)[1])
            return
        self.set("music", self.parse_music(line))
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._music_line)

    def parse_music(self, line: str) -> dict | None:
        parts = line.split("\t")
        if len(parts) < 8 or not parts[0] or not (parts[3] or parts[2]):
            return None
        status, player, artist, title, album, art, length, pos = parts[:8]
        instance, url = (parts[8:10] + ["", ""])[:2]
        to_s = lambda v: int(v) / 1e6 if v.strip().isdigit() else 0.0  # noqa: E731
        self._music_pos = (to_s(pos), time.monotonic())
        m = {"status": status, "player": player, "artist": artist, "title": title or artist,
             "album": album, "art": art, "length": to_s(length), "instance": instance or player, "url": url}
        self.resolve_app(m)
        return m

    def resolve_app(self, m: dict) -> None:
        """App real detrás del reproductor (webapp, Spotify, navegador…), en un
        hilo y cacheada por (instancia, dominio)."""
        key = (m["instance"], url_host(m["url"]))
        if key == getattr(self, "_app_key", None):
            return
        self._app_key = key
        cache = self.__dict__.setdefault("_app_cache", {})
        if key in cache:
            self.set("music_app", cache[key])
            return

        def done(app):
            cache[key] = app
            if self._app_key == key:
                self.set("music_app", app)
        in_thread(lambda: player_app(m["instance"], m["url"]), done)

    def music_position(self) -> float:
        pos, t0 = self._music_pos
        m = self.data.get("music")
        if m and m["status"] == "Playing":
            pos += time.monotonic() - t0
        return min(pos, m["length"]) if m and m["length"] else pos

    def tick_music_pos(self) -> bool:
        if self.active and self.data.get("music"):
            self.set("music_pos", self.music_position())
        return True

    def resync_music(self) -> None:
        if not self.data.get("music"):
            return

        def get():
            r = subprocess.run(["playerctl", "position"], capture_output=True, text=True, timeout=3)
            return float(r.stdout.strip())

        def done(res):
            if res is not None:
                self._music_pos = (res, time.monotonic())
                self.set("music_pos", self.music_position())
        in_thread(get, done)

    # Todo: el archivo lo pueden cambiar el widget o Settings → se vigila.
    def watch_todo(self) -> None:
        dwlib.TODO.parent.mkdir(parents=True, exist_ok=True)
        self._todo_mon = Gio.File.new_for_path(str(dwlib.TODO)).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
        self._todo_mon.connect("changed", lambda *_: self.refresh_todo())

    def refresh_todo(self) -> None:
        self.set("todo", dwlib.load_todo())


# ── Piezas de UI ──────────────────────────────────────────

def label(text: str = "", cls: str = "text", xalign: float = 0.0, ellipsize: bool = False,
          width: int = 0) -> Gtk.Label:
    lb = Gtk.Label(label=text, xalign=xalign)
    for c in cls.split():
        lb.get_style_context().add_class(c)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END)
    if width:
        lb.set_max_width_chars(width)
        lb.set_width_chars(width)
    return lb


def set_shown(widget: Gtk.Widget, on: bool) -> None:
    """Mostrar u ocultar de forma que un show_all() posterior (al rearmar la
    ventana) no lo vuelva a prender."""
    widget.set_no_show_all(not on)
    widget.show_all() if on else widget.hide()


def set_classes(widget: Gtk.Widget, on: str, choices=("ok", "warn", "error")) -> None:
    ctx = widget.get_style_context()
    for c in choices:
        ctx.remove_class(c)
    if on:
        ctx.add_class(on)


def card(title: str) -> tuple[Gtk.Box, Gtk.Box]:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    outer.get_style_context().add_class("card")
    outer.pack_start(label(title.upper(), "card-title"), False, False, 0)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    outer.pack_start(body, True, True, 0)
    return outer, body


class Meter(Gtk.Box):
    """Fila "CPU [=====    ] 34%" con color por nivel."""

    def __init__(self, name: str):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.name = label(name, "muted mono", width=6)
        self.bar = Gtk.ProgressBar()
        self.bar.set_valign(Gtk.Align.CENTER)
        self.value = label("", "text value", xalign=1.0, width=12)
        self.pack_start(self.name, False, False, 0)
        self.pack_start(self.bar, True, True, 0)
        self.pack_start(self.value, False, False, 0)

    def update(self, pct: float | None, text: str, cls: str | None = None) -> None:
        self.bar.set_fraction(max(0.0, min(1.0, (pct or 0) / 100)))
        set_classes(self.bar, dwlib.level(pct or 0) if cls is None else cls)
        self.value.set_text(text)


def notify(title: str, body: str) -> None:
    subprocess.Popen(["notify-send", "-a", "Desktop widgets", "-i", "alarm-symbolic", title, body],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_uri(uri: str) -> None:
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error as e:
        log("open:", e.message)


# ── KDE Connect (D-Bus) ───────────────────────────────────

KDEC = "org.kde.kdeconnect"
KDEC_DEV = "/modules/kdeconnect/devices/"


def _dbus(bus, path: str, iface: str, method: str, args=None, reply: str | None = None):
    return bus.call_sync(KDEC, path, iface, method, args, GLib.VariantType(reply) if reply else None,
                         Gio.DBusCallFlags.NONE, 2000, None).unpack()


def _props(bus, path: str, iface: str) -> dict:
    try:
        return _dbus(bus, path, "org.freedesktop.DBus.Properties", "GetAll", GLib.Variant("(s)", (iface,)),
                     "(a{sv})")[0]
    except GLib.Error:
        return {}


def phone_status(pref: str = "") -> dict:
    """Teléfono emparejado y alcanzable: batería, señal, notificaciones activas."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        devs = _dbus(bus, "/modules/kdeconnect", f"{KDEC}.daemon", "devices",
                     GLib.Variant("(bb)", (True, True)), "(as)")[0]
    except GLib.Error:
        return {"state": "no-daemon"}
    if not devs:
        return {"state": "unreachable"}
    dev = pref if pref in devs else devs[0]
    path = KDEC_DEV + dev
    info = _props(bus, path, f"{KDEC}.device")
    bat = _props(bus, path + "/battery", f"{KDEC}.device.battery")
    net = _props(bus, path + "/connectivity_report", f"{KDEC}.device.connectivity_report")
    notes = []
    try:
        ids = _dbus(bus, path + "/notifications", f"{KDEC}.device.notifications", "activeNotifications",
                    None, "(as)")[0]
    except GLib.Error:
        ids = []
    for nid in list(ids)[-4:][::-1]:
        n = _props(bus, f"{path}/notifications/{nid}", f"{KDEC}.device.notifications.notification")
        if n:
            notes.append({"app": n.get("appName", ""), "title": n.get("title", ""), "text": n.get("text", "")})
    return {"state": "ok", "id": dev, "name": info.get("name", "Phone"),
            "battery": bat.get("charge") if bat.get("hasBattery", True) else None,
            "charging": bat.get("isCharging", False),
            "net": net.get("cellularNetworkType", ""), "signal": net.get("cellularNetworkStrength", -1),
            "notifications": notes}


def phone_ring(dev: str) -> None:
    def work():
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            _dbus(bus, KDEC_DEV + dev + "/findmyphone", f"{KDEC}.device.findmyphone", "ring")
        except GLib.Error as e:
            log("ring:", e.message)
    threading.Thread(target=work, daemon=True).start()


# ── App detrás de un reproductor MPRIS ────────────────────
# Dominio de la URL que suena → (nombre, ícono): para pestañas de navegador
# que no son una webapp propia.
SITE_APPS = {
    "music.youtube.com": ("YouTube Music", "youtube-music"), "youtube.com": ("YouTube", "youtube"),
    "youtu.be": ("YouTube", "youtube"), "open.spotify.com": ("Spotify", "spotify"),
    "soundcloud.com": ("SoundCloud", "soundcloud"), "twitch.tv": ("Twitch", "twitch"),
    "music.apple.com": ("Apple Music", "apple-music"), "deezer.com": ("Deezer", "deezer"),
    "tidal.com": ("TIDAL", "tidal"), "netflix.com": ("Netflix", "netflix"),
    "primevideo.com": ("Prime Video", "amazon-prime-video"), "disneyplus.com": ("Disney+", "disneyplus"),
    "bandcamp.com": ("Bandcamp", "bandcamp"), "vimeo.com": ("Vimeo", "vimeo"),
}
BROWSERS = {"firefox", "chromium", "chrome", "google-chrome", "brave", "brave-browser", "vivaldi", "opera",
            "librewolf", "zen", "zen-browser", "microsoft-edge", "floorp"}
# Procesos que nunca son "la app" (si el navegador se abrió desde una terminal
# o un lanzador, subir por el árbol no tiene que terminar en ellos)
LAUNCHERS = {"kitty", "foot", "alacritty", "wezterm", "wezterm-gui", "ghostty", "konsole", "gnome-terminal",
             "xterm", "hyprland", "uwsm", "walker", "rofi", "elephant", "dbus-daemon", "systemd", "init",
             "sh", "bash", "zsh", "fish", "dash", "env", "setsid", "nohup", "sudo", "tmux", "herdr", "qtile"}
FFPWA_RE = re.compile(r"FFPWA-([0-9A-Z]{26})|--pwa[= ]([0-9A-Z]{26})|site launch ([0-9A-Z]{26})")


def url_host(url: str) -> str:
    m = re.match(r"\w+://([^/:]+)", url or "")
    return m.group(1).lower().removeprefix("www.").removeprefix("m.") if m else ""


def _desktop(app_id: str):
    try:
        return Gio.DesktopAppInfo.new(app_id if app_id.endswith(".desktop") else app_id + ".desktop")
    except TypeError:
        return None


def _app_from(info) -> dict | None:
    if not info:
        return None
    icon = info.get_icon()
    return {"name": info.get_name(), "icon": icon.to_string() if icon else None}


def _proc_chain(pid: int, depth: int = 8) -> list[tuple[str, str]]:
    """[(exe, cmdline)] del proceso y sus padres."""
    out = []
    while pid > 1 and depth:
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            exe = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
            stat = Path(f"/proc/{pid}/stat").read_text()
            pid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        out.append((exe, cmd))
        depth -= 1
    return out


def player_app(instance: str, url: str) -> dict | None:
    """{"name", "icon"} de la app que reproduce: webapp de firefoxpwa (su
    .desktop), Spotify aunque MPRIS lo publique como chromium, el DesktopEntry
    de MPRIS, el sitio de la URL si es una pestaña, o el navegador."""
    bus_name = f"org.mpris.MediaPlayer2.{instance}"
    entry, identity, chain = "", "", []
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        pid = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                            "GetConnectionUnixProcessID", GLib.Variant("(s)", (bus_name,)),
                            GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        chain = _proc_chain(pid)
        props = bus.call_sync(bus_name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "GetAll",
                              GLib.Variant("(s)", ("org.mpris.MediaPlayer2",)), GLib.VariantType("(a{sv})"),
                              Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        entry, identity = props.get("DesktopEntry", ""), props.get("Identity", "")
    except GLib.Error:
        pass
    # 1) Webapp de firefoxpwa: su id está en la línea de comandos del runtime
    for _exe, cmd in chain:
        m = FFPWA_RE.search(cmd)
        if m:
            app = _app_from(_desktop("FFPWA-" + next(g for g in m.groups() if g)))
            if app:
                return app
    # 2) Spotify (u otra app con .desktop propio) aunque MPRIS diga chromium:
    #    el dueño del bus o sus dos padres inmediatos, sin terminales/lanzadores
    near = [(e, c) for e, c in chain[:3] if e.lower() not in LAUNCHERS and not e.lower().startswith("python")]
    for exe, cmd in near:
        for cand in (exe, os.path.basename(cmd.split(" ", 1)[0])):
            base = cand.lower().removesuffix(".bin").removesuffix("-bin")
            if base and base not in BROWSERS and base not in LAUNCHERS:
                app = _app_from(_desktop(base)) or _app_from(_desktop(base + "-client"))
                if app:
                    return app
    # 3) DesktopEntry de MPRIS, salvo que sea un navegador (entonces manda el sitio)
    browser = None
    if entry:
        app = _app_from(_desktop(entry))
        if entry.split(".")[-1].lower() not in BROWSERS and app:
            return app
        browser = app
    host = url_host(url)
    for dom, (name, icon) in SITE_APPS.items():
        if host == dom or host.endswith("." + dom):
            return {"name": name, "icon": icon}
    if browser:
        return browser
    for exe, _cmd in near:
        for cand in (exe.lower(), exe.lower() + "-browser"):
            app = _app_from(_desktop(cand))
            if app:
                return app
    return {"name": identity, "icon": None} if identity else None


def app_pixbuf(icon: str | None, size: int):
    """Pixbuf de un ícono (nombre del tema, ruta o Gio.Icon serializado)."""
    if not icon:
        return None
    theme = Gtk.IconTheme.get_default()
    try:
        if icon.startswith("/"):
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(icon, size, size, True)
        gicon = Gio.Icon.new_for_string(icon)
        info = theme.lookup_by_gicon(gicon, size, Gtk.IconLookupFlags.FORCE_SIZE)
        return info.load_icon() if info else None
    except GLib.Error:
        return None


def fmt_time(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ── Tarjetas ──────────────────────────────────────────────

def build_clock(hub: Hub, xalign: float = 0.5) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    t = label("", xalign=xalign)
    t.set_name("clock-time")
    d = label("", xalign=xalign)
    d.set_name("clock-date")
    box.pack_start(t, False, False, 0)
    box.pack_start(d, False, False, 0)

    def upd(now: datetime):
        t.set_text(now.strftime("%H:%M"))
        txt = now.strftime("%A %d %B")
        d.set_text(txt[:1].upper() + txt[1:])
    hub.on("clock", upd)
    return box


def build_music(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰎆  Now playing")
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
    art = Gtk.Image()
    art.set_name("music-art")
    art.set_size_request(ART_SIZE, ART_SIZE)
    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    badge = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    badge_icon = Gtk.Image()
    badge_name = label("", "muted")
    badge.pack_start(badge_icon, False, False, 0)
    badge.pack_start(badge_name, False, False, 0)
    info.pack_start(badge, False, False, 0)
    title = label("", "text", ellipsize=True, width=26)
    artist = label("", "muted", ellipsize=True, width=26)
    bar = Gtk.ProgressBar()
    times = label("", "muted mono")
    info.pack_start(title, False, False, 0)
    info.pack_start(artist, False, False, 0)
    info.pack_start(bar, False, False, 4)
    info.pack_start(times, False, False, 0)
    row.pack_start(art, False, False, 0)
    row.pack_start(info, True, True, 0)
    body.pack_start(row, False, False, 0)

    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, halign=Gtk.Align.CENTER)
    play = None
    for icon, cmd in (("󰒮", "previous"), ("󰐊", "play-pause"), ("󰒭", "next")):
        b = Gtk.Button(label=icon)
        b.get_style_context().add_class("media-btn")
        # Al reproductor que se muestra, no al que playerctl elija por defecto
        b.connect("clicked", lambda _b, c=cmd: subprocess.Popen(
            ["playerctl", *(["-p", state["instance"]] if state.get("instance") else []), c],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        controls.pack_start(b, False, False, 0)
        if cmd == "play-pause":
            play = b
    body.pack_start(controls, False, False, 0)
    outer.set_no_show_all(True)
    state = {"art": None, "length": 0.0, "instance": None, "cover": False, "app": None}

    def set_fallback():
        """Sin portada: el logo de la app que suena (o la nota genérica)."""
        pb = app_pixbuf((state["app"] or {}).get("icon"), ART_SIZE)
        if pb:
            art.set_from_pixbuf(pb)
        else:
            art.set_from_icon_name("audio-x-generic", Gtk.IconSize.DIALOG)

    def set_art(path: str | None):
        state["cover"] = False
        if not path:
            set_fallback()
            return
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, ART_SIZE, ART_SIZE, True)
            art.set_from_pixbuf(pb)
            state["cover"] = True
        except GLib.Error:
            set_fallback()

    def load_art(url: str):
        if url == state["art"]:
            return
        state["art"] = url
        if url.startswith("file://"):
            set_art(urllib.request.url2pathname(url[7:]))
        elif url.startswith(("http://", "https://")):
            dest = dwlib.ART_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".img")

            def get():
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with urllib.request.urlopen(url, timeout=10) as r:
                        dwlib.write_atomic_bytes(dest, r.read())
                return str(dest)
            in_thread(get, lambda p: state["art"] == url and set_art(p))
        else:
            set_art(None)

    def show(on: bool):
        # En el dashboard la tarjeta va dentro de un FlowBoxChild: ocultarlo
        # también para que no quede un hueco.
        parent = outer.get_parent()
        for w in (outer, parent) if isinstance(parent, Gtk.FlowBoxChild) else (outer,):
            w.set_no_show_all(not on)
            w.show_all() if on else w.hide()

    def upd(m):
        if not m:
            show(False)
            return
        state["instance"] = m.get("instance")
        title.set_text(m["title"])
        artist.set_text(" · ".join(x for x in (m["artist"], m["album"]) if x) or m["player"])
        play.set_label("󰏤" if m["status"] == "Playing" else "󰐊")
        state["length"] = m["length"]
        bar.set_visible(bool(m["length"]))
        times.set_visible(bool(m["length"]))
        load_art(m["art"])
        show(True)
        bar.set_visible(bool(m["length"]))
        times.set_visible(bool(m["length"]))

    def upd_pos(pos: float):
        if state["length"]:
            bar.set_fraction(min(1.0, pos / state["length"]))
            times.set_text(f"{fmt_time(pos)} / {fmt_time(state['length'])}")

    def upd_app(app):
        state["app"] = app
        pb = app_pixbuf((app or {}).get("icon"), 16)
        badge_icon.set_from_pixbuf(pb) if pb else badge_icon.clear()
        badge_name.set_text((app or {}).get("name") or "")
        set_shown(badge, bool(app and app.get("name")))
        if not state["cover"]:
            set_fallback()

    hub.on("music", upd)
    hub.on("music_pos", upd_pos)
    hub.on("music_app", upd_app)
    if "music_app" not in hub.data:
        set_shown(badge, False)
    return outer


def build_weather(hub: Hub) -> Gtk.Widget:
    city = hub.conf.get("weather_city", "")
    outer, body = card("󰖐  Weather" + (f" · {city}" if city else ""))
    top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    icon = label("", "big mono")
    icon.get_style_context().add_class("weather-icon")
    temp = label("…", "big")
    desc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    d1 = label("Loading…", "text")
    d2 = label("", "muted")
    desc.pack_start(d1, False, False, 0)
    desc.pack_start(d2, False, False, 0)
    top.pack_start(icon, False, False, 0)
    top.pack_start(temp, False, False, 0)
    top.pack_start(desc, False, False, 0)
    body.pack_start(top, False, False, 0)
    days = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
    body.pack_start(days, False, False, 4)

    def upd(w):
        if not w:
            d1.set_text("No data (offline?)")
            return
        if w.get("unset"):
            icon.set_text("󰖐")
            temp.set_text("")
            d1.set_text("No location yet")
            d2.set_text("Settings → Desktop widgets → Options")
            return
        icon.set_text(w["icon"])
        temp.set_text(f"{w['temp']}{w['deg']}")
        d1.set_text(w["desc"])
        d2.set_text(f"feels {w['feels']}° · {w['humidity']}% · {w['wind']} {w['speed']}")
        for c in days.get_children():
            days.remove(c)
        for day in w["days"][1:4]:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name = datetime.strptime(day["date"], "%Y-%m-%d").strftime("%a")
            col.pack_start(label(name.capitalize(), "muted", xalign=0.5), False, False, 0)
            col.pack_start(label(day["icon"], "text mono wicon", xalign=0.5), False, False, 0)
            col.pack_start(label(f"{day['max']}° / {day['min']}°", "text", xalign=0.5), False, False, 0)
            if day.get("rain"):
                col.pack_start(label(f"󰖗 {day['rain']}%", "muted", xalign=0.5), False, False, 0)
            days.pack_start(col, True, True, 0)
        days.show_all()

    hub.on("weather", upd)
    return outer


def build_system(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰍛  System")
    cpu, mem, disk, bat = Meter("CPU"), Meter("RAM"), Meter("Disk"), Meter("Bat")
    for m in (cpu, mem, disk, bat):
        body.pack_start(m, False, False, 0)
    bat.set_no_show_all(True)
    up = label("", "muted")
    body.pack_start(up, False, False, 2)

    def upd(s):
        if not s:
            return
        cpu.update(s["cpu"], f"{s['cpu']:.0f}%")
        pct, used, total = s["mem"]
        mem.update(pct, f"{dwlib.human(used)}/{dwlib.human(total)}")
        pct, used, total = s["disk"]
        disk.update(pct, f"{dwlib.human(used)}/{dwlib.human(total)}")
        if s["bat"]:
            cap, st = s["bat"]
            cls = "ok" if st == "Charging" else "error" if cap <= 15 else "warn" if cap <= 30 else ""
            bat.update(cap, f"{cap}%{' 󰂄' if st == 'Charging' else ''}", cls)
            bat.set_no_show_all(False)
            bat.show_all()
        try:
            secs = float(Path("/proc/uptime").read_text().split()[0])
            up.set_text(f"up {int(secs // 86400)}d {int(secs // 3600 % 24)}h {int(secs // 60 % 60)}m"
                        if secs >= 86400 else f"up {int(secs // 3600)}h {int(secs // 60 % 60)}m")
        except (OSError, ValueError):
            pass

    hub.on("system", upd)
    return outer


def build_agents(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰚩  AI agents")
    five, seven = Meter("5h"), Meter("7d")
    resets = label("", "muted")
    body.pack_start(five, False, False, 0)
    body.pack_start(seven, False, False, 0)
    body.pack_start(resets, False, False, 0)
    sessions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    body.pack_start(sessions, False, False, 4)

    def upd(a):
        for c in sessions.get_children():
            sessions.remove(c)
        if not a:
            return
        c = a.get("claude")
        for m in (five, seven, resets):
            set_shown(m, bool(c))
        if c:
            five.update(c["five"], f"{c['five'] or 0:.0f}%")
            seven.update(c["seven"], f"{c['seven'] or 0:.0f}%")
            r = [f"5h resets in {dwlib.until(c['five_reset'])}" if c.get("five_reset") else "",
                 f"7d in {dwlib.until(c['seven_reset'])}" if c.get("seven_reset") else ""]
            resets.set_text(" · ".join(x for x in r if x))
        rows = [("󰚩", s["label"], s["pct"]) for s in (c or {}).get("sessions", [])[:3]]
        rows += [("󰘦", s.get("label", "?"), s.get("pct") or 0) for s in (a.get("opencode") or [])[:2]]
        if not rows:
            sessions.pack_start(label("No active sessions", "muted"), False, False, 0)
        for icon, name, pct in rows:
            r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            r.pack_start(label(icon, "text mono"), False, False, 0)
            r.pack_start(label(name, "text", ellipsize=True, width=22), True, True, 0)
            r.pack_start(label(f"ctx {float(pct):.0f}%", "muted mono " + dwlib.level(float(pct))), False, False, 0)
            sessions.pack_start(r, False, False, 0)
        sessions.show_all()

    hub.on("agents", upd)
    return outer


def build_status(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰄬  Status")
    rows = {}
    for key in ("updates", "vpn", "todo"):
        r = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = label("", "text mono", width=2)
        text = label("…", "text", ellipsize=True, width=30)
        r.pack_start(icon, False, False, 0)
        r.pack_start(text, True, True, 0)
        body.pack_start(r, False, False, 0)
        rows[key] = (icon, text)

    def put(key, icon, text, cls=""):
        i, t = rows[key]
        i.set_text(icon)
        t.set_text(text)
        set_classes(i, cls)

    def upd(s):
        if not s:
            return
        u = s.get("updates")
        if not u:
            put("updates", "󰚰", "Updates: not checked yet", "")
        elif u["count"]:
            aur = f" ({u['aur']} AUR)" if u["aur"] else ""
            put("updates", "󰚰", f"{u['count']} updates pending{aur}", "warn")
        else:
            put("updates", "󰚰", "System up to date", "ok")
        v = s.get("vpn") or []
        put("vpn", "󰦝" if v else "󰦞", "VPN: " + ", ".join(v) if v else "No VPN connected", "ok" if v else "")

    def upd_todo(items):
        pending = sum(not i.get("done") for i in items or [])
        put("todo", "󰄲", f"{pending} pending todo{'s' if pending != 1 else ''}" if pending else "Nothing to do",
            "warn" if pending else "ok")

    hub.on("status", upd)
    hub.on("todo", upd_todo)
    return outer


def build_todo(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰄲  Todo")
    entry = Gtk.Entry()
    entry.set_placeholder_text("Add a task and press Enter")
    body.pack_start(entry, False, False, 0)
    items_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    body.pack_start(items_box, False, False, 0)
    hint = label("click: done · right click: delete", "muted")
    body.pack_start(hint, False, False, 0)

    def add(_e):
        dwlib.todo_add(entry.get_text())
        entry.set_text("")
        hub.refresh_todo()

    entry.connect("activate", add)

    def key(_e, ev):
        if ev.keyval == Gdk.KEY_Escape:
            entry.set_text("")
            release = getattr(entry.get_toplevel(), "dw_release", None)
            if release:
                release()
            return True
        return False

    entry.connect("key-press-event", key)

    def click(_w, ev, idx):
        if ev.button == 1:
            dwlib.todo_toggle(idx)
        elif ev.button == 3:
            dwlib.todo_remove(idx)
        hub.refresh_todo()
        return True

    def upd(items):
        for c in items_box.get_children():
            items_box.remove(c)
        for idx, it in list(enumerate(items or []))[:TODO_MAX]:
            ev = Gtk.EventBox()
            ev.get_style_context().add_class("todo-item")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.pack_start(label("󰄲" if it.get("done") else "󰄱", "text mono"), False, False, 0)
            txt = label("", "text", ellipsize=True, width=28)
            esc = GLib.markup_escape_text(it["text"])
            txt.set_markup(f"<s>{esc}</s>" if it.get("done") else esc)
            row.pack_start(txt, True, True, 0)
            ev.add(row)
            if it.get("done"):
                ev.get_style_context().add_class("done")
            ev.connect("button-press-event", click, idx)
            items_box.pack_start(ev, False, False, 0)
        extra = len(items or []) - TODO_MAX
        if extra > 0:
            items_box.pack_start(label(f"+{extra} more (Settings → Desktop widgets)", "muted"), False, False, 0)
        items_box.show_all()

    hub.on("todo", upd)
    return outer


def build_agenda(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰃭  Agenda")
    rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    body.pack_start(rows, False, False, 0)
    foot = label("", "muted")
    body.pack_start(foot, False, False, 2)
    MAX = 9

    def click(_w, ev, uri):
        if ev.button == 1 and uri:
            open_uri(uri)
        return True

    def upd(a):
        for c in rows.get_children():
            rows.remove(c)
        if a is None:
            rows.pack_start(label("Loading…", "muted"), False, False, 0)
            rows.show_all()
            return
        if not a["count"]:
            rows.pack_start(label("No calendars configured", "text"), False, False, 0)
            foot.set_text("Settings → Desktop widgets → Agenda")
            rows.show_all()
            return
        now = datetime.now().astimezone()
        today = now.date()
        last_day, shown = None, 0
        for e in a["events"]:
            if shown >= MAX:
                break
            d = e["start"].date() if not e["allday"] or e["start"].date() >= today else today
            if d != last_day:
                name = ("Today" if d == today else "Tomorrow" if (d - today).days == 1
                        else datetime.combine(d, datetime.min.time()).strftime("%a %d"))
                rows.pack_start(label(name.upper(), "card-title agenda-day"), False, False, 2 if last_day else 0)
                last_day = d
            ev = Gtk.EventBox()
            ev.get_style_context().add_class("todo-item")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            dot = Gtk.Label(xalign=0.5)
            dot.set_markup(f'<span foreground="{e["color"]}">●</span>' if e.get("color") else "●")
            if not e.get("color"):
                dot.get_style_context().add_class("accent")
            when = "all day" if e["allday"] else e["start"].strftime("%H:%M")
            running = not e["allday"] and e["start"] <= now < e["end"]
            row.pack_start(dot, False, False, 0)
            row.pack_start(label(when, "muted mono" + (" ok" if running else ""), width=7), False, False, 0)
            row.pack_start(label(e["title"], "text", ellipsize=True, width=28), True, True, 0)
            ev.add(row)
            if e.get("open"):
                ev.connect("button-press-event", click, e["open"])
            ev.set_tooltip_text(f"{e['title']}\n{e['cal']}" + ("" if e["allday"] else
                                f" · {e['start']:%H:%M}–{e['end']:%H:%M}"))
            rows.pack_start(ev, False, False, 0)
            shown += 1
        if not shown:
            rows.pack_start(label("Nothing coming up", "muted"), False, False, 0)
        more = len(a["events"]) - shown
        msg = [f"+{more} more"] if more > 0 else []
        if a["errors"]:
            msg.append("unreachable: " + ", ".join(a["errors"]))
        foot.set_text(" · ".join(msg))
        set_classes(foot, "warn" if a["errors"] else "")
        rows.show_all()

    hub.on("agenda", upd)
    if "agenda" not in hub.data:
        upd(None)
    return outer


def build_pomodoro(hub: Hub) -> Gtk.Widget:
    outer, body = card("󱎫  Pomodoro")
    top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    phase = label("", "text")
    dots = label("", "muted mono", xalign=1.0)
    top.pack_start(phase, True, True, 0)
    top.pack_start(dots, False, False, 0)
    clock = label("25:00", "big mono", xalign=0.5)
    clock.get_style_context().add_class("pomo-time")
    bar = Gtk.ProgressBar()
    body.pack_start(top, False, False, 0)
    body.pack_start(clock, False, False, 2)
    body.pack_start(bar, False, False, 2)
    controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, halign=Gtk.Align.CENTER)
    buttons = {}
    for icon, action, tip in (("󰐊", "toggle", "start / pause"), ("󰒭", "skip", "skip phase"),
                              ("󰑐", "reset", "reset")):
        b = Gtk.Button(label=icon)
        b.set_tooltip_text(tip)
        b.get_style_context().add_class("media-btn")
        b.connect("clicked", lambda _b, a=action: hub.pomo_action(a))
        controls.pack_start(b, False, False, 0)
        buttons[action] = b
    body.pack_start(controls, False, False, 0)

    def upd(st):
        conf = hub.conf
        left = dwlib.pomo_remaining(st, conf)
        total = dwlib.pomo_minutes(conf, "work" if st["phase"] == "idle" else st["phase"]) * 60
        running = bool(st.get("ends"))
        name = dwlib.PHASE_NAMES.get(st["phase"], "")
        phase.set_text(name + ("" if running or st["phase"] == "idle" else " · paused"))
        set_classes(phase, "ok" if running and st["phase"] != "work" else "")
        every = max(1, int(conf.get("pomo_every", "4") or 4))
        done = st.get("done", 0)
        dots.set_text("●" * (done % every) + "○" * (every - done % every) + (f"  {done}" if done else ""))
        clock.set_text(f"{int(left) // 60:02d}:{int(left) % 60:02d}")
        bar.set_fraction(0 if not total else 1 - left / total)
        set_classes(bar, "ok" if st["phase"] in ("short", "long") else "")
        buttons["toggle"].set_label("󰏤" if running else "󰐊")

    hub.on("pomodoro", upd)
    return outer


def build_phone(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰏲  Phone")
    name = label("…", "text")
    bat = Meter("Bat")
    sig = label("", "muted")
    notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    ring = Gtk.Button(label="󰂞  Ring")
    ring.set_tooltip_text("make the phone ring (find my phone)")
    ring.get_style_context().add_class("small-btn")
    ring.set_halign(Gtk.Align.START)
    state = {"id": None}
    ring.connect("clicked", lambda _b: state["id"] and phone_ring(state["id"]))
    for w in (name, bat, sig, notes, ring):
        body.pack_start(w, False, False, 0)

    def upd(p):
        for c in notes.get_children():
            notes.remove(c)
        ok = bool(p) and p.get("state") == "ok"
        for w in (bat, sig, notes, ring):
            set_shown(w, ok)
        if not p:
            return
        if not ok:
            name.set_text("KDE Connect is not running" if p.get("state") == "no-daemon"
                          else "Phone not connected")
            set_classes(name, "")
            return
        state["id"] = p["id"]
        name.set_text(p["name"])
        if p["battery"] is not None:
            cap = int(p["battery"])
            cls = "ok" if p["charging"] else "error" if cap <= 15 else "warn" if cap <= 30 else ""
            bat.update(cap, f"{cap}%{' 󰂄' if p['charging'] else ''}", cls)
        else:
            set_shown(bat, False)
        if p["signal"] is not None and p["signal"] >= 0:
            bars = "▂▄▆█"[:max(0, min(4, p["signal"]))].ljust(4, "·")
            kind = p['net'] if p['net'] not in ('', 'Unknown') else 'Cellular'
            sig.set_text(f"{kind}  {bars}")
        else:
            set_shown(sig, False)
        for n in p["notifications"]:
            r = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            r.pack_start(label(n["app"] + (f" · {n['title']}" if n["title"] else ""), "muted", ellipsize=True,
                               width=32), False, False, 0)
            if n["text"]:
                r.pack_start(label(n["text"], "text", ellipsize=True, width=32), False, False, 0)
            notes.pack_start(r, False, False, 2)
        if not p["notifications"]:
            notes.pack_start(label("No notifications", "muted"), False, False, 0)
        notes.show_all()

    hub.on("phone", upd)
    return outer


class Sparkline(Gtk.DrawingArea):
    """Bajada (acento) y subida (status ok) de los últimos NET_HIST muestras."""

    def __init__(self, hub: Hub):
        super().__init__()
        self.hub = hub
        self.set_size_request(240, 44)
        self.connect("draw", self.on_draw)

    def color(self, name: str, fallback: tuple) -> tuple:
        ok, c = self.get_style_context().lookup_color(name)
        return (c.red, c.green, c.blue) if ok else fallback

    def on_draw(self, _w, cr) -> bool:
        hist = self.hub.net_hist
        w, h = self.get_allocated_width(), self.get_allocated_height()
        if len(hist) < 2:
            return False
        top = max(max(max(rx, tx) for rx, tx in hist), 1024.0)
        step = w / (self.hub.NET_HIST - 1)
        x0 = w - step * (len(hist) - 1)
        for idx, name, fb in ((0, "dw_accent", (0.8, 0.2, 0.2)), (1, "dw_ok", (0.4, 0.7, 0.4))):
            r, g, b = self.color(name, fb)
            cr.set_line_width(1.5)
            for i, sample in enumerate(hist):
                y = h - 2 - (h - 4) * sample[idx] / top
                (cr.move_to if i == 0 else cr.line_to)(x0 + i * step, y)
            cr.set_source_rgba(r, g, b, 0.95)
            cr.stroke_preserve()
            cr.line_to(x0 + (len(hist) - 1) * step, h)
            cr.line_to(x0, h)
            cr.close_path()
            cr.set_source_rgba(r, g, b, 0.15)
            cr.fill()
        return False


def build_network(hub: Hub) -> Gtk.Widget:
    outer, body = card("󰛳  Network")
    head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    icon = label("󰈀", "big mono")
    info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    l1 = label("…", "text", ellipsize=True, width=26)
    l2 = label("", "muted mono", ellipsize=True, width=30)
    info.pack_start(l1, False, False, 0)
    info.pack_start(l2, False, False, 0)
    head.pack_start(icon, False, False, 0)
    head.pack_start(info, True, True, 0)
    body.pack_start(head, False, False, 0)
    spark = Sparkline(hub)
    body.pack_start(spark, False, False, 4)
    rates = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    down = label("󰇚 —", "mono accent")
    up = label("󰕒 —", "mono ok")
    rates.pack_start(down, False, False, 0)
    rates.pack_start(up, False, False, 0)
    body.pack_start(rates, False, False, 0)

    def upd_info(n):
        if not n:
            return
        if not n.get("iface"):
            icon.set_text("󰲛")
            l1.set_text("Offline")
            l2.set_text("")
            return
        wifi = n.get("wifi")
        if n["kind"] == "wifi" and wifi:
            icon.set_text("󰤨" if wifi["signal"] >= 75 else "󰤥" if wifi["signal"] >= 50 else
                          "󰤢" if wifi["signal"] >= 25 else "󰤟")
            l1.set_text(f"{wifi['ssid']}  {wifi['signal']}%")
        else:
            icon.set_text("󰈀")
            l1.set_text(f"Ethernet · {n['iface']}" + (f"  (Wi-Fi: {wifi['ssid']})" if wifi else ""))
        l2.set_text(" · ".join(x for x in (n.get("ip"), n.get("public") and f"public {n['public']}") if x))

    def upd_rate(r):
        down.set_text(f"󰇚 {dwlib.rate(r[0])}")
        up.set_text(f"󰕒 {dwlib.rate(r[1])}")
        spark.queue_draw()

    hub.on("net_info", upd_info)
    hub.on("net_rate", upd_rate)
    return outer


BUILDERS = {"agenda": build_agenda, "pomodoro": build_pomodoro, "phone": build_phone, "network": build_network,
            "music": build_music, "weather": build_weather, "system": build_system,
            "agents": build_agents, "status": build_status, "todo": build_todo}


# ── Ventanas ──────────────────────────────────────────────

# Eventos de socket2 tras los que se revisa si una capa tiene que soltar el teclado
FOCUS_EVENTS = {"activewindowv2", "focusedmon", "focusedmonv2", "workspace", "workspacev2"}

# Cómo se alinea cada zona dentro de la pantalla
ALIGN = {"top-left": ("start", "start"), "top": ("center", "start"), "top-right": ("end", "start"),
         "left": ("start", "center"), "center": ("center", "center"), "right": ("end", "center"),
         "bottom-left": ("start", "end"), "bottom": ("center", "end"), "bottom-right": ("end", "end")}
GTK_ALIGN = {"start": Gtk.Align.START, "center": Gtk.Align.CENTER, "end": Gtk.Align.END}
XALIGN = {"start": 0.0, "center": 0.5, "end": 1.0}
# Zonas de arriba, medio y abajo al centro: tarjetas en filas de a 3. El
# resto (costados y esquinas): en columna, partida si no entra en el alto.
ROW_ZONES = {"top", "center", "bottom"}


def split_columns(zone: Gtk.Box) -> None:
    """Reparte las tarjetas de una zona en columnas según su altura real (un
    FlowBox vertical no sirve: sin altura fija arma una sola fila). Se llama
    con la ventana ya armada: antes del CSS las alturas no son las reales."""
    split = getattr(zone, "dw_split", None)
    if not split:
        return
    row, cards, max_height, right = split
    head = [c for c in zone.get_children() if c is not row]
    free = max_height - sum(c.get_preferred_height()[1] + 12 for c in head)
    for col in row.get_children():
        for c in col.get_children():
            col.remove(c)
        row.remove(col)
    col, used = None, 0
    for c in cards:
        h = c.get_preferred_height()[1] + 12
        if col is None or (used + h > free and used):
            col, used = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), 0
            row.pack_start(col, False, False, 0)
            if right:
                row.reorder_child(col, 0)    # la primera columna, pegada al borde
        col.pack_start(c, False, False, 0)
        used += h
    row.show_all()


def build_zone(hub: Hub, pos: str, widgets: list[str], max_height: int) -> Gtk.Box:
    """Una zona de la grilla: el reloj (si va ahí) arriba y después las
    tarjetas, en filas (zonas del centro) o en columnas (costados/esquinas)."""
    halign, valign = ALIGN[pos]
    zone = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    zone.set_halign(GTK_ALIGN[halign])
    zone.set_valign(GTK_ALIGN[valign])
    zone.set_margin_start(COLUMN_MARGIN)
    zone.set_margin_end(COLUMN_MARGIN)
    zone.set_margin_top(COLUMN_MARGIN)
    zone.set_margin_bottom(COLUMN_MARGIN)
    if "clock" in widgets:
        clock = build_clock(hub, XALIGN[halign])
        if pos != "center":
            clock.get_style_context().add_class("compact")
        clock.set_halign(GTK_ALIGN[halign])
        zone.pack_start(clock, False, False, 0)
    cards = [BUILDERS[w](hub) for w in widgets if w in BUILDERS]
    if not cards:
        return zone
    if pos in ROW_ZONES:
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_homogeneous(False)
        flow.set_column_spacing(12)
        flow.set_row_spacing(12)
        flow.set_valign(Gtk.Align.START)
        flow.set_halign(Gtk.Align.CENTER)
        flow.set_max_children_per_line(3)
        flow.set_min_children_per_line(min(3, len(cards)))
        for c in cards:
            flow.add(c)
        for child in flow.get_children():
            child.set_can_focus(False)
            child.set_valign(Gtk.Align.START)
            # Tarjeta que arrancó oculta (música sin reproductor): sin hueco
            # (GTK3 muestra el FlowBoxChild al insertarlo)
            if child.get_child().get_no_show_all():
                child.set_no_show_all(True)
                child.hide()
        zone.pack_start(flow, False, False, 0)
    else:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_halign(GTK_ALIGN[halign])
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for c in cards:
            col.pack_start(c, False, False, 0)
        row.pack_start(col, False, False, 0)
        zone.pack_start(row, False, False, 0)
        # Esquinas: media pantalla, para no pisarse con la de enfrente
        height = max_height if pos in ("left", "right") else max_height // 2
        zone.dw_split = (row, cards, height, halign == "end")
    return zone


def build_root(hub: Hub, conf: dict, max_height: int = 1000) -> Gtk.Overlay:
    """Pantalla completa (menos waybar) con una zona por posición ocupada."""
    root = Gtk.Overlay()
    root.add(Gtk.Box())                       # fondo transparente
    root.dw_zones = []
    for pos, widgets in dwlib.placement(conf).items():
        if widgets:
            zone = build_zone(hub, pos, widgets, max_height)
            root.add_overlay(zone)
            root.dw_zones.append(zone)
    return root


class MonitorWindow:
    def __init__(self, hub: Hub, monitor: Gdk.Monitor, name: str | None):
        self.name = name
        self.visible = False
        self._region_id = None
        self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win.set_name("desktop-widgets")
        self.win.set_app_paintable(True)
        visual = self.win.get_screen().get_rgba_visual()
        if visual:
            self.win.set_visual(visual)

        GtkLayerShell.init_for_window(self.win)
        GtkLayerShell.set_namespace(self.win, NAMESPACE)
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_monitor(self.win, monitor)
        # ON_DEMAND: el teclado llega solo al hacer click (para el todo)
        GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.ON_DEMAND)
        # Todo el monitor menos la zona reservada de waybar; cada zona se
        # ubica sola adentro (Gtk.Overlay con halign/valign).
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self.win, edge, True)

        # Alto útil: el del monitor menos la barra (zona reservada) y márgenes
        height = monitor.get_geometry().height - BAR_RESERVE - 2 * COLUMN_MARGIN
        root = build_root(hub, conf=hub.conf, max_height=height)
        self.win.add(root)
        root.show_all()
        for zone in root.dw_zones:
            split_columns(zone)
            # Cualquier cambio de tamaño (música que aparece, un todo más)
            # recalcula la región que recibe clicks
            zone.connect("size-allocate", lambda *_: self.schedule_region())
        self.win.connect("map", lambda *_: self.schedule_region())
        # Teclado: ON_DEMAND lo da al hacer click en el todo, pero Hyprland no
        # lo devuelve solo al irse a otro monitor/ventana (la capa sigue visible
        # allá): DesktopWidgets.on_focus_event lo suelta con release_keyboard().
        self.has_kb = False
        self.win.connect("focus-in-event", lambda *_: self._kb(True))
        self.win.connect("focus-out-event", lambda *_: self._kb(False))
        self.win.dw_release = self.release_keyboard

    def _kb(self, on: bool) -> bool:
        self.has_kb = on
        return False

    def release_keyboard(self) -> None:
        """Devuelve el teclado: interactividad NONE (Hyprland reenfoca la
        ventana) y, un momento después, ON_DEMAND otra vez para que un click
        nuevo en el todo vuelva a funcionar."""
        if not self.has_kb:
            return
        self.has_kb = False
        self.win.set_focus(None)
        GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.NONE)

        def back():
            try:
                GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.ON_DEMAND)
            except Exception:  # noqa: BLE001 - la ventana pudo haberse destruido
                pass
            return False
        GLib.timeout_add(250, back)

    def schedule_region(self) -> None:
        if not self._region_id:
            self._region_id = GLib.idle_add(self.update_input_region)

    def update_input_region(self) -> bool:
        """Solo las tarjetas y el reloj reciben el mouse: el resto de la capa es
        transparente también para los clicks."""
        self._region_id = None
        region = cairo.Region()
        for zone in self.win.get_child().dw_zones:
            if not zone.get_visible():
                continue
            pos = zone.translate_coordinates(self.win, 0, 0)
            if pos:
                a = zone.get_allocation()
                region.union(cairo.RectangleInt(pos[0], pos[1], a.width, a.height))
        self.win.input_shape_combine_region(region)
        return False

    def set_visible(self, visible: bool) -> None:
        if visible != self.visible:
            self.visible = visible
            self.win.show() if visible else self.win.hide()

    def destroy(self) -> None:
        self.win.destroy()


class DesktopWidgets:
    def __init__(self):
        self.hub = Hub()
        self.windows: list[MonitorWindow] = []
        self._check_id = None
        self._rebuild_id = None
        self.provider = None
        self.load_style()
        self.monitors = []
        for path, fn in ((STYLE_PATH, self.load_style), (dwlib.CONF, self.schedule_rebuild)):
            mon = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            mon.connect("changed", lambda *_a, f=fn: f())
            self.monitors.append(mon)
        display = Gdk.Display.get_default()
        display.connect("monitor-added", lambda *_: self.schedule_rebuild())
        display.connect("monitor-removed", lambda *_: self.schedule_rebuild())
        self.build()
        self.hub.start()
        threading.Thread(target=self.listen, daemon=True).start()

    def load_style(self) -> None:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(str(STYLE_PATH))
        except GLib.Error as err:
            log("CSS inválido:", err.message)
            return
        screen = Gdk.Screen.get_default()
        if self.provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, self.provider)
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.provider = provider

    def hypr_names(self) -> dict[tuple[int, int], str]:
        """Posición lógica → nombre del monitor en Hyprland (Gdk no da el conector en GTK3)."""
        return {(m.get("x"), m.get("y")): m.get("name") for m in dwlib.hypr_json("monitors") or []}

    def build(self) -> None:
        for w in self.windows:
            w.destroy()
        self.windows = []
        self.hub.clear_subs()
        old_music = dwlib.enabled(self.hub.conf, "music")
        self.hub.conf = dwlib.load_conf()
        if dwlib.enabled(self.hub.conf, "music") and not old_music:
            self.hub.start_music()
        elif not dwlib.enabled(self.hub.conf, "music"):
            self.hub.stop_music()
        names = self.hypr_names()
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            g = mon.get_geometry()
            self.windows.append(MonitorWindow(self.hub, mon, names.get((g.x, g.y))))
        self.check()
        if self.hub.active:
            self.hub.refresh_all()

    def schedule_rebuild(self) -> None:
        if self._rebuild_id:
            GLib.source_remove(self._rebuild_id)
        self._rebuild_id = GLib.timeout_add(300, self._do_rebuild)

    def _do_rebuild(self) -> bool:
        self._rebuild_id = None
        old_key = (self.hub.conf.get("weather_lat"), self.hub.conf.get("weather_lon"), self.hub.conf.get("units"))
        self.build()
        new_key = (self.hub.conf.get("weather_lat"), self.hub.conf.get("weather_lon"), self.hub.conf.get("units"))
        if new_key != old_key:
            self.hub.data.pop("weather", None)
            self.hub.tick_weather()
        return False

    # Visibilidad: socket2 de Hyprland → debounce → consulta por el socket.
    def listen(self) -> None:
        path = dwlib.hypr_socket(".socket2.sock")
        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(path)
                    buf = b""
                    while chunk := s.recv(4096):
                        buf += chunk
                        *lines, buf = buf.split(b"\n")
                        events = [l.decode(errors="replace").partition(">>") for l in lines]
                        if any(name in dwlib.VIS_EVENTS for name, _, _ in events):
                            GLib.idle_add(self.schedule_check)
                        for name, _, data in events:
                            if name in FOCUS_EVENTS:
                                GLib.idle_add(self.on_focus_event, name, data)
            except OSError as e:
                log("socket2:", e)
            time.sleep(2)

    def on_focus_event(self, name: str, data: str) -> bool:
        """Suelta el teclado de las capas que lo tienen cuando el foco se fue:
        una ventana lo tomó (activewindowv2 con dirección) o el monitor
        enfocado es otro (focusedmon / workspace)."""
        holders = [w for w in self.windows if w.has_kb]
        if not holders:
            return False
        if name == "activewindowv2":
            if data.strip():
                for w in holders:
                    w.release_keyboard()
            return False
        focused = next((m.get("name") for m in dwlib.hypr_json("monitors") or [] if m.get("focused")), None)
        for w in holders:
            if focused and w.name != focused:
                w.release_keyboard()
        return False

    def schedule_check(self) -> bool:
        if self._check_id:
            GLib.source_remove(self._check_id)
        self._check_id = GLib.timeout_add(80, self.check)
        return False

    def check(self) -> bool:
        self._check_id = None
        monitors = dwlib.hypr_json("monitors")
        if monitors is None:
            return False
        empty = dwlib.empty_monitors(monitors, dwlib.hypr_json("workspaces") or [])
        names = {(m.get("x"), m.get("y")): m.get("name") for m in monitors}
        display = Gdk.Display.get_default()
        any_visible = False
        for i, w in enumerate(self.windows):
            if not w.name and i < display.get_n_monitors():
                g = display.get_monitor(i).get_geometry()
                w.name = names.get((g.x, g.y))
            vis = w.name in empty
            any_visible |= vis
            w.set_visible(vis)
        self.hub.set_active(any_visible)
        return False


def main() -> int:
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        log("requiere una sesión de Hyprland")
        return 1
    # Una sola instancia (exec-once + arranque a mano no duplican ventanas)
    lock = open(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "desktop-widgets.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("ya está corriendo")
        return 0
    Gtk.init(None)
    DesktopWidgets()
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix
        signal_add = GLibUnix.signal_add
    except (ValueError, ImportError):
        signal_add = GLib.unix_signal_add
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_: (Gtk.main_quit(), False)[1])
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
