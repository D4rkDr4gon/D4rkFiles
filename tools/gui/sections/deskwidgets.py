"""Desktop widgets (GUI): paridad con DeskWidgetsView — prender/apagar cada widget, zona de la
grilla 3×3 y orden dentro de la zona (con el mapa de cómo queda), presets, opciones (ciudad del
clima con geocoding de Open-Meteo, unidades, agenda Obsidian/.ics, días, pomodoro, no molestar,
teléfono de KDE Connect, IP pública), la lista de pendientes (agregar, marcar, borrar, limpiar
hechas) y arrancar el daemon. Todo va por dwlib (widgets.conf + todo.json): el daemon lo relee solo."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from . import _lib as L

UI: dict = {}
DAEMON = L.CONFIG / "desktop-widgets" / "desktop-widgets.py"
STATE: dict = {"found": [], "city": ""}
POS_ICON = {"top-left": "↖", "top": "↑", "top-right": "↗", "left": "←", "center": "•",
            "right": "→", "bottom-left": "↙", "bottom": "↓", "bottom-right": "↘"}
DESCS = {"clock": "big clock and date", "music": "player, cover, controls", "weather": "now + 3 days",
         "system": "CPU, RAM, disk, battery", "agents": "Claude / opencode usage", "status": "backup, updates, VPN, todos",
         "todo": "quick task list", "agenda": "upcoming events", "pomodoro": "focus timer",
         "phone": "KDE Connect: battery, notifications", "network": "SSID, IP, traffic graph",
         "money": "net worth, month, budget, cards (expenses TUI)"}


def DW():
    p = str(L.CONFIG / "desktop-widgets")
    if p not in sys.path:
        sys.path.insert(0, p)
    import dwlib
    return dwlib


def daemon_running() -> bool:
    return L.run(["pgrep", "-f", "[d]esktop-widgets/desktop-widgets.py"]).returncode == 0


def get() -> dict:
    dw = DW()
    conf = dw.load_conf()
    names = {w: (icon, name) for w, icon, name in dw.WIDGETS}
    pos_name = dict(dw.POSITIONS)
    running = daemon_running()
    head = [L.info("daemon", "Daemon", "● running" if running else "○ stopped")]
    if not running:
        head.append(L.button("start", "Start the daemon", "Shows the widgets on empty workspaces", "Start"))
    wrows = []
    for w in dw.order(conf):
        on = dw.enabled(conf, w)
        p = conf["pos_" + w]
        wrows.append(L.item(f"w:{w}", f"{names[w][0]}  {names[w][1]}", sub=f"{POS_ICON[p]} {pos_name[p]} · {DESCS.get(w, '')}",
                            on=on, right="● on" if on else "○ off",
                            actions=[L.action(f"w:{w}", "Turn off" if on else "Turn on"), L.action(f"pos:{w}", "Position"),
                                     L.action(f"up:{w}", "Up"), L.action(f"down:{w}", "Down")]))
    presets = [L.item(f"preset:{lid}", name, on=conf["layout"] == lid, right="● active" if conf["layout"] == lid else "",
                      actions=[] if conf["layout"] == lid else [L.action(f"preset:{lid}", "Apply")])
               for lid, name in dw.LAYOUTS]
    if conf["layout"] == "custom":
        presets.insert(0, L.info("custom", "Custom placement", "moved by hand"))
    zones = dw.placement(conf)
    grid = []
    for r in range(3):
        cells = []
        for c in range(3):
            z = dw.POS_IDS[r * 3 + c]
            cells.append(POS_ICON[z] + " " + (", ".join(names[w][1] for w in zones[z]) or "·"))
        grid.append(L.info(f"row{r}", ["Top", "Middle", "Bottom"][r], "   │   ".join(cells)))
    units = "°C · km/h" if conf["units"] != "imperial" else "°F · mph"
    opts = [L.button("city", "Weather city", (f"{conf['weather_city']} · {conf['weather_lat']}, {conf['weather_lon']}"
                                              if conf["weather_city"] else "Not set"), "Edit"),
            L.choice("units", "Units", units, conf["units"], ["metric", "imperial"]),
            L.choice("ag_source", "Agenda source", "Obsidian Full Calendar or .ics calendars",
                     "obsidian" if conf["agenda_source"] == "obsidian" else "ics", ["obsidian", "ics"])]
    if conf["agenda_source"] == "obsidian":
        opts.append(L.button("ag_vault", "Obsidian vault", conf["agenda_vault"] or "Not set", "Edit"))
    else:
        urls = conf["agenda_ics"].split()
        hosts = ", ".join(re.sub(r"^\w+://([^/]+).*", r"\1", u) if "://" in u else Path(u).name for u in urls)
        opts.append(L.button("ag_ics", ".ics calendars", f"{len(urls)}: {hosts}" if urls else "Not set", "Edit"))
    opts += [L.button("ag_days", "Agenda days ahead", conf["agenda_days"], "Edit"),
             L.button("pomo_times", "Pomodoro minutes", f"focus {conf['pomo_work']} · break {conf['pomo_short']} · "
                      f"long {conf['pomo_long']} every {conf['pomo_every']}", "Edit"),
             L.toggle("pomo_dnd", "Pomodoro: do not disturb", "During focus", conf["pomo_dnd"] == "on"),
             L.button("phone", "Phone", conf["phone_device"] or "First connected (KDE Connect)", "Choose"),
             L.toggle("net_public_ip", "Network: public IP", "api.ipify.org, every 30 min", conf["net_public_ip"] == "on")]
    items = dw.load_todo()
    todo = [L.button("todo_add", "Add task", f"{sum(not i.get('done') for i in items)} pending", "Add")]
    todo += [L.item(f"t:{i}", it["text"], sub=dw.ago(it.get("ts")), on=not it.get("done"), glyph="✓" if it.get("done") else "○",
                    actions=[L.action(f"t:{i}", "Undo" if it.get("done") else "Done"), L.action(f"tdel:{i}", "Delete", True)])
             for i, it in enumerate(items)]
    if any(i.get("done") for i in items):
        todo.append(L.button("clear_done", "Clear done tasks", "", "Clear"))
    return L.page("Desktop widgets", "Dashboard on empty workspaces · changes show up live", [
        L.group("Daemon", head), L.group("Widgets", wrows), L.group("Placement", grid), L.group("Presets", presets),
        L.group("Options", opts), L.group("Todo", todo)], refresh=5)


def set_value(key, value):
    dw = DW()
    if key == "units":
        dw.save_conf({"units": value})
    elif key == "ag_source":
        dw.save_conf({"agenda_source": value})
    elif key in ("pomo_dnd", "net_public_ip"):
        dw.save_conf({key: "on" if value else "off"})
    else:
        return L.fail("Unknown setting")
    return L.ok()


def simple_form(key: str, title: str, fields: list, numeric=(), text=None, hint="") -> dict:
    dw = DW()
    conf = dw.load_conf()
    if text is None:
        return L.form(key, title, [{"name": n, "label": lbl.upper(), "text": conf[n]} for n, lbl in fields], hint=hint)
    v = L.parse_form(text)
    bad = [lbl for n, lbl in fields if n in numeric and not v.get(n, "").strip().isdigit()]
    if bad:
        return L.form(key, title, [{"name": n, "label": lbl.upper(), "text": v.get(n, "")} for n, lbl in fields], hint=hint,
                      error=f"Must be a whole number: {', '.join(bad)}")
    dw.save_conf({n: " ".join(v.get(n, "").split()) for n, _ in fields})
    return L.ok(f"{title}: saved")


def act(key: str, text=None):
    dw = DW()
    op, _, arg = key.partition(":")
    wname = {x: n for x, _, n in dw.WIDGETS}
    if op == "start":
        if not daemon_running():
            L.detach(["python3", str(DAEMON)])
        return L.ok("Desktop widgets started")
    if op == "w":
        on = dw.enabled(dw.load_conf(), arg)
        dw.save_conf({arg: "off" if on else "on"})
        return L.ok(f"{wname[arg]}: {'off' if on else 'on'}")
    if op == "pos":
        if text is None:
            return L.form(key, f"Position of {wname[arg]}", [{"name": "pos", "label": "ZONE", "text": dw.load_conf()[f"pos_{arg}"],
                                                              "choices": [[f"{POS_ICON[p]}  {lbl}", p] for p, lbl in dw.POSITIONS]}])
        pos = L.parse_form(text).get("pos", "")
        if pos in dict(dw.POSITIONS):
            dw.set_position(arg, pos)
            return L.ok(f"{wname[arg]} → {dict(dw.POSITIONS)[pos]}")
        return L.ok()
    if op in ("up", "down"):
        step = -1 if op == "up" else 1
        return L.ok() if dw.move(arg, step) else L.ok("Already " + ("first" if step < 0 else "last") + " in its zone")
    if op == "preset":
        dw.apply_preset(arg)
        return L.ok(f"Preset: {dict(dw.LAYOUTS)[arg]}")
    if op == "city":
        if text is None:
            return L.form("city", "Weather location", [{"name": "city", "label": "CITY", "text": dw.load_conf()["weather_city"]}],
                          hint="e.g. Córdoba")
        city = L.parse_form(text).get("city", "").strip()
        if not city:
            return L.ok()
        try:
            found = dw.geocode(city)
        except Exception as e:  # noqa: BLE001 - sin red, timeout
            return L.fail(f"Lookup failed: {e}")
        if not found:
            return L.form("city", "Weather location", [{"name": "city", "label": "CITY", "text": city}],
                          error=f"No city found for “{city}”")
        STATE["found"] = found
        return L.form("citypick", "Pick the location", [{"name": "i", "label": "PLACE", "text": "0",
                                                          "choices": [[f"{g['label']} ({g['lat']}, {g['lon']})", str(i)]
                                                                      for i, g in enumerate(found)]}])
    if op == "citypick":
        try:
            g = STATE["found"][int(L.parse_form(text).get("i", "0"))]
        except (ValueError, IndexError, TypeError):
            return L.ok()
        dw.save_conf({"weather_city": g["name"], "weather_lat": g["lat"], "weather_lon": g["lon"]})
        return L.ok(f"Weather: {g['label']}")
    if op == "ag_vault":
        return simple_form(key, "Obsidian vault", [("agenda_vault", "Vault folder")], text=text,
                           hint="The vault with the Full Calendar plugin")
    if op == "ag_ics":
        return simple_form(key, ".ics calendars", [("agenda_ics", "URLs or files")], text=text,
                           hint="https://…/basic.ics  ~/cal.ics (space separated)")
    if op == "ag_days":
        return simple_form(key, "Agenda", [("agenda_days", "Days ahead")], numeric=("agenda_days",), text=text)
    if op == "pomo_times":
        return simple_form(key, "Pomodoro", [("pomo_work", "Focus (min)"), ("pomo_short", "Short break (min)"),
                                             ("pomo_long", "Long break (min)"), ("pomo_every", "Long break every N focus")],
                           numeric=("pomo_work", "pomo_short", "pomo_long", "pomo_every"), text=text)
    if op == "phone":
        if text is None:
            out = L.run(["kdeconnect-cli", "-l", "--id-name-only"]).stdout.splitlines()
            devs = [(ln.split(" ", 1)[0], ln.split(" ", 1)[1] if " " in ln else "") for ln in out if ln.strip()]
            return L.form("phone", "Phone (KDE Connect)", [{"name": "dev", "label": "DEVICE", "text": dw.load_conf()["phone_device"] or "-",
                                                            "choices": [["First connected", "-"]] + [[f"{n} ({i})", i] for i, n in devs]}])
        dev = L.parse_form(text).get("dev", "-")
        dw.save_conf({"phone_device": "" if dev == "-" else dev})
        return L.ok("Phone saved")
    if op == "todo_add":
        if text is None:
            return L.form("todo_add", "New task", [{"name": "text", "label": "TASK", "text": ""}], hint="What to do")
        t = L.parse_form(text).get("text", "").strip()
        if t:
            dw.todo_add(t)
        return L.ok()
    if op == "t":
        dw.todo_toggle(int(arg))
        return L.ok()
    if op == "tdel":
        items = dw.load_todo()
        i = int(arg)
        if i >= len(items):
            return L.ok()
        if not L.yes(text):
            return L.confirm(key, "Delete task", f"Delete “{items[i]['text']}”?", ok_label="Delete")
        dw.todo_remove(i)
        return L.ok()
    if op == "clear_done":
        dw.todo_clear_done()
        return L.ok("Cleared done tasks")
    return L.ok()
