#!/usr/bin/env python3
"""usbguard-notify — avisa cuando USBGuard bloquea un dispositivo y deja permitirlo
desde la notificación (dunst: click del medio → acciones).

Lee `usbguard watch` (IPC del daemon: el usuario tiene que estar en
IPCAllowedUsers de /etc/usbguard/usbguard-daemon.conf, lo deja así Settings →
USB guard). Acciones: permitir esta vez, permitir siempre (regla permanente) o
dejarlo bloqueado. Sin usbguard instalado sale enseguida; si el daemon se cae,
reintenta cada 30 s. Lo lanza exec-once en config/hypr/hyprland.conf.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time

ICON = "drive-removable-media-usb"


def notify(dev_id: str, rule: str) -> None:
    name = m.group(1) if (m := re.search(r'name "([^"]*)"', rule)) else ""
    vid = m.group(1) if (m := re.search(r"\bid (\S+)", rule)) else ""
    iface = m.group(1) if (m := re.search(r"with-interface (\{[^}]*\}|\S+)", rule)) else ""
    # Un "teclado" que aparece de la nada es el ataque típico (BadUSB): avisarlo
    hid = " · it says it is a KEYBOARD/HID" if re.search(r"\b03:", iface) else ""
    body = f"{name or 'Unknown device'} ({vid}){hid}\nMiddle-click to choose."
    try:
        r = subprocess.run(["notify-send", "-a", "USB guard", "-i", ICON, "-u", "critical", "--wait",
                            "-A", "once=Allow once", "-A", "always=Allow always", "-A", "block=Keep blocked",
                            "Blocked a new USB device", body], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return
    choice = r.stdout.strip()
    if choice in ("once", "always"):
        args = ["usbguard", "allow-device", dev_id] + (["-p"] if choice == "always" else [])
        ok = subprocess.run(args, capture_output=True).returncode == 0
        subprocess.run(["notify-send", "-a", "USB guard", "-i", ICON,
                        f"{name or vid}: {'allowed' if ok else 'could not allow it'}"
                        + (" (always)" if ok and choice == "always" else "")])


def watch() -> None:
    """PolicyApplied (y no PresenceChanged, que llega antes de evaluar las reglas
    con target=block para todo) con target_new=block = lo bloqueó una regla."""
    proc = subprocess.Popen(["usbguard", "watch", "-w"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True)
    event: dict = {}
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("[device] PolicyApplied:"):
            event = {"id": line.split("id=", 1)[-1].strip()}
        elif event and line.startswith(" "):
            k, _, v = line.strip().partition("=")
            event[k] = v
            if k == "rule_id":
                if event.get("target_new") == "block":
                    threading.Thread(target=notify, args=(event["id"], event.get("device_rule", "")),
                                     daemon=True).start()
                event = {}
        else:
            event = {}
    proc.wait()


def main() -> None:
    if not shutil.which("usbguard"):
        sys.exit(0)
    while True:
        watch()
        time.sleep(30)


if __name__ == "__main__":
    main()
