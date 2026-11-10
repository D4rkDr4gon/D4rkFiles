"""USB guard (GUI): paridad con UsbGuardView (settings/sections/usbguard.py).

Protección (instalar/prender/apagar, dar acceso IPC al usuario), notificador y dispositivos
conectados: permitir hasta desconectar, bloquear, permitir siempre. Leer y permitir/bloquear va
por la IPC de usbguard (el usuario está en IPCAllowedUsers: sin polkit); instalar y prender o
apagar el servicio, por el helper root de la GUI (una huella por sesión). En una red insegura,
permitir un dispositivo pide la autorización de netguard (L.unsafe_gate)."""

from __future__ import annotations

import getpass
import re

from . import _lib as L

UI: dict = {}


def T():
    return L.tui_module("usbguard")


def get() -> dict:
    t = T()
    st = t.status()
    if not st["installed"]:
        prot = L.button("prot", "Protection", "Not installed · installs it and allows everything connected now; new devices "
                        "wait for your OK", "Install")
    elif not st["active"]:
        prot = L.toggle("prot", "Protection", "Off · every USB device is allowed", False)
    elif not st["ipc"]:
        prot = L.button("prot", "Protection", f"On, but you are not in IPCAllowedUsers ({t.DAEMON_CONF})", "Fix access")
    else:
        blocked = sum(d["target"] != "allow" for d in st["devices"])
        prot = L.toggle("prot", "Protection", "New devices are blocked until you allow them"
                        + (f" · {blocked} blocked now" if blocked else ""), True)
    rows = [prot]
    if st["installed"] and st["active"]:
        rows.append(L.button("notifier", "Notifications", "Asks you when something gets blocked"
                             + (" · running" if st["notifier"] else " · stopped"), "Running" if st["notifier"] else "Start"))
    devs = []
    for d in st["devices"]:
        tgt = {"allow": "● allowed", "block": "○ blocked", "reject": "✗ rejected"}[d["target"]]
        note = " · keyboard / HID" if d["hid"] else " · hub" if d["hub"] else ""
        acts = ([L.action(f"block:{d['id']}", "Block", True)] if d["target"] == "allow" and not d["hub"] else
                [L.action(f"allow:{d['id']}", "Allow")] if d["target"] != "allow" else [])
        acts.append(L.action(f"perm:{d['id']}", "Allow always"))
        devs.append(L.item(f"dev:{d['id']}", d["name"] or "—", sub=f"{tgt} · {d['vidpid']} · port {d['port']}{note}",
                           on=d["target"] == "allow", glyph="󰕓", actions=acts))
    return L.page("USB guard", "Blocks new USB devices until you allow them (BadUSB)", [
        L.group("USB guard", rows),
        L.group("Connected devices", devs or [L.info("none", "Nothing listed", "turn protection on to list devices"
                                                    if not st.get("ipc") else "nothing connected")])], refresh=5)


def set_value(key, value):
    if key == "prot":
        return act("prot", None)
    return L.fail("Unknown setting")


def setup(user: str, install: bool) -> dict:
    t = T()
    cmds = [["pacman", "-S", "--needed", "--noconfirm", "usbguard"]] if install else []
    if cmds:
        ok, out = L.root_run(cmds, timeout=900)
        if not ok:
            return L.fail(out.splitlines()[-1][:160] if out else "Install failed")
        ok, pol = L.root_run([["usbguard", "generate-policy"]])
        if not ok:
            return L.fail("usbguard generate-policy failed")
        ok, out = L.root_run([["install", "-m600", L.root_file(pol + "\n"), t.RULES]])
        if not ok:
            return L.fail(out[:160])
    ok, conf = L.root_run([["cat", t.DAEMON_CONF]])
    if not ok:
        return L.fail(f"Can't read {t.DAEMON_CONF}")
    line = f"IPCAllowedUsers=root {user}"
    conf = re.sub(r"^IPCAllowedUsers=.*$", line, conf, flags=re.M) if re.search(r"^IPCAllowedUsers=", conf, re.M) \
        else conf.rstrip("\n") + "\n" + line + "\n"
    ok, out = L.root_run([["install", "-m600", L.root_file(conf if conf.endswith("\n") else conf + "\n"), t.DAEMON_CONF],
                          ["systemctl", "enable", "--now", "usbguard"], ["systemctl", "restart", "usbguard"]])
    if not ok:
        return L.fail(out.splitlines()[-1][:160] if out else "Setup failed")
    L.detach([str(t.NOTIFIER)])
    return L.ok("USB guard on")


def act(key: str, text=None):
    t = T()
    op, _, arg = key.partition(":")
    st = t.status()
    if op == "notifier":
        if not st.get("notifier"):
            L.detach([str(t.NOTIFIER)])
            return L.ok("Notifications started")
        return L.ok("Notifications already running")
    if op == "prot":
        user = getpass.getuser()
        if not st.get("installed") or (st.get("active") and not st.get("ipc")):
            if not L.yes(text):
                msg = ("Install USBGuard? Everything connected right now stays allowed; anything you plug in later is "
                       "blocked until you allow it from the notification or from here." if not st.get("installed")
                       else f"Give {user} access to USBGuard ({t.DAEMON_CONF})?")
                return L.confirm("prot", "USB guard", msg, danger=False, ok_label="Continue")
            return setup(user, not st.get("installed"))
        if not st.get("active"):
            ok, out = L.root_run([["systemctl", "enable", "--now", "usbguard"]])
            if ok:
                L.detach([str(t.NOTIFIER)])
            return L.ok("USB guard on") if ok else L.fail(out[:160])
        if not L.yes(text):
            return L.confirm("prot", "USB guard", "Turn it off? Every USB device will be allowed again.", ok_label="Turn off")
        return L.root_ok([["systemctl", "disable", "--now", "usbguard"]], "USB guard off: every device is allowed")
    d = next((x for x in st.get("devices", []) if x["id"] == arg), None)
    if not d:
        return L.ok()
    name = d["name"] or d["vidpid"]
    if op in ("allow", "perm") and not L.unsafe_gate():
        return L.fail("Unsafe network: authentication needed to allow USB devices")
    if op == "block" and d["hub"]:
        return L.fail("Blocking a hub cuts everything behind it: not from here")
    cmd = {"allow": ["allow-device", d["id"]], "block": ["block-device", d["id"]], "perm": ["allow-device", "-p", d["id"]]}.get(op)
    if not cmd:
        return L.ok()
    r = L.run(["usbguard", *cmd])
    if r.returncode:
        return L.fail(r.stderr.strip()[:160] or "usbguard failed")
    return L.ok(f"{name}: " + {"allow": "allowed until unplugged", "block": "blocked", "perm": "always allowed"}[op])
