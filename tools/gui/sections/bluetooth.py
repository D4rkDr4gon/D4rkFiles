"""Bluetooth (GUI): paridad con BluetoothView — adaptador (on/off, nombre, visible, conectados,
buscando), dispositivos agrupados (conectados, emparejados, disponibles) con ícono, batería y
estado; conectar (empareja y confía si hace falta), desconectar, confiar/desconfiar, olvidar (con
confirmación), buscar 12 s en segundo plano y bluetui en una kitty. En red insegura, conectar o
abrir bluetui pide la misma autenticación que la TUI (L.unsafe_gate, por rootd)."""

from __future__ import annotations

import re
import shutil
import subprocess
import threading

from . import _lib as L

UI: dict = {}
STATE: dict = {"busy": ""}
BT_ICONS = {"audio-headset": "󰋋", "audio-headphones": "󰋋", "audio-card": "󰓃", "input-keyboard": "󰌌",
            "input-mouse": "󰍽", "input-gaming": "󰊴", "input-tablet": "󰓶", "phone": "󰏲", "computer": "󰟀",
            "video-display": "󰔂", "multimedia-player": "󰐌", "printer": "󰐪", "camera-photo": "󰄀"}


def field(out: str, k: str) -> str:
    m = re.search(rf"^\s*{k}: (.*)$", out, re.M)
    return m.group(1).strip() if m else ""


def bt_info(mac: str) -> dict:
    out = L.run(["bluetoothctl", "info", mac]).stdout
    battery = re.search(r"Battery Percentage: 0x[0-9a-f]+ \((\d+)\)", out)
    return {"mac": mac, "name": field(out, "Name") or field(out, "Alias") or mac, "icon": field(out, "Icon"),
            "paired": field(out, "Paired") == "yes", "trusted": field(out, "Trusted") == "yes",
            "connected": field(out, "Connected") == "yes", "battery": int(battery.group(1)) if battery else None}


def devices() -> list[dict]:
    macs = [ln.split()[1] for ln in L.run(["bluetoothctl", "devices"]).stdout.splitlines() if ln.startswith("Device ")]
    return [bt_info(m) for m in macs]


def get() -> dict:
    show = L.run(["bluetoothctl", "show"]).stdout
    present, powered = bool(show.strip()), field(show, "Powered") == "yes"
    devs = devices() if powered else []
    if not present:
        st = L.info("st", "Bluetooth", "○ no Bluetooth adapter found")
    elif not powered:
        st = L.info("st", "Bluetooth", "○ off")
    else:
        conn = sum(d["connected"] for d in devs)
        st = L.info("st", f"● On · {field(show, 'Name') or field(show, 'Alias')}",
                    f"{'visible to others' if field(show, 'Discoverable') == 'yes' else 'hidden'} · {conn} connected"
                    + (" · scanning…" if field(show, "Discovering") == "yes" else ""))
    ctl = [st, L.toggle("power", "Bluetooth", "Turn the adapter on or off", powered)]
    if STATE["busy"]:
        ctl.append(L.info("busy", "Working", STATE["busy"]))
    if powered:
        ctl.append(L.button("scan", "Scan", "12 s · put the device in pairing mode", "…" if STATE["busy"].startswith("scan") else "Scan"))
    if shutil.which("bluetui"):
        ctl.append(L.button("bluetui", "Open bluetui", "The Bluetooth TUI, in a terminal", "Open"))
    groups = [L.group("Bluetooth", ctl)]
    for label, ds in (("Connected", [d for d in devs if d["connected"]]),
                      ("Paired", [d for d in devs if d["paired"] and not d["connected"]]),
                      ("Available", [d for d in devs if not d["paired"] and not d["connected"]])):
        rows = []
        for d in sorted(ds, key=lambda d: d["name"].lower()):
            state = "● connected" if d["connected"] else "○ paired" if d["paired"] else "not paired"
            acts = [L.action(f"c:{d['mac']}", "Disconnect" if d["connected"] else ("Connect" if d["paired"] else "Pair"))]
            if d["paired"]:
                acts.append(L.action(f"trust:{d['mac']}", "Untrust" if d["trusted"] else "Trust"))
                acts.append(L.action(f"forget:{d['mac']}", "Forget", True))
            rows.append(L.item(f"c:{d['mac']}", d["name"], sub=state + (" · trusted" if d["trusted"] else "") + f" · {d['mac']}",
                               right=f"{d['battery']}%" if d["battery"] is not None else "", glyph=BT_ICONS.get(d["icon"], "󰂯"),
                               on=d["connected"], actions=acts))
        if rows:
            groups.append(L.group(label, rows))
    return L.page("Bluetooth", f"{len(devs)} known devices" if powered else "Bluetooth off", groups, refresh=2 if STATE["busy"] else 5)


def set_value(key: str, value):
    if key == "power":
        L.run(["bluetoothctl", "power", "on" if value else "off"])
        return L.ok("Bluetooth " + ("on" if value else "off"))
    return L.fail("Unknown setting")


def scan() -> None:
    STATE["busy"] = "scanning for 12 s… put the device in pairing mode"
    try:
        subprocess.run(["bluetoothctl", "--timeout", "12", "scan", "on"], capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        pass
    finally:
        STATE["busy"] = ""


def toggle(d: dict) -> dict:
    if d["connected"]:
        r = L.run(["bluetoothctl", "disconnect", d["mac"]], timeout=15)
        ok = f"{d['name']} disconnected"
    else:
        if not L.unsafe_gate():
            return L.fail("Unsafe network: authentication needed to connect Bluetooth devices")
        if not d["paired"]:
            r = L.run(["bluetoothctl", "--timeout", "20", "pair", d["mac"]], timeout=30)
            if "Pairing successful" not in r.stdout and "AlreadyExists" not in r.stdout:
                return L.fail(f"Could not pair {d['name']}")
            L.run(["bluetoothctl", "trust", d["mac"]])
        r = L.run(["bluetoothctl", "--timeout", "15", "connect", d["mac"]], timeout=25)
        ok = f"{d['name']} connected"
    if r.returncode == 0 and "Failed" not in r.stdout:
        return L.ok(ok)
    err = (r.stdout or r.stderr).strip().splitlines()
    return L.fail(f"{d['name']}: {err[-1] if err else 'failed'}")


def act(key: str, text=None):
    op, _, mac = key.partition(":")
    if op == "scan":
        if not STATE["busy"]:
            threading.Thread(target=scan, daemon=True).start()
        return L.ok("Scanning for 12 s…")
    if op == "bluetui":
        if not L.unsafe_gate():
            return L.fail("Unsafe network: authentication needed to open bluetui")
        L.detach(["kitty", "--class", "bluetui", "--title", "Bluetooth", "-e", "bluetui"])
        return L.ok()
    if not re.fullmatch(r"[0-9A-Fa-f:]{17}", mac):
        return L.ok()
    d = bt_info(mac)
    if op == "c":
        STATE["busy"] = f"{'disconnecting' if d['connected'] else 'connecting'} {d['name']}…"
        try:
            return toggle(d)
        finally:
            STATE["busy"] = ""
    if op == "trust":
        L.run(["bluetoothctl", "untrust" if d["trusted"] else "trust", mac])
        return L.ok(f"{d['name']} {'untrusted' if d['trusted'] else 'trusted'}")
    if op == "forget":
        if not L.yes(text):
            return L.confirm(key, "Forget device", f"Forget {d['name']}? You'll have to pair it again.", ok_label="Forget")
        L.run(["bluetoothctl", "remove", mac])
        return L.ok(f"{d['name']} forgotten")
    return L.ok()
