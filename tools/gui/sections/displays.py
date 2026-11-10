"""Displays (GUI): paridad con DisplaysView — monitores, luz nocturna (hyprsunset) y la tablet
como monitor (wayvnc). Monitores: lo que informa Hyprland y hyprmon (TUI de terceros) en una
kitty para reacomodarlos. Luz nocturna: prender/apagar, temperatura y brillo en vivo (sliders),
horario y arranque al iniciar sesión. Tablet: wayvnc on/off."""

from __future__ import annotations

import shutil
import time
from datetime import datetime

from . import _lib as L

UI: dict = {}


def T():
    return L.tui_module("displays")


def NL():
    T()
    import nightlight
    return nightlight


def get() -> dict:
    t, nl = T(), NL()
    mons = t.monitors()
    mrows = [L.item(f"mon:{m['name']}", ("● " if m.get("focused") else "") + m["name"],
                    sub=f"{m['width']}×{m['height']} @ {m['refreshRate']:.0f} Hz · scale {m['scale']:g} · at {m['x']},{m['y']}"
                    + (f" · rotated {m['transform'] * 90}°" if m.get("transform") else "") + f" · {m.get('description', '')}"[:60],
                    glyph="󰍹", on=bool(m.get("focused"))) for m in mons]
    mrows.append(L.button("hyprmon", "Arrange monitors", "Opens hyprmon (position, resolution, scale)", "Open"))
    n = t.night_state()
    if not n["installed"]:
        night = [L.button("install-night", "Night light", "hyprsunset is not installed", "Install")]
    else:
        cfg = n["cfg"]
        state = "on" if n["on"] else "off" if n["running"] else "not running"
        night = [L.toggle("night", "Night light", f"Now {state} · until the next scheduled change", n["on"]),
                 L.slider("temp", "Temperature", "Lower = warmer", int(cfg["temperature"]), t.TEMP_MIN, t.TEMP_MAX, t.TEMP_STEP),
                 L.slider("gamma", "Brightness", "At night (%)", int(cfg["gamma"]), t.GAMMA_MIN, 100, t.GAMMA_STEP),
                 L.button("schedule", "Schedule", (f"Night {cfg['from']} → {cfg['to']} · now {datetime.now():%H:%M}"
                                                   if cfg["schedule"] == "on" else "Off · only when turned on by hand"), "Edit"),
                 L.toggle("login", "Start at login", "hyprsunset user service", n["login"])]
    on, ip = t.tablet_state()
    tab = [L.toggle("tablet", "Tablet as monitor", f"On · connect the tablet's VNC app to {ip or '<your IP>:5900'}" if on
                    else "Extends the desktop to the tablet (wayvnc, output VNC-1)", on)]
    return L.page("Displays", "Monitors, night light and tablet", [L.group("Monitors", mrows), L.group("Night light", night),
                                                                    L.group("Tablet", tab)], refresh=5)


def adjust(key: str, value) -> dict:
    t, nl = T(), NL()
    n = t.night_state()
    if not n["installed"]:
        return L.fail("hyprsunset is not installed")
    n["cfg"][key] = str(int(value))
    nl.write_conf(n["cfg"])
    if n["running"]:
        nl.ipc("temperature", n["cfg"]["temperature"])
        nl.ipc("gamma", n["cfg"]["gamma"])
    return L.ok()


def set_value(key, value):
    t, nl = T(), NL()
    if key == "temp":
        return adjust("temperature", value)
    if key == "gamma":
        return adjust("gamma", value)
    if key == "night":
        n = t.night_state()
        cfg = n["cfg"]
        if not n["running"]:
            if not nl.CONF.exists():
                nl.write_conf(cfg)
            r = L.run(["systemctl", "--user", "enable", "--now", nl.UNIT])
            if r.returncode != 0:
                return L.fail(r.stderr.strip() or "could not start hyprsunset")
            time.sleep(0.5)
            return L.ok("Night light started (follows the schedule)")
        if not value:
            nl.ipc("identity")
            nl.ipc("gamma", "100")
            return L.ok("Night light off (until the next scheduled change)")
        nl.ipc("temperature", cfg["temperature"])
        nl.ipc("gamma", cfg["gamma"])
        return L.ok("Night light on (until the next scheduled change)")
    if key == "login":
        r = L.run(["systemctl", "--user", "enable" if value else "disable", nl.UNIT])
        return L.ok("Starts at login" if value else "Won't start at login") if r.returncode == 0 else L.fail(r.stderr.strip()[:120])
    if key == "tablet":
        r = L.run(["bash", str(t.WAYVNC), "on" if value else "off"], timeout=20)
        if r.returncode:
            out = (r.stderr or r.stdout).strip().splitlines()
            return L.fail(out[-1] if out else "wayvnc failed")
        return L.ok("Tablet monitor on: connect from the tablet" if value else "Tablet monitor off")
    return L.fail("Unknown setting")


def act(key: str, text=None):
    t, nl = T(), NL()
    if key == "hyprmon":
        if not shutil.which("hyprmon"):
            return L.fail("hyprmon is not installed")
        L.detach(["kitty", "--class", "hyprmon", "--title", "Monitors", "-e", "hyprmon"])
        return L.ok()
    if key == "install-night":
        return L.root_ok([["pacman", "-S", "--needed", "--noconfirm", "hyprsunset"]], "hyprsunset installed", timeout=600)
    if key == "schedule":
        cfg = t.night_state()["cfg"]
        fields = lambda v: [{"name": "schedule", "label": "AUTOMATIC SCHEDULE", "text": v["schedule"], "choices": ["on", "off"]},  # noqa: E731
                            {"name": "from", "label": "NIGHT STARTS AT", "text": v["from"]},
                            {"name": "to", "label": "NIGHT ENDS AT", "text": v["to"]}]
        if text is None:
            return L.form("schedule", "Night light schedule", fields(cfg), hint="HH:MM, e.g. 21:00 → 07:30")
        v = L.parse_form(text)
        if not nl.TIME_RE.match(v.get("from", "")) or not nl.TIME_RE.match(v.get("to", "")):
            return L.form("schedule", "Night light schedule", fields(v), error="Times go as HH:MM (e.g. 21:00)")
        nl.write_conf(dict(cfg) | {k: v[k].strip() for k in ("schedule", "from", "to")})
        if nl.running():
            L.run(["systemctl", "--user", "restart", nl.UNIT])
        return L.ok("Schedule saved")
    return L.ok()
