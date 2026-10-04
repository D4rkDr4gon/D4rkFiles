"""Desktop widgets — el dashboard de los workspaces vacíos (config/desktop-widgets/).

Prende/apaga cada widget y elige dónde va cada uno (zona de una grilla 3×3 y
orden dentro de la zona; con un mapa de cómo queda) o aplica un preset que los
ubica a todos de una vez. También la ciudad del clima (geocoding de Open-Meteo) y maneja la lista de
pendientes. Todo va a ~/.config/dotfiles/desktop-widgets.conf (nunca a un
archivo del repo) y al todo.json de ~/.local/state/dotfiles/desktop-widgets/;
el daemon los vigila (GFileMonitor), así que los cambios se ven al instante
sin reiniciarlo. La lógica compartida con el daemon está en dwlib.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from common import DOTFILES, detach, run
from dtui import THEME, Card, ConfirmModal, DView, Field, FormModal, Panel, PickModal, Table, css
from rich import box
from rich.table import Table as RichTable
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable

sys.path.insert(0, str(DOTFILES / "config" / "desktop-widgets"))
import dwlib  # noqa: E402

DAEMON = DOTFILES / "config" / "desktop-widgets" / "desktop-widgets.py"


def daemon_running() -> bool:
    return run(["pgrep", "-f", "desktop-widgets/desktop-widgets.py"]).returncode == 0


class DeskWidgetsView(DView):
    FOCUS = "#dw-widgets"
    TABLES = ["dw-widgets", "dw-layout", "dw-opts", "dw-todo"]
    POS_ICON = {"top-left": "↖", "top": "↑", "top-right": "↗", "left": "←", "center": "•",
                "right": "→", "bottom-left": "↙", "bottom": "↓", "bottom-right": "↘"}
    DEFAULT_CSS = css("""
    #dw-left { width: 1fr; }
    #dw-right { width: 1fr; }
    #dw-widgets-panel, #dw-layout-panel, #dw-opts-panel, #dw-map-panel { height: auto; }
    #dw-widgets, #dw-layout, #dw-opts, #dw-map { height: auto; }
    #dw-todo-panel { height: 1fr; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False, description="next panel"),
        Binding("shift+tab", "cycle(-1)", show=False, description="previous panel"),
        Binding("p", "position", "position"),
        Binding("K", "move(-1)", "move up"),
        Binding("J", "move(1)", "move down"),
        Binding("a", "add", "add task"),
        Binding("d", "delete", "delete task"),
        Binding("c", "clear_done", "clear done"),
        Binding("s", "start", "start daemon"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="dw-left"):
                yield Panel(Table(id="dw-widgets"), title="\uf108  Desktop widgets", id="dw-widgets-panel")
                yield Panel(Table(id="dw-layout", show_header=False), title="Presets", id="dw-layout-panel")
                yield Panel(Card(id="dw-map"), title="Placement", id="dw-map-panel")
            with Vertical(id="dw-right"):
                yield Panel(Table(id="dw-opts", show_header=False), title="Options", id="dw-opts-panel")
                yield Panel(Table(id="dw-todo"), title="󰄲  Todo", id="dw-todo-panel")

    def on_mount(self) -> None:
        t = self.query_one("#dw-widgets", Table)
        t.add_column("", key="state", width=3)
        t.add_column("Widget", key="name", width=20)
        t.add_column("Position", key="pos", width=16)
        t.add_column("Shows", key="desc", width=36)
        self.query_one("#dw-layout", Table).add_columns("", "Layout")
        self.query_one("#dw-opts", Table).add_columns("Key", "Value")
        t = self.query_one("#dw-todo", Table)
        t.add_column("", key="state", width=3)
        t.add_column("Task", key="text", width=50)
        t.add_column("Added", key="ago", width=10)
        self.reload()
        self.set_interval(5, lambda: self.visible_now and self.reload())

    DESCS = {"clock": "big clock and date", "music": "player, cover, controls",
             "weather": "now + 3 days", "system": "CPU, RAM, disk, battery",
             "agents": "Claude / opencode usage", "status": "updates, VPN, todos",
             "todo": "quick task list", "agenda": "upcoming events", "pomodoro": "focus timer",
             "phone": "KDE Connect: battery, notifications", "network": "SSID, IP, traffic graph"}

    def reload(self) -> None:
        conf = dwlib.load_conf()
        on = lambda b: Text("●", style=THEME["status_ok"]) if b else Text("○", style=THEME["muted"])  # noqa: E731
        pos_name = dict(dwlib.POSITIONS)
        names = {w: (icon, name) for w, icon, name in dwlib.WIDGETS}
        self.query_one("#dw-widgets", Table).set_rows([
            (w, [on(dwlib.enabled(conf, w)), Text(f"{names[w][0]}  {names[w][1]}"),
                 Text(f"{self.POS_ICON[conf['pos_' + w]]} {pos_name[conf['pos_' + w]]}",
                      style="" if dwlib.enabled(conf, w) else THEME["muted"]),
                 Text(self.DESCS.get(w, ""), style=THEME["muted"])])
            for w in dwlib.order(conf)])
        self.query_one("#dw-layout", Table).set_rows([
            (lid, [on(conf["layout"] == lid), Text(name)]) for lid, name in dwlib.LAYOUTS])
        self.query_one("#dw-layout-panel").border_subtitle = (
            " custom placement " if conf["layout"] == "custom" else "")
        self.query_one("#dw-map", Card).update(self.placement_map(conf))
        self.query_one("#dw-opts", Table).set_rows(self.option_rows(conf))
        items = dwlib.load_todo()
        rows = [(str(i), [Text("✓", style=THEME["status_ok"]) if it.get("done") else Text("○", style=THEME["muted"]),
                          Text(it["text"], style=THEME["muted"] if it.get("done") else ""),
                          Text(dwlib.ago(it.get("ts")).replace(" ago", ""), style=THEME["muted"])])
                for i, it in enumerate(items)]
        self.query_one("#dw-todo", Table).set_rows(rows or [("hdr:empty", [Text(""), Text("No tasks · a to add",
                                                                                         style=THEME["muted"]), Text("")])])
        pending = sum(not i.get("done") for i in items)
        self.query_one("#dw-todo-panel").border_subtitle = f" {pending} pending "
        self.query_one("#dw-widgets-panel").border_subtitle = (
            " ● daemon running " if daemon_running() else " ○ daemon stopped · s to start ")

    def option_rows(self, conf: dict) -> list:
        """Opciones de cada widget configurable, agrupadas (hdr: = encabezado)."""
        m = THEME["muted"]
        k = lambda t: Text(t, style=m)  # noqa: E731
        units = "°C · km/h" if conf["units"] != "imperial" else "°F · mph"
        unset = Text("not set · enter to choose", style=THEME["status_warn"])
        hdr = lambda key, title: (f"hdr:{key}", [Text(title, style=f"bold {THEME['primary']}"), Text("")])  # noqa: E731
        rows = [hdr("weather", "󰖐  Weather"),
                ("city", [k("City"), Text(conf["weather_city"]) if conf["weather_city"] else unset]),
                ("coords", [k("Coordinates"), Text(f"{conf['weather_lat']}, {conf['weather_lon']}")
                            if conf["weather_lat"] else Text("—")]),
                ("units", [k("Units"), Text(f"{conf['units']} ({units})")]),
                hdr("agenda", "󰃭  Agenda")]
        obsidian = conf["agenda_source"] == "obsidian"
        rows.append(("ag_source", [k("Source"), Text("Obsidian Full Calendar" if obsidian else ".ics calendars")]))
        if obsidian:
            rows.append(("ag_vault", [k("Vault"), Text(conf["agenda_vault"]) if conf["agenda_vault"] else unset]))
        else:
            urls = conf["agenda_ics"].split()
            hosts = ", ".join(re.sub(r"^\w+://([^/]+).*", r"\1", u) if "://" in u else Path(u).name for u in urls)
            rows.append(("ag_ics", [k("Calendars"), Text(f"{len(urls)}: {hosts}") if urls else unset]))
        rows.append(("ag_days", [k("Days ahead"), Text(conf["agenda_days"])]))
        rows += [hdr("pomodoro", "󱎫  Pomodoro"),
                 ("pomo_times", [k("Minutes"), Text(f"focus {conf['pomo_work']} · break {conf['pomo_short']} · "
                                                    f"long {conf['pomo_long']} every {conf['pomo_every']}")]),
                 ("pomo_dnd", [k("Do not disturb"), Text("on during focus" if conf["pomo_dnd"] == "on" else "off")]),
                 hdr("phone", "󰏲  Phone"),
                 ("phone_device", [k("Device"), Text(conf["phone_device"] or "first connected")]),
                 hdr("network", "󰛳  Network"),
                 ("net_public_ip", [k("Public IP"), Text("on (api.ipify.org, every 30 min)"
                                                         if conf["net_public_ip"] == "on" else "off")])]
        return rows

    def placement_map(self, conf: dict) -> RichTable:
        """Grilla 3×3 con los widgets prendidos de cada zona, en orden."""
        grid = RichTable(box=box.ROUNDED, show_header=False, show_lines=True, expand=True,
                         border_style=THEME["muted"], padding=(0, 1))
        for _ in range(3):
            grid.add_column(ratio=1)
        zones = dwlib.placement(conf)
        names = {w: (icon, name) for w, icon, name in dwlib.WIDGETS}
        sel = self.query_one("#dw-widgets", Table).selected_key()
        for r in range(3):
            cells = []
            for c in range(3):
                t = Text()
                for i, w in enumerate(zones[dwlib.POS_IDS[r * 3 + c]]):
                    if i:
                        t.append("\n")
                    t.append(f"{names[w][0]} {names[w][1]}", style=f"bold {THEME['primary']}" if w == sel else "")
                if not t.plain:
                    t.append("·", style=THEME["muted"])
                cells.append(t)
            grid.add_row(*cells)
        return grid

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "dw-widgets":
            self.query_one("#dw-map", Card).update(self.placement_map(dwlib.load_conf()))

    # ── Foco y atajos ──
    def focused_table(self) -> str:
        f = self.app.focused
        return f.id if isinstance(f, Table) and f.id in self.TABLES else "dw-widgets"

    def action_cycle(self, step: int) -> None:
        i = self.TABLES.index(self.focused_table())
        self.query_one(f"#{self.TABLES[(i + step) % len(self.TABLES)]}", Table).focus()

    def hints(self) -> list[tuple[str, str]]:
        tid = self.focused_table()
        h = {"dw-widgets": [("enter", "on/off"), ("p", "position"), ("K", "up"), ("J", "down")],
             "dw-layout": [("enter", "apply preset")],
             "dw-opts": [("enter", "edit / toggle")],
             "dw-todo": [("a", "add"), ("enter", "done"), ("d", "delete"), ("c", "clear done")]}[tid]
        if not daemon_running():
            h.append(("s", "start daemon"))
        return h + [("tab", "panel"), ("q", "quit")]

    # ── Acciones ──
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tid, key = event.data_table.id, event.row_key.value
        if tid == "dw-widgets":
            on = dwlib.enabled(dwlib.load_conf(), key)
            dwlib.save_conf({key: "off" if on else "on"})
            self.app.notify_ok(f"{dict((w, n) for w, _, n in dwlib.WIDGETS)[key]}: {'off' if on else 'on'}")
        elif tid == "dw-layout":
            dwlib.apply_preset(key)
            self.app.notify_ok(f"Preset: {dict(dwlib.LAYOUTS)[key]}")
        elif tid == "dw-opts":
            self.edit_option(key)
        elif tid == "dw-todo" and key.isdigit():
            dwlib.todo_toggle(int(key))
        else:
            return
        self.reload()

    def action_position(self) -> None:
        if self.focused_table() != "dw-widgets":
            return
        w = self.query_one("#dw-widgets", Table).selected_key()
        if not w:
            return
        name = {x: n for x, _, n in dwlib.WIDGETS}[w]
        cur = dwlib.load_conf()[f"pos_{w}"]

        def chosen(pos):
            if pos:
                dwlib.set_position(w, pos)
                self.app.notify_ok(f"{name} → {dict(dwlib.POSITIONS)[pos]}")
                self.reload()
        rows = [(p, [Text(self.POS_ICON[p]), Text(label, style=f"bold {THEME['primary']}" if p == cur else "")])
                for p, label in dwlib.POSITIONS]
        self.app.push_screen(PickModal(f"Position of {name}", ["", "Zone"], rows), chosen)

    def action_move(self, step: int) -> None:
        if self.focused_table() != "dw-widgets":
            return
        t = self.query_one("#dw-widgets", Table)
        w = t.selected_key()
        if w and dwlib.move(w, step):
            self.reload()
        elif w:
            self.app.notify_ok("Already " + ("first" if step < 0 else "last") + " in its zone")

    def edit_option(self, key: str) -> None:
        conf = dwlib.load_conf()
        toggles = {"units": ("units", "metric", "imperial"), "pomo_dnd": ("pomo_dnd", "off", "on"),
                   "net_public_ip": ("net_public_ip", "off", "on"),
                   "ag_source": ("agenda_source", "obsidian", "ics")}
        if key in toggles:
            ck, a, b = toggles[key]
            val = b if conf[ck] == a else a
            dwlib.save_conf({ck: val})
            self.app.notify_ok(f"{ck}: {val}")
        elif key in ("city", "coords"):
            self.edit_city()
        elif key == "ag_vault":
            self.form("Obsidian vault", [Field("agenda_vault", "Vault folder", conf["agenda_vault"], paths=True)],
                      hint="the vault with the Full Calendar plugin · enter save")
        elif key == "ag_ics":
            self.form(".ics calendars", [Field("agenda_ics", "URLs or files", conf["agenda_ics"],
                                               placeholder="https://…/basic.ics  ~/cal.ics (space separated)")])
        elif key == "ag_days":
            self.form("Agenda", [Field("agenda_days", "Days ahead", conf["agenda_days"])], numeric=("agenda_days",))
        elif key == "pomo_times":
            self.form("Pomodoro", [Field("pomo_work", "Focus (min)", conf["pomo_work"]),
                                   Field("pomo_short", "Short break (min)", conf["pomo_short"]),
                                   Field("pomo_long", "Long break (min)", conf["pomo_long"]),
                                   Field("pomo_every", "Long break every N focus", conf["pomo_every"])],
                      numeric=("pomo_work", "pomo_short", "pomo_long", "pomo_every"))
        elif key == "phone_device":
            self.pick_phone()
        self.reload()

    def form(self, title: str, fields: list, hint: str = "enter save · esc cancel", numeric=()) -> None:
        def validate(vals):
            bad = [f.label for f in fields if f.key in numeric and not vals.get(f.key, "").strip().isdigit()]
            return f"Must be a whole number: {', '.join(bad)}" if bad else None

        def done(vals):
            if vals is not None:
                dwlib.save_conf({k: " ".join(v.split()) for k, v in vals.items()})
                self.app.notify_ok(f"{title}: saved")
                self.reload()
        self.app.push_screen(FormModal(title, fields, hint=hint, validate=validate, enter_advances=len(fields) > 1),
                             done)

    def pick_phone(self) -> None:
        out = run(["kdeconnect-cli", "-l", "--id-name-only"]).stdout.splitlines()
        devs = [(line.split(" ", 1)[0], line.split(" ", 1)[1] if " " in line else "") for line in out if line.strip()]

        def chosen(dev):
            if dev is not None:
                dwlib.save_conf({"phone_device": "" if dev == "-" else dev})
                self.reload()
        self.app.push_screen(PickModal("Phone (KDE Connect)", ["Device", "Id"],
                                       [("-", ["First connected", ""])] + [(i, [n, i]) for i, n in devs]), chosen)

    def edit_city(self) -> None:
        conf = dwlib.load_conf()

        def done(vals):
            if vals and vals.get("city", "").strip():
                self.app.notify_ok("Looking up city…")
                self.lookup(vals["city"].strip())
        self.app.push_screen(FormModal("Weather location", [Field("city", "City", conf["weather_city"],
                                                                    placeholder="e.g. Madrid")],
                                       hint="enter search · esc cancel"), done)

    @work(thread=True, exclusive=True, group="dw-geocode")
    def lookup(self, city: str) -> None:
        try:
            found = dwlib.geocode(city)
        except Exception as e:  # noqa: BLE001 - sin red, timeout, etc.
            self.app.call_from_thread(self.app.notify_err, f"Lookup failed: {e}")
            return
        self.app.call_from_thread(self.pick_city, city, found)

    def pick_city(self, city: str, found: list[dict]) -> None:
        if not found:
            self.app.notify_err(f"No city found for “{city}”")
            return

        def chosen(key):
            if key is None:
                return
            g = found[int(key)]
            dwlib.save_conf({"weather_city": g["name"], "weather_lat": g["lat"], "weather_lon": g["lon"]})
            self.app.notify_ok(f"Weather: {g['label']}")
            self.reload()
        self.app.push_screen(PickModal("Pick the location", ["Place", "Coordinates"],
                                       [(str(i), [g["label"], f"{g['lat']}, {g['lon']}"]) for i, g in enumerate(found)]),
                             chosen)

    def action_add(self) -> None:
        def done(vals):
            if vals and vals.get("text", "").strip():
                dwlib.todo_add(vals["text"])
                self.reload()
        self.app.push_screen(FormModal("New task", [Field("text", "Task", placeholder="what to do")]), done)

    def selected_todo(self) -> int | None:
        if self.focused_table() != "dw-todo":
            return None
        key = self.query_one("#dw-todo", Table).selected_key()
        return int(key) if key and key.isdigit() else None

    def action_delete(self) -> None:
        idx = self.selected_todo()
        if idx is None:
            return
        text = dwlib.load_todo()[idx]["text"]

        def yes(ok: bool = True):
            if ok:
                dwlib.todo_remove(idx)
                self.reload()
        self.app.push_screen(ConfirmModal("Delete task", f"Delete “{text}”?"), yes)

    def action_clear_done(self) -> None:
        dwlib.todo_clear_done()
        self.app.notify_ok("Cleared done tasks")
        self.reload()

    def action_start(self) -> None:
        if daemon_running():
            self.app.notify_ok("Daemon already running")
            return
        detach(["python3", str(DAEMON)])
        self.app.notify_ok("Desktop widgets started")
        self.set_timer(1.5, self.reload)
