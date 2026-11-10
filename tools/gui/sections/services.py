"""Services (GUI): paridad con ServicesView — los servicios de usuario conocidos (USER_SERVICES de
settings_tui.py): arrancar/parar, al iniciar sesión sí/no y sus logs. Además las unidades caídas
del sistema y del usuario, con reinicio (las del sistema por rootd) y logs."""

from __future__ import annotations

from . import _lib as L

UI: dict = {}


def unit_state(unit: str) -> tuple[bool, bool]:
    active = L.run(["systemctl", "--user", "is-active", unit]).stdout.strip() == "active"
    enabled = L.run(["systemctl", "--user", "is-enabled", unit]).stdout.strip() == "enabled"
    return active, enabled


def failed(scope: list[str]) -> list[tuple[str, str]]:
    out = []
    for ln in L.run(["systemctl", *scope, "list-units", "--state=failed", "--no-legend", "--plain", "--no-pager"]).stdout.splitlines():
        p = ln.split(None, 4)
        if p:
            out.append((p[0], p[4] if len(p) > 4 else ""))
    return out


def get() -> dict:
    rows = []
    for unit, desc in L.literal("USER_SERVICES"):
        active, enabled = unit_state(unit)
        rows.append(L.item(f"u:{unit}", unit.rsplit(".", 1)[0], sub=desc, on=active,
                           right=("● running" if active else "○ stopped") + (" · at login" if enabled else ""),
                           actions=[L.action(f"u:{unit}", "Stop" if active else "Start", active),
                                    L.action(f"en:{unit}", "Don't start at login" if enabled else "Start at login"),
                                    L.action(f"log:usr:{unit}", "Logs")]))
    groups = [L.group("User services · systemctl --user", rows)]
    for title, scope, tag in (("Failed system units", [], "sys"), ("Failed user units", ["--user"], "usr")):
        fr = [L.item(f"log:{tag}:{u}", u, sub=d, right="failed", glyph="✗",
                     actions=[L.action(f"restart:{tag}:{u}", "Restart"), L.action(f"log:{tag}:{u}", "Logs")]) for u, d in failed(scope)]
        if fr:
            groups.append(L.group(title, fr))
    return L.page("Services", "Start/stop, start at login and logs", groups, refresh=6)


def set_value(key, value):
    return L.fail("Unknown setting")


def act(key, text=None):
    op, _, rest = key.partition(":")
    if op == "u":
        active, _ = unit_state(rest)
        r = L.run(["systemctl", "--user", "stop" if active else "start", rest], timeout=30)
        return L.ok(f"{rest} {'stopped' if active else 'started'}") if r.returncode == 0 else \
            L.fail(r.stderr.strip() or f"could not {'stop' if active else 'start'} {rest}")
    if op == "en":
        _, enabled = unit_state(rest)
        r = L.run(["systemctl", "--user", "disable" if enabled else "enable", rest])
        return L.ok(f"{rest}: {'not started' if enabled else 'started'} at login") if r.returncode == 0 else \
            L.fail(r.stderr.strip() or "systemctl failed")
    tag, _, unit = rest.partition(":")
    if op == "log":
        r = L.run(["journalctl", *(["--user"] if tag == "usr" else []), "-u", unit, "-n", "200", "--no-pager"], timeout=20)
        return L.text_view(f"Logs · {unit}", r.stdout or r.stderr or "(empty)")
    if op == "restart":
        if tag == "usr":
            r = L.run(["systemctl", "--user", "restart", unit], timeout=30)
            return L.ok(f"Restarted {unit}") if r.returncode == 0 else L.fail((r.stderr or "Failed").strip()[:160])
        return L.root_ok([["systemctl", "restart", unit]], f"Restarted {unit}", timeout=60)
    return L.ok()
