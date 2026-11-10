"""Battery (GUI): paridad con BatteryView — batería y periféricos (upower) y el tope de carga
(charge_control_end_threshold + regla de udev para que quede al reiniciar), por el helper root."""

from __future__ import annotations

from . import _lib as L

UI: dict = {}


def T():
    return L.tui_module("battery")


def get() -> dict:
    t = T()
    paths = [p for p in L.run(["upower", "-e"]).stdout.split() if "DisplayDevice" not in p]
    groups = []
    lim = t.charge_limit()
    if lim:
        end, start, persistent = lim
        groups.append(L.group("Charge limit", [
            L.choice("limit", "Stop charging at", (f"Resumes at {start} %" if start else "") + (" · kept after reboot" if persistent and end != 100
                                                                                               else " · factory default" if end == 100 else " · until reboot"),
                     str(end), [str(v) for v, _n, _d in t.LIMITS]),
            L.info("why", "Why", " · ".join(f"{v} % {n.lower()}" for v, n, _d in t.LIMITS))]))
    for p in paths:
        b = t.upower_info(p)
        if not b["pct"] and not b["state"]:
            continue
        rows = [L.info("pct", "Charge", f"{b['pct']:.0f}% · {b['state'] or '—'}")]
        if b["kind"].startswith("battery_BAT"):
            health = b["full"] / b["design"] * 100 if b["design"] else 0
            rows += [L.info("left", "To full" if b["state"] == "charging" else "Left", (b["to_full"] if b["state"] == "charging" else b["to_empty"]) or "—"),
                     L.info("rate", "Draw", f"{b['rate']:.1f} W" if b["rate"] else "—"),
                     L.info("health", "Health", f"{health:.0f}%" if health else "—"),
                     L.info("cycles", "Cycles", b["cycles"] or "—")]
        groups.append(L.group(" ".join(x for x in (b["vendor"], b["model"]) if x) or b["kind"], rows))
    return L.page("Battery", "Health, peripherals and charge limit", groups or [L.group("Battery", [L.info("none", "No battery detected", "")])],
                  refresh=10)


def set_value(key, value):
    t = T()
    if key != "limit":
        return L.fail("Unknown setting")
    bat = t.battery_dir()
    if not bat:
        return L.fail("This battery has no configurable charge limit")
    end = int(value)
    start_f, end_f = bat / "charge_control_start_threshold", bat / "charge_control_end_threshold"
    has_start = start_f.exists()
    start = 95 if end == 100 else end - 5
    writes = [(start_f, start), (end_f, end)] if has_start else [(end_f, end)]
    if has_start and end > (t.read_int(end_f) or 100):
        writes.reverse()
    for f, v in writes:
        ok, out = L.root_run([["tee", str(f)]], input_text=f"{v}\n")
        if not ok:
            return L.fail(out[:160] or "Could not write the limit")
    if end == 100:
        ok, out = L.root_run([["rm", "-f", str(t.LIMIT_RULE)]])
    else:
        attrs = (f'ATTR{{charge_control_start_threshold}}="{start}", ' if has_start else "") + f'ATTR{{charge_control_end_threshold}}="{end}"'
        rule = ("# Generado por Settings → Battery (dotfiles): tope de carga de la batería.\n# Se borra eligiendo 100 % en Settings.\n"
                f'ACTION=="add", SUBSYSTEM=="power_supply", KERNEL=="{bat.name}", {attrs}\n')
        ok, out = L.root_run([["install", "-m644", L.root_file(rule), str(t.LIMIT_RULE)]])
    return L.ok(f"Charge limit: {end} %" + ("" if end == 100 else " (kept after reboot)")) if ok else L.fail(out[:160])


def act(key: str, text=None):
    return L.ok()
