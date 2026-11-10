"""Workspaces (GUI): paridad con WorkspacesView — cantidad (1–10, genera hypr/workspaces.conf y
recarga Hyprland para rearmar los atajos; ofrece mover las ventanas que queden en workspaces
deshabilitados), lista para ir a cada uno y la sesión (guardar, restaurar, autosave, restaurar al
iniciar sesión; hypr/scripts/hypr-session.py)."""

from __future__ import annotations

from . import _lib as L

UI: dict = {}
STATE: dict = {"draft": None, "stranded": []}


def T():
    return L.tui_module("workspaces")


def get() -> dict:
    t = T()
    saved = t.ws_count()
    draft = STATE["draft"] or saved
    info, active, clients = t.hypr_state()
    count = [L.slider("count", "Workspaces", f"Super+1…{draft % 10 if draft == 10 else draft} go · Super+Shift+N move window · "
                      f"Ctrl+Tab cycles 1–{draft}", draft, t.MIN_WS, t.MAX_WS, 1)]
    if draft != saved:
        count.append(L.button("apply", f"Apply {draft} workspaces", f"Changed from {saved} · reloads Hyprland keybinds and waybar", "Apply"))
    rows = []
    for i in range(1, draft + 1):
        w = info.get(i, {})
        rows.append(L.item(f"go:{i}", f"Workspace {i}" + ("  ●" if i == active else ""), sub=f"Super+{i % 10}"
                           + (f" · {w.get('windows', 0)} windows · {w.get('lastwindowtitle', '')[:60]}" if w else " · empty"),
                           on=i == active, glyph="󰍹"))
    for i in sorted(w for w in info if w > draft):
        w = info[i]
        rows.append(L.item(f"go:{i}", f"Workspace {i}", sub=f"disabled · {w.get('windows', 0)} windows · {w.get('lastwindowtitle', '')[:60]}",
                           glyph="󰍺"))
    se = t.session_status()
    conf = se.get("conf", {})
    mins = max(1, int(conf.get("interval", "120") or 120) // 60)
    sess = [L.button("save", "Save now", (f"{se['count']} windows on workspaces {', '.join(map(str, se['workspaces']))}"
                                          if se.get("count") else "Nothing saved yet"), "Save"),
            L.button("restore", "Restore", "Reopen what was saved and is not open, each on its workspace", "Restore"),
            L.toggle("autosave", "Autosave", f"Every {mins} min, when something changed", conf.get("autosave") == "on"),
            L.toggle("login", "Restore at login", "Reopen the last session when you log in", conf.get("restore_on_login") == "on")]
    return L.page("Workspaces", "How many workspaces Super+N and the bar use", [
        L.group("Count", count), L.group("Workspaces", rows), L.group("Session", sess)], refresh=5)


def save(n: int) -> dict:
    t = T()
    t.write_ws_conf(n)
    L.run(["hyprctl", "reload"])
    errors = L.run(["hyprctl", "configerrors"]).stdout.strip()
    STATE["draft"] = None
    if errors and "no errors" not in errors.lower():
        return L.fail(f"Hyprland reported config errors: {errors.splitlines()[0]}")
    return L.ok(f"{n} workspaces enabled · keybinds and waybar updated")


def set_value(key, value):
    t = T()
    if key == "count":
        STATE["draft"] = max(t.MIN_WS, min(t.MAX_WS, int(float(value))))
        return L.ok()
    if key == "autosave":
        t.session_set("autosave", "on" if value else "off")
        return L.ok()
    if key == "login":
        t.session_set("restore_on_login", "on" if value else "off")
        return L.ok()
    return L.fail("Unknown setting")


def act(key: str, text=None):
    t = T()
    op, _, arg = key.partition(":")
    if op == "apply":
        n = STATE["draft"] or t.ws_count()
        if text is not None:
            if L.parse_form(text).get("move") == "yes":
                for c in STATE["stranded"]:
                    L.run([t.HYPR_DISPATCH, "movetoworkspacesilent", f"{n},address:{c['address']}"])
            return save(n)
        _info, _active, clients = t.hypr_state()
        stranded = [c for c in clients if c.get("workspace", {}).get("id", 0) > n]
        if not stranded:
            return save(n)
        STATE["stranded"] = stranded
        names = "\n".join(f"  {c.get('class', '?')} — {c.get('title', '')[:50]} (ws {c['workspace']['id']})" for c in stranded[:8]) \
            + (f"\n  … +{len(stranded) - 8}" if len(stranded) > 8 else "")
        r = L.form("apply", f"Use {n} workspaces", [{"name": "move", "label": f"MOVE THEM TO WORKSPACE {n}?", "text": "yes",
                                                      "choices": [["Move them", "yes"], ["Leave them (reachable from the overview)", "no"]]}],
                   ok_label="Apply")
        r["ask"]["message"] = f"{len(stranded)} window(s) are on workspaces above {n}:\n{names}"
        return r
    if op == "go":
        L.run([t.HYPR_DISPATCH, "workspace", arg])
        return {"ok": True, "msg": "", "close": True}
    if op == "save":
        out = L.run(["python3", str(t.SESSION_PY), "save"]).stdout.strip()
        return L.ok(out.capitalize() or "Saved")
    if op == "restore":
        if not t.session_status().get("count"):
            return L.fail("Nothing saved yet")
        L.detach(["python3", str(t.SESSION_PY), "restore"])
        return L.ok("Restoring: windows open on their workspaces")
    return L.ok()
