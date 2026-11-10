"""Power (GUI): paridad con PowerView — batería, perfil de energía, brillo (pantalla y teclado),
acciones por inactividad (hypridle: on/off y minutos; genera hypr/hypridle.conf) y sesión
(bloquear, suspender, cerrar sesión, reiniciar, apagar)."""

from __future__ import annotations

from . import _lib as L

UI: dict = {}


def T():
    return L.tui_module("power")


def get() -> dict:
    t = T()
    b = t.battery()
    if b:
        charging = b["state"] in ("charging", "fully-charged")
        left = "plugged in" if b["state"] == "fully-charged" else (b["to_full"] if b["state"] == "charging" else b["to_empty"]) or "—"
        health = b["full"] / b["design"] * 100 if b["design"] else 0
        bat = [L.info("pct", "Charge", f"{b['pct']:.0f}% · {'󰂄 ' if charging else ''}{b['state']}"),
               L.info("left", "To full" if b["state"] == "charging" else "Left", left),
               L.info("rate", "Draw", f"{b['rate']:.1f} W" if b["rate"] else "—"),
               L.info("health", "Health", (f"{health:.0f}%" if health else "—")
                      + (f" · {b['cycles']} cycles" if b["cycles"] and b["cycles"] not in ("0", "N/A") else ""))]
    else:
        bat = [L.info("none", "Battery", "no battery (desktop or not reported by upower)")]
    cur = L.run(["powerprofilesctl", "get"]).stdout.strip()
    prof = [L.item(f"profile:{p}", p, sub=desc, glyph=icon, on=p == cur, right="● active" if p == cur else "",
                   actions=[] if p == cur else [L.action(f"profile:{p}", "Use")]) for p, icon, desc in t.PROFILES]
    bright = [L.slider(f"bright:{d['name']}", "Screen" if d["kind"] == "screen" else "Keyboard", d["name"],
                       d["cur"] if d["kind"] == "keyboard" and d["max"] <= 5 else d["pct"],
                       0, d["max"] if d["kind"] == "keyboard" and d["max"] <= 5 else 100, 1 if d["kind"] == "keyboard" and d["max"] <= 5 else 5)
              for d in t.brightness_devices()] or [L.info("none", "Brightness", "no backlight found (brightnessctl)")]
    st, on = t.idle_settings(), t.idle_active()
    idle = [L.toggle("idle", "Idle actions", "hypridle · lock should come before turning the screen off", on)]
    idle += [L.slider(f"idle:{k}", name, "Minutes · 0 = never", st[k], 0, 120, 1) for k, _icon, name in t.IDLE_ITEMS]
    sess = [L.button(f"session:{k}", name, "Asks to confirm" if c else "", name, danger=c) for k, _i, name, c in t.SESSION]
    return L.page("Power", "Battery, profile, brightness, idle and session", [
        L.group("Battery", bat), L.group("Power profile", prof), L.group("Brightness", bright),
        L.group("Idle actions", idle), L.group("Session", sess)], refresh=10)


def set_value(key, value):
    t = T()
    op, _, arg = key.partition(":")
    if op == "bright":
        d = next((x for x in t.brightness_devices() if x["name"] == arg), None)
        if not d:
            return L.fail("Device not found")
        val = str(int(value)) if d["kind"] == "keyboard" and d["max"] <= 5 else f"{int(value)}%"
        r = L.run(["brightnessctl", "-d", arg, "set", val])
        return L.ok() if r.returncode == 0 else L.fail(r.stderr.strip()[:120])
    if key == "idle":
        if value:
            if not t.IDLE_CONF.exists():
                t.write_idle_conf(t.idle_settings())
            L.run(["systemctl", "--user", "enable", "--now", t.IDLE_UNIT])
            return L.ok("Idle actions on")
        L.run(["systemctl", "--user", "disable", "--now", t.IDLE_UNIT])
        return L.ok("Idle actions off")
    if op == "idle":
        st = t.idle_settings()
        st[arg] = max(0, min(600, int(value)))
        t.write_idle_conf(st)
        if t.idle_active():
            L.run(["systemctl", "--user", "restart", t.IDLE_UNIT])
        return L.ok()
    return L.fail("Unknown setting")


def act(key: str, text=None):
    t = T()
    op, _, arg = key.partition(":")
    if op == "profile":
        r = L.run(["powerprofilesctl", "set", arg])
        return L.ok(f"Profile: {arg}") if r.returncode == 0 else L.fail(r.stderr.strip()[:120])
    if op == "session":
        name, confirm = next((n, c) for k, _i, n, c in t.SESSION if k == arg)
        if confirm and not L.yes(text):
            return L.confirm(key, name, f"{name} now? Unsaved work in open apps will be lost.", ok_label=name)
        if arg == "lock":
            L.detach(["loginctl", "lock-session"])
        elif arg == "suspend":
            L.detach(["systemctl", "suspend"])
        elif arg == "logout":
            L.detach([str(L.CONFIG / "hypr" / "scripts" / "hypr-dispatch"), "exit"])
        else:
            r = L.run(["systemctl", arg])
            if r.returncode != 0:
                ok, out = L.root_run([["systemctl", arg]])
                if not ok:
                    return L.fail(out[:160])
        return {"ok": True, "msg": "", "close": True}
    return L.ok()
