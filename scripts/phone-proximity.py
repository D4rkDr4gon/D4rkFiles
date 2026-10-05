#!/usr/bin/env python3
"""phone-proximity — bloquea la sesión cuando el teléfono (KDE Connect) se aleja.

Config en ~/.config/dotfiles/phone.conf (Settings → Phone): proximity_lock=on|off,
proximity_grace (segundos fuera de alcance antes de bloquear) y proximity_device.
Lee isReachable del dispositivo por D-Bus cada 10 s (sin lanzar procesos).

Para no bloquear de más:
- Solo después de haber visto el teléfono al alcance en esta sesión, y una vez
  por salida: hasta que vuelva no bloquea de nuevo.
- Nunca si kdeconnectd no está en el bus, si la compu no tiene red (sin ruta
  por defecto el teléfono "desaparece" aunque esté al lado) o si ya hay lock.
Bloquea con `loginctl lock-session` (hypridle corre su lock_cmd). Lo lanza
exec-once en hypr/hyprland.conf; con proximity_lock=off solo relee la config.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

CONF = Path(os.environ.get("PHONE_CONF", Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
                           / "dotfiles" / "phone.conf"))
BUS = "org.kde.kdeconnect"
POLL = 10


def load_conf() -> dict:
    conf = {"proximity_lock": "off", "proximity_grace": "120", "proximity_device": ""}
    try:
        for line in CONF.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                conf[k.strip()] = v.strip()
    except OSError:
        pass
    return conf


def has_network() -> bool:
    try:
        return any(l.split()[1] == "00000000" for l in Path("/proc/net/route").read_text().splitlines()[1:])
    except (OSError, IndexError):
        return False


def call(bus: Gio.DBusConnection, path: str, iface: str, method: str, args=None):
    try:
        return bus.call_sync(BUS, path, iface, method, args, None, Gio.DBusCallFlags.NONE, 3000, None).unpack()
    except GLib.Error:
        return None


def reachable(bus: Gio.DBusConnection, wanted: str) -> bool | None:
    """True/False si se sabe; None si kdeconnectd no está o no hay teléfono."""
    devs = call(bus, "/modules/kdeconnect", "org.kde.kdeconnect.daemon", "devices",
                GLib.Variant("(bb)", (False, True)))   # (onlyReachable, onlyPaired)
    if devs is None:
        return None
    ids = devs[0]
    dev = wanted if wanted in ids else (ids[0] if ids and not wanted else None)
    if not dev:
        return None
    v = call(bus, f"/modules/kdeconnect/devices/{dev}", "org.freedesktop.DBus.Properties", "Get",
             GLib.Variant("(ss)", ("org.kde.kdeconnect.device", "isReachable")))
    return bool(v[0]) if v is not None else None


def locked() -> bool:
    return subprocess.run(["pidof", "gtklock"], capture_output=True).returncode == 0


def main() -> None:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    armed, gone_since = False, None
    while True:
        conf = load_conf()
        if conf.get("proximity_lock") != "on":
            armed, gone_since = False, None
            time.sleep(30)
            continue
        state = reachable(bus, conf.get("proximity_device", ""))
        if state is True:
            armed, gone_since = True, None
        elif state is False and armed and has_network():
            gone_since = gone_since or time.monotonic()
            try:
                grace = max(30, int(conf.get("proximity_grace", "120")))
            except ValueError:
                grace = 120
            if time.monotonic() - gone_since >= grace:
                if not locked():
                    subprocess.run(["loginctl", "lock-session"])
                armed, gone_since = False, None
        else:
            gone_since = None   # sin datos o sin red: no cuenta como "se fue"
        time.sleep(POLL)


if __name__ == "__main__":
    main()
