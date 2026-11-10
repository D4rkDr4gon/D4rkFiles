"""Notifications (GUI): paridad con NotificationsView — historial de dunst (leer el mensaje
completo, borrar todo), No molestar (scripts/dnd.sh: on/off, 1 h, 2 h, hasta mañana 08:00, tiempo a
medida, silenciar apps puntuales y agregar apps del historial o por nombre) y modo foco
(scripts/focus-mode.sh)."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta

from . import _lib as L

UI: dict = {}
DND = str(L.DOTFILES / "scripts" / "dnd.sh")
FOCUS = str(L.DOTFILES / "scripts" / "focus-mode.sh")
STATE: dict = {"items": []}


def dnd_state() -> dict:
    try:
        return json.loads(L.run(["bash", DND, "--status"]).stdout)
    except ValueError:
        return {"active": False, "remaining": "", "apps": []}


def history() -> list:
    try:
        data = json.loads(L.run(["dunstctl", "history"]).stdout or "{}").get("data", [[]])[0]
    except (ValueError, IndexError):
        data = []
    items = [{k: (n.get(k) or {}).get("data", "") for k in ("id", "appname", "summary", "body")} for n in data]
    for n in items:
        for k in ("summary", "body"):
            n[k] = re.sub(r"<[^>]+>", "", html.unescape(html.unescape(str(n[k]))))
    STATE["items"] = items
    return items


def get() -> dict:
    st = dnd_state()
    focus = L.run(["bash", FOCUS, "status"]).returncode == 0
    dnd = [L.toggle("dnd", "Do Not Disturb", (f"On · turns off in {st['remaining']}" if st.get("remaining") else "On until turned off")
                    if st.get("active") else "Silence popups", bool(st.get("active"))),
           L.toggle("focus", "Focus mode", "Do Not Disturb + hides music, weather, phone and money widgets", focus),
           L.button("t:3600", "⏱  On for 1 hour", "", "Start"), L.button("t:7200", "⏱  On for 2 hours", "", "Start"),
           L.button("t:morning", "⏱  On until tomorrow 08:00", "", "Start"),
           L.button("t:custom", "⏱  On for a custom time…", "Hours, e.g. 3 or 1.5", "Set")]
    apps = [L.toggle(f"app:{a['app']}", f"Silence {a['app']}", "silenced" if a["enabled"] else "allowed", a["enabled"])
            for a in st.get("apps", [])]
    apps.append(L.button("add", "Silence an app…", "From the history or by name", "Add"))
    items = history()
    q = (UI.get("search") or "").lower()
    hist = [L.item(f"n:{n['id']}", n["summary"] or n["appname"] or "(no title)", sub=" ".join(n["body"].split())[:110],
                   right=n["appname"]) for n in items
            if not q or q in (n["appname"] + n["summary"] + n["body"]).lower()]
    head = [L.button("clear", "Clear history", f"{len(items)} in history", "Clear all", danger=True)] if items else []
    p = L.page("Notifications", "History, Do Not Disturb and focus mode", [
        L.group("Do Not Disturb", dnd), L.group("Silenced apps", apps),
        L.group("History", head + (hist or [L.info("empty", "History is empty", "")]))], refresh=5)
    p["search"] = "Filter the history…"
    return p


def dnd_cmd(*args, msg="") -> dict:
    L.run(["bash", DND, *args])
    return L.ok(msg)


def set_value(key: str, value):
    if key == "dnd":
        return dnd_cmd("--on" if value else "--off", msg="Do Not Disturb on" if value else "Do Not Disturb off")
    if key == "focus":
        L.run(["bash", FOCUS, "toggle"])
        return L.ok("Focus mode on" if value else "Focus mode off")
    if key.startswith("app:"):
        return dnd_cmd("--app-toggle", key[4:])
    return L.fail("Unknown setting")


def act(key: str, text=None):
    op, _, arg = key.partition(":")
    if op == "n":
        n = next((n for n in STATE["items"] if str(n["id"]) == arg), None)
        return L.text_view(n["appname"] or "Notification", f"{n['summary']}\n\n{n['body']}".strip()) if n else L.ok()
    if op == "clear":
        if not L.yes(text):
            return L.confirm("clear", "Clear history", "Delete every notification in the history?", ok_label="Clear")
        L.run(["dunstctl", "history-clear"])
        return L.ok("History cleared")
    if op == "t":
        if arg in ("3600", "7200"):
            return dnd_cmd("--timer", arg, msg=f"Do Not Disturb for {int(arg) // 3600} h")
        if arg == "morning":
            now = datetime.now()
            target = now.replace(hour=8, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return dnd_cmd("--timer", str(int((target - now).total_seconds())), msg="Do Not Disturb until 08:00")
        fields = lambda v: [{"name": "hours", "label": "HOURS", "text": v}]  # noqa: E731
        if text is None:
            return L.form(key, "Do Not Disturb for…", fields(""), hint="e.g. 3 or 1.5")
        h = L.parse_form(text).get("hours", "").strip()
        try:
            err = "" if float(h) > 0 else "Must be greater than 0"
        except ValueError:
            err = "Hours must be a number (e.g. 3 or 1.5)"
        if err:
            return L.form(key, "Do Not Disturb for…", fields(h), error=err)
        return dnd_cmd("--timer", str(int(float(h) * 3600)), msg=f"Do Not Disturb for {h} h")
    if op == "add":
        silenced = {a["app"] for a in dnd_state().get("apps", [])}
        seen = sorted({n["appname"] for n in STATE["items"] if n["appname"] and n["appname"] not in silenced})
        fields = lambda pick, name: [{"name": "pick", "label": "APP FROM THE HISTORY", "text": pick,  # noqa: E731
                                      "choices": [["Type a name below", "-"]] + [[a, a] for a in seen]},
                                     {"name": "name", "label": "OR TYPE ITS NAME", "text": name}]
        if text is None:
            return L.form("add", "Silence an app", fields(seen[0] if seen else "-", ""), hint="e.g. Discord")
        v = L.parse_form(text)
        app = v.get("name", "").strip() if v.get("pick", "-") == "-" else v["pick"]
        if not app:
            return L.form("add", "Silence an app", fields("-", ""), error="The name is missing")
        return dnd_cmd("--app-add", app, msg=f"{app} silenced")
    return L.ok()
