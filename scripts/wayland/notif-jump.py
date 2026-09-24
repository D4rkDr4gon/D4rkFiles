#!/usr/bin/env python3
"""Click del medio en una notificación -> saltar a la ventana de la app.

dunst no puede correr un script al hacer click, pero con
`mouse_middle_click = do_action, close_current` invoca la acción de la
notificación y emite la señal D-Bus `ActionInvoked(id, key)` hacia la app.
Esa señal es unicast, así que se escucha con `dbus-monitor` (modo monitor).

La ventana se busca en dos pasos:
1. Por PID: la señal va dirigida a la conexión D-Bus de la app que mandó la
   notificación; su PID (GetConnectionUnixProcessID) identifica la ventana
   exacta. Así se distinguen las webapps de FirefoxPWA (clase FFPWA-..., pero
   notifican como appname "Firefox") del Firefox normal.
2. Fallback por nombre: el log id -> app que escribe
   config/dunst/scripts/notif-record.sh (regla [notif_jump_record]), matcheado
   contra class/initialClass (p. ej. apps Flatpak, que notifican vía portal).
Se enfoca con `hyprctl dispatch focuswindow`, que cambia de workspace.

Solo Hyprland. Notificaciones sin acciones (p. ej. notify-send pelado) no
emiten ActionInvoked: para esas el click del medio solo la cierra.
"""

import json
import os
import re
import subprocess
import sys

LOG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "dunst-notif-apps.tsv")
MATCH = "type='signal',interface='org.freedesktop.Notifications',member='ActionInvoked'"


def app_for(notif_id):
    try:
        with open(LOG) as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        parts = line.split("\t")
        if parts[0] == str(notif_id):
            return [p for p in parts[1:] if p]
    return None


def norm(s):
    return s.lower().removesuffix(".desktop")


def find_window(names):
    wanted = {norm(n) for n in names}
    matches = []
    for c in clients():
        classes = {norm(c.get("class", "")), norm(c.get("initialClass", ""))} - {""}
        # Coincidencia exacta, o por la última parte del reverse-DNS
        # (org.telegram.desktop -> telegram / desktop entry "firefox").
        tails = {cl.split(".")[-1] for cl in classes} | {
            cl.split(".")[-2] for cl in classes if cl.count(".") >= 1
        }
        if wanted & classes or wanted & tails:
            matches.append(c)
    return most_recent(matches)


def pid_of(bus_name):
    out = subprocess.run(
        ["busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
         "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s", bus_name],
        capture_output=True, text=True,
    ).stdout.split()
    return int(out[1]) if len(out) == 2 and out[1].isdigit() else None


def ancestors(pid):
    """pid y sus padres (la ventana puede ser de un proceso padre)."""
    chain = []
    while pid and pid > 1 and len(chain) < 10:
        chain.append(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return chain


def clients():
    out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except ValueError:
        return []


def most_recent(cands):
    return min(cands, key=lambda c: c.get("focusHistoryID", 1e9), default=None)


def window_by_pid(bus_name):
    pid = pid_of(bus_name)
    if not pid:
        return None
    cs = clients()
    for p in ancestors(pid):
        win = most_recent([c for c in cs if c.get("pid") == p])
        if win:
            return win
    return None


def main():
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        sys.exit("notif-jump: solo funciona en Hyprland")
    proc = subprocess.Popen(
        ["dbus-monitor", "--session", MATCH], stdout=subprocess.PIPE, text=True, bufsize=1
    )
    dest = None
    for line in proc.stdout:
        if "member=ActionInvoked" in line:
            m = re.search(r"destination=(\S+)", line)
            dest = m.group(1) if m else ""
            continue
        if dest is not None:
            m = re.search(r"uint32 (\d+)", line)
            bus_name, dest = dest, None
            if not m:
                continue
            win = window_by_pid(bus_name) if bus_name.startswith(":") else None
            if not win:
                names = app_for(m.group(1))
                win = find_window(names) if names else None
            if win:
                subprocess.run(
                    ["hyprctl", "dispatch", "focuswindow", f"address:{win['address']}"],
                    capture_output=True,
                )


if __name__ == "__main__":
    main()
