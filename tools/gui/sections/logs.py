"""Logs (GUI): paridad con LogsView — errores (o errores + warnings) del journal de este arranque
o del anterior, unidades fallidas, filtro por unidad o texto (búsqueda de la página), mensaje
completo y el journal entero del arranque en lnav (en una kitty)."""

from __future__ import annotations

import json
import shutil
import time

from . import _lib as L

UI: dict = {}
STATE: dict = {"level": 3, "boot": 0, "entries": []}


def load() -> list:
    r = L.run(["journalctl", "-b", str(-STATE["boot"]) if STATE["boot"] else "0", "-p", str(STATE["level"]), "-o", "json", "--no-pager",
               "-n", "500"], timeout=20)
    entries = []
    for line in r.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        msg = e.get("MESSAGE") or ""
        if isinstance(msg, list):
            msg = bytes(msg).decode(errors="replace")
        ts = int(e.get("__REALTIME_TIMESTAMP", 0)) / 1e6
        entries.append({"time": time.strftime("%d/%m %H:%M:%S", time.localtime(ts)),
                        "unit": e.get("_SYSTEMD_UNIT") or e.get("SYSLOG_IDENTIFIER") or e.get("_COMM", "?"),
                        "prio": int(e.get("PRIORITY", 6)), "msg": str(msg)})
    return list(reversed(entries))


def get() -> dict:
    STATE["entries"] = load()
    q = (UI.get("search") or "").strip().lower()
    failed = [ln.split()[0] for ln in L.run(["systemctl", "--failed", "--no-legend", "--plain"]).stdout.split("\n") if ln.strip()]
    failed_user = [ln.split()[0] for ln in L.run(["systemctl", "--user", "--failed", "--no-legend", "--plain"]).stdout.split("\n") if ln.strip()]
    fl = [L.info(f"f{i}", "✗ " + u, "system") for i, u in enumerate(failed)] + \
         [L.info(f"fu{i}", "✗ " + u, "user") for i, u in enumerate(failed_user)]
    opts = [L.choice("level", "Show", "Priority", "errors" if STATE["level"] == 3 else "errors + warnings", ["errors", "errors + warnings"]),
            L.choice("boot", "Boot", "Which boot", "this boot" if not STATE["boot"] else "previous boot", ["this boot", "previous boot"]),
            L.button("lnav", "Open in lnav", "Whole journal of this boot: filters, search, SQL, timeline", "Open")]
    rows = [L.item(f"e:{i}", " ".join(e["msg"].split())[:140] or "(empty)", sub=f"{e['time']} · {e['unit']}", on=e["prio"] > 3,
                   glyph="✗" if e["prio"] <= 3 else "⚠") for i, e in enumerate(STATE["entries"])
            if not q or q in e["unit"].lower() or q in e["msg"].lower()]
    p = L.page("Logs", f"{len(rows)} {'errors' if STATE['level'] == 3 else 'errors + warnings'} · "
               f"{'this boot' if not STATE['boot'] else 'previous boot'}", [
                   L.group("Journal", opts), L.group("Failed units", fl or [L.info("ok", "No failed units", "✓")]),
                   L.group("Entries", rows or [L.info("none", "Nothing", "✓")])], refresh=15)
    p["search"] = "Filter by unit or text…"
    return p


def set_value(key, value):
    if key == "level":
        STATE["level"] = 3 if value == "errors" else 4
    elif key == "boot":
        STATE["boot"] = 0 if value == "this boot" else 1
    return L.ok()


def act(key: str, text=None):
    op, _, arg = key.partition(":")
    if op == "e":
        try:
            e = STATE["entries"][int(arg)]
        except (IndexError, ValueError):
            return L.ok()
        return L.text_view(f"{e['unit']} · {e['time']}", e["msg"])
    if op == "lnav":
        if not shutil.which("lnav"):
            return L.fail("lnav is not installed (sudo pacman -S lnav)")
        boot = f"-b {-STATE['boot']}" if STATE["boot"] else "-b"
        L.detach(["kitty", "--title", "Journal", "-e", "sh", "-c", f"journalctl {boot} -o short-iso --no-pager | lnav"])
        return L.ok()
    return L.ok()
