"""Phone (GUI): paridad con PhoneView — teléfono vinculado por KDE Connect (alcanzable, batería
por D-Bus), las acciones que soporta (hacer sonar, ping, mandar el portapapeles, compartir un
archivo o un texto/URL, ver sus notificaciones, bloquearlo) y "Lock when it leaves"
(scripts/phone-proximity.py, phone/phone.conf: on/off y minutos fuera de alcance)."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import _lib as L

UI: dict = {}
STATE: dict = {"dev": None}


def T():
    return L.tui_module("phone")


def current():
    t = T()
    devs = t.devices() if shutil.which("kdeconnect-cli") else []
    dev = next((d for d in devs if d["paired"] and d["reachable"]), None) or next((d for d in devs if d["paired"]), None)
    STATE["dev"] = dev
    return dev, devs


def get() -> dict:
    t = T()
    dev, devs = current()
    if not shutil.which("kdeconnect-cli"):
        st = [L.info("none", "KDE Connect", "not installed")]
    elif not dev:
        st = [L.info("none", "No paired phone", "pair one from the KDE Connect app on the phone")]
    else:
        st = [L.info("dev", ("● " if dev["reachable"] else "○ ") + dev["name"],
                     "reachable" if dev["reachable"] else "not reachable (same network? app open?)")]
        if dev["reachable"]:
            charge = t.prop(dev["id"], "/battery", "org.kde.kdeconnect.device.battery", "charge")
            charging = t.prop(dev["id"], "/battery", "org.kde.kdeconnect.device.battery", "isCharging")
            if charge and charge.lstrip("-").isdigit() and int(charge) >= 0:
                k = max(0, min(10, round(int(charge) / 10)))
                st.append(L.info("bat", "Battery", "▓" * k + "░" * (10 - k) + f" {int(charge)}%" + ("  charging" if charging == "true" else "")))
    if devs:
        st.append(L.info("known", "Known devices", str(len(devs))))
    plugins = t.supported_plugins(dev["id"]) if dev else None
    acts = [L.button(key, name, desc, "Run") for key, name, desc, plugin in t.ACTIONS if plugins is None or plugin in plugins]
    c = t.load_conf()
    mins = int(c.get("proximity_grace", "120") or 120) / 60
    prox = [L.toggle("proximity", "󰌾  Lock when it leaves", f"Locks this computer after {mins:g} min out of reach"
                     if c.get("proximity_lock") == "on" else "Lock this computer when the phone is out of reach",
                     c.get("proximity_lock") == "on"),
            L.button("prox_mins", "Minutes out of reach", f"{mins:g} min before locking", "Edit")]
    return L.page("Phone", "KDE Connect", [L.group("Phone", st), L.group("Actions", acts), L.group("Proximity lock", prox)], refresh=15)


def proximity_form(text, enable: bool) -> dict:
    t = T()
    c = t.load_conf()
    mins = int(c.get("proximity_grace", "120") or 120) / 60
    key = "prox_on" if enable else "prox_mins"
    hint = "Only after the phone was seen in this session, never without network or with KDE Connect down."
    if text is None:
        return L.form(key, "Lock when the phone leaves", [{"name": "mins", "label": "MINUTES OUT OF REACH BEFORE LOCKING", "text": f"{mins:g}"}],
                      hint=hint)
    v = L.parse_form(text).get("mins", "").strip()
    try:
        err = "" if 0.5 <= float(v) <= 60 else "Between 0.5 and 60 minutes"
    except ValueError:
        err = "A number of minutes"
    if err:
        return L.form(key, "Lock when the phone leaves", [{"name": "mins", "label": "MINUTES OUT OF REACH BEFORE LOCKING", "text": v}],
                      hint=hint, error=err)
    upd = {"proximity_grace": str(int(float(v) * 60))}
    if enable:
        upd |= {"proximity_lock": "on", "proximity_device": STATE["dev"]["id"] if STATE["dev"] else ""}
    t.save_conf(upd)
    if c.get("proximity_lock") == "on" or enable:
        if L.run(["pgrep", "-f", "[p]hone-proximity.py"]).returncode != 0:
            L.detach([str(t.PROXIMITY)])
    return L.ok("Proximity lock on" if enable else "Saved")


def set_value(key, value):
    if key == "proximity":
        if value:
            return proximity_form(None, True)
        T().save_conf({"proximity_lock": "off"})
        return L.ok("Proximity lock off")
    return L.fail("Unknown setting")


def cli(*args, ok: str) -> dict:
    dev = STATE["dev"] or current()[0]
    if not dev or not dev["reachable"]:
        return L.fail("No reachable phone")
    r = L.run(["kdeconnect-cli", "-d", dev["id"], *args], timeout=20)
    return L.ok(ok) if r.returncode == 0 else L.fail((r.stderr or r.stdout).strip() or "kdeconnect-cli failed")


def act(key: str, text=None):
    if key in ("prox_on", "prox_mins"):
        return proximity_form(text, key == "prox_on")
    if key == "ring":
        return cli("--ring", ok="Ringing the phone")
    if key == "ping":
        return cli("--ping", ok="Ping sent")
    if key == "clip":
        return cli("--send-clipboard", ok="Clipboard sent")
    if key == "lock":
        return cli("--lock", ok="Lock requested")
    if key == "notif":
        dev = STATE["dev"] or current()[0]
        if not dev or not dev["reachable"]:
            return L.fail("No reachable phone")
        r = L.run(["kdeconnect-cli", "-d", dev["id"], "--list-notifications"], timeout=20)
        return L.text_view("Phone notifications", r.stdout.strip() or "(none)")
    if key == "file":
        fields = lambda v: [{"name": "path", "label": "FILE", "text": v}]  # noqa: E731
        if text is None:
            return L.form("file", "Share a file", fields(str(Path.home()) + "/"))
        p = Path(L.parse_form(text).get("path", "").strip()).expanduser()
        if not p.is_file():
            return L.form("file", "Share a file", fields(str(p)), error="File not found")
        return cli("--share", str(p), ok="File sent")
    if key == "text":
        if text is None:
            return L.form("text", "Share text or URL", [{"name": "text", "label": "TEXT OR URL", "text": ""}])
        v = L.parse_form(text).get("text", "")
        if not v.strip():
            return L.form("text", "Share text or URL", [{"name": "text", "label": "TEXT OR URL", "text": ""}], error="Nothing to send")
        return cli("--share-text", v, ok="Sent to the phone")
    return L.ok()
