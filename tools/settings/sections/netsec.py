"""Network security — endurecimiento de red, sobre netguard (https://github.com/D4rkDr4gon/netguard, opcional en
D4rkFiles). Cuatro páginas (tab o 1-4):

1 Hardening  opciones del daemon (DNS cifrado, IPv6 y autoconexión en redes inseguras, evil twin, aviso de puertos),
             archivos de sistema (sysctl de red, privacidad de MAC/IPv6) y access points aprendidos.
2 Ports      qué escucha fuera de loopback y si la red puede alcanzarlo.
3 Apps       firewall por aplicación con OpenSnitch: reglas de apps y sitios desde listas dinámicas.
4 History    el historial de redes.

Sin lógica propia: lee con `netguard … --json` y cambia con sus comandos (ngapi.py), igual que su CLI y su TUI.
Bajar la protección lo autentica netguard (agente de polkit); lo que usa sudo se corre en la terminal.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

import ngapi
from dtui import THEME, Card, ConfirmModal, DView, Field, FormModal, Panel, PickModal, Table, TextModal, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import ContentSwitcher, DataTable, Static

PAGES = [("hard", "Hardening"), ("ports", "Ports"), ("apps", "App firewall"), ("hist", "History")]
OPTS = ("dns", "ipv6_unsafe", "autoconnect_unsafe", "ap_check", "ports_warn")
NAMES = {"dns": "Encrypted DNS", "ipv6_unsafe": "IPv6 on unsafe networks", "autoconnect_unsafe": "Autoconnect unsafe networks",
         "ap_check": "Fake network detection", "ports_warn": "Open ports warning"}
BEST = {"dns": "strict", "ipv6_unsafe": "off", "autoconnect_unsafe": "off", "ap_check": "on", "ports_warn": "on"}
DOMAIN_RE = re.compile(r"[a-z0-9.-]+\.[a-z]{2,}")
TABLES = {"hard": "#ns-hard", "ports": "#ns-ports", "apps": "#ns-apps", "hist": "#ns-hist"}


class NetSecView(DView):
    FOCUS = "#ns-hard"
    DEFAULT_CSS = css("""
    #ns-tabs { height: 1; padding: 0 1; }
    #ns-pages { height: 1fr; }
    #ns-apps-state-panel { height: auto; }
    #ns-apps-panel { height: 1fr; }
    """)
    BINDINGS = [
        Binding("1", "page('hard')", "hardening", show=False),
        Binding("2", "page('ports')", "ports", show=False),
        Binding("3", "page('apps')", "app firewall", show=False),
        Binding("4", "page('hist')", "history", show=False),
        Binding("tab", "next_page(1)", "next page", show=False),
        Binding("shift+tab", "next_page(-1)", "previous page", show=False),
        Binding("a", "add_app", "add app rule"),
        Binding("s", "add_site", "add site rule"),
        Binding("x", "flip", "allow/deny"),
        Binding("d", "delete", "delete"),
        Binding("A", "apply_rules", "apply rules"),
        Binding("D", "default_action", "default action"),
        Binding("r", "reload", "reload"),
        Binding("c", "clear_history", "clear history"),
    ]
    page = "hard"

    def compose(self) -> ComposeResult:
        yield Static(id="ns-tabs")
        with ContentSwitcher(initial="hard", id="ns-pages"):
            with Vertical(id="hard"):
                yield Panel(Table(id="ns-hard", show_header=False), title="󰒃  Network hardening", id="ns-hard-panel")
            with Vertical(id="ports"):
                yield Panel(Table(id="ns-ports"), title="󰛳  Listening ports", id="ns-ports-panel")
            with Vertical(id="apps"):
                yield Panel(Card(id="ns-apps-state"), title="󰒃  OpenSnitch", id="ns-apps-state-panel")
                yield Panel(Table(id="ns-apps"), title="Rules", id="ns-apps-panel")
            with Vertical(id="hist"):
                yield Panel(Table(id="ns-hist"), title="󰋚  Network history", id="ns-hist-panel")

    def on_mount(self) -> None:
        h = self.query_one("#ns-hard", Table)
        h.add_column("", key="name", width=32)
        h.add_column("", key="state", width=22)
        h.add_column("", key="desc", width=90)
        p = self.query_one("#ns-ports", Table)
        for key, label, w in (("proto", "Proto", 6), ("port", "Port", 7), ("addr", "Address", 22),
                              ("proc", "Process", 18), ("unit", "Unit", 34), ("st", "Exposed?", 40)):
            p.add_column(label, key=key, width=w)
        a = self.query_one("#ns-apps", Table)
        for key, label, w in (("on", "", 2), ("action", "Action", 7), ("app", "App", 44), ("site", "Site", 30),
                              ("st", "", 14)):
            a.add_column(label, key=key, width=w)
        t = self.query_one("#ns-hist", Table)
        for key, label, w in (("t", "When", 17), ("ev", "Event", 16), ("d", "Detail", 110)):
            t.add_column(label, key=key, width=w)
        self.data: dict = {}
        self.render_tabs()
        self.action_reload()
        self.set_interval(5, self.tick)

    def tick(self) -> None:
        if self.visible_now and self.page in ("hard", "ports", "hist"):
            self.action_reload()

    # ── páginas ──

    def render_tabs(self) -> None:
        t = Text()
        for i, (pid, label) in enumerate(PAGES, 1):
            on = pid == self.page
            t.append(f" {i} {label} ", style=f"bold reverse {THEME['primary']}" if on else THEME["muted"])
            t.append("  ")
        self.query_one("#ns-tabs", Static).update(t)

    def action_page(self, name: str) -> None:
        self.page = name
        self.query_one("#ns-pages", ContentSwitcher).current = name
        self.render_tabs()
        self.query_one(TABLES[name], Table).focus()
        self.action_reload()
        self.update_hints()

    def action_next_page(self, step: int) -> None:
        ids = [p for p, _ in PAGES]
        self.action_page(ids[(ids.index(self.page) + step) % len(ids)])

    def action_reload(self) -> None:
        self.load(self.page)

    def hints(self) -> list[tuple[str, str]]:
        base = [("tab", "page"), ("1-4", "jump"), ("q", "quit")]
        if not ngapi.available():
            return [("enter", "install netguard")] + base
        return {"hard": [("enter", "change")], "ports": [("enter", "details / stop"), ("r", "refresh")],
                "apps": [("a", "app rule"), ("s", "site rule"), ("enter", "on/off"), ("x", "allow/deny"),
                         ("d", "delete"), ("A", "apply"), ("D", "default")],
                "hist": [("enter", "details"), ("c", "clear")]}[self.page] + base

    # ── datos (siempre por la CLI de netguard) ──

    @work(thread=True, exclusive=True, group="ns-load")
    def load(self, page: str) -> None:
        d: dict = {"available": ngapi.available()}
        if d["available"]:
            if page == "hard":
                d.update(config=ngapi.read("config", "list") or [], harden=ngapi.read("harden") or {},
                         aps=ngapi.read("ap", "list") or [], status=ngapi.read("status") or {})
            elif page == "ports":
                d["ports"] = ngapi.read("ports") or []
            elif page == "apps":
                d.update(apps=ngapi.read("apps", "status") or {}, rules=ngapi.read("apps", "list") or [])
            else:
                d["hist"] = ngapi.read("history", "-n", "800") or []
        self.app.call_from_thread(self.show, page, d)

    def show(self, page: str, d: dict) -> None:
        self.data = d
        if not d["available"]:
            muted, warn = THEME["muted"], THEME["status_warn"]
            t = self.query_one(TABLES[page], Table)
            cells = [Text("󰒃  Install netguard", style="bold"), Text("○ not installed", style=warn),
                     Text("optional in D4rkFiles · enter installs it (git + makepkg, then setup)", style=muted)]
            t.set_rows([("install", (cells + [""] * len(t.columns))[:len(t.columns)])])
            return
        getattr(self, f"show_{page}")(d)

    @work(thread=True, exclusive=True, group="ns-call")
    def ng_call(self, args: list[str], ok_msg: str = "") -> None:
        ok, msg = ngapi.call(*args)
        if ok:
            self.app.call_from_thread(self.app.notify_ok, ok_msg or msg or "done")
        else:
            self.app.call_from_thread(self.app.notify_err, msg or "netguard refused it")
        self.app.call_from_thread(self.action_reload)

    def term(self, args: list[str], title: str) -> None:
        ngapi.term(self.app, args, title)
        self.action_reload()

    def install(self) -> None:
        def done(yes: bool) -> None:
            if yes and ngapi.install(self.app, setup=True):
                self.app.notify_ok("netguard installed and set up")
            self.action_reload()
        self.app.push_screen(ConfirmModal("Install netguard", "Downloads the pinned version of netguard, builds it with "
                                          "makepkg (sudo) and runs its setup.\nSee Settings → Firewall → Zones."), done)

    # ── 1 · Hardening ──

    def show_hard(self, d: dict) -> None:
        ok, warn, muted, err = THEME["status_ok"], THEME["status_warn"], THEME["muted"], THEME["status_error"]
        conf = {o["key"]: o for o in d["config"]}
        rows = [("hdr:daemon", [Text("APPLIED PER CONNECTION BY NETGUARD", style=f"bold {THEME['primary']}"), "", ""])]
        for key in OPTS:
            o = conf.get(key)
            if not o:
                continue
            good = o["value"] == BEST[key]
            rows.append((f"opt:{key}", [f"  {NAMES[key]}", Text(("● " if good else "○ ") + o["value"],
                                                               style=ok if good else warn), Text(o["help"], style=muted)]))
        n = sum(len(a["bssids"]) for a in d["aps"])
        rows.append(("aps", ["  Known access points", Text(f"{n} in {len(d['aps'])} networks", style=muted),
                             Text("learned the first time on each trusted Wi-Fi · enter to forget one", style=muted)]))
        if d["status"].get("config", {}).get("enabled") != "on":
            rows.append(("zones-off", ["  ⚠ Network zones are off", Text("", style=err),
                                       Text("these only apply while netguard runs: Settings → Firewall → Zones",
                                            style=warn)]))
        rows.append(("hdr:sys", [Text("SYSTEM (installed once, sudo)", style=f"bold {THEME['primary']}"), "", ""]))
        h = d["harden"]
        rows.append(("sysctl", ["  Kernel network hardening", self.file_state(h.get("sysctl", "")),
                                Text("no ICMP redirects or source routing, loose rp_filter, martians logged, SYN cookies",
                                     style=muted)]))
        rows.append(("privacy", ["  MAC & IPv6 privacy", self.file_state(h.get("privacy", "")),
                                 Text("one MAC per network (stable on each), random MAC while scanning, temporary IPv6"
                                      + (" · Wi-Fi MAC via iwd" if h.get("iwd") != "n/a" else ""), style=muted)]))
        self.query_one("#ns-hard", Table).set_rows(rows)
        self.query_one("#ns-hard-panel").border_subtitle = " enter changes · lowering protection asks for fingerprint "

    def file_state(self, st: str) -> Text:
        return {"ours": Text("● installed", style=THEME["status_ok"]),
                "old": Text("◐ outdated", style=THEME["status_warn"]),
                "other": Text("◐ custom file", style=THEME["status_warn"])}.get(st, Text("○ not installed",
                                                                                         style=THEME["muted"]))

    def hard_selected(self, key: str) -> None:
        if key.startswith("opt:"):
            return self.change_opt(key[4:])
        if key == "aps":
            return self.forget_ap()
        if key in ("sysctl", "privacy"):
            on = self.data.get("harden", {}).get(key) != "ours"
            title = ("Install " if on else "Remove ") + ("kernel network hardening" if key == "sysctl"
                                                         else "MAC & IPv6 privacy")
            msg = ("Runs `netguard harden " + key + (" on" if on else " off") + "` (sudo)."
                   + ("\nTakes effect on the next connection; Wi-Fi reconnects if iwd restarts.\nIf your router "
                      "reserves an IP by MAC, update it." if key == "privacy" and on else ""))
            self.app.push_screen(ConfirmModal(title, msg), lambda yes: self.term(
                ["harden", key, "on" if on else "off", "-y"], title) if yes else None)

    def change_opt(self, key: str) -> None:
        o = next((o for o in self.data.get("config", []) if o["key"] == key), None)
        if not o:
            return
        values = o["choices"] or [BEST[key], "on" if BEST[key] == "off" else "off"]
        rows = [(v, [("● " if v == o["value"] else "  ") + v]) for v in values]
        self.app.push_screen(PickModal(NAMES[key], ["Value"], rows), lambda v: self.ng_call(
            ["config", "set", key, v], f"{NAMES[key]}: {v} (netguard applies it in a few seconds)")
            if v and v != o["value"] else None)

    def forget_ap(self) -> None:
        rows = [(f"{a['uuid']}|{b}", [a["name"] or a["uuid"][:8], b, a["security"]]) for a in self.data.get("aps", [])
                for b in a["bssids"]]
        if not rows:
            return self.app.notify_ok("No access points learned yet")

        def done(k: Optional[str]) -> None:
            if k:
                uuid, bssid = k.split("|")
                self.ng_call(["ap", "forget", uuid, bssid], f"Forgot {bssid} (it will be asked again)")
        self.app.push_screen(PickModal("Forget an access point", ["Network", "BSSID", "Security"], rows), done)

    # ── 2 · Ports ──

    def show_ports(self, d: dict) -> None:
        ok, err, muted = THEME["status_ok"], THEME["status_error"], THEME["muted"]
        rows = []
        self.port_rows = {}
        for p in d["ports"]:
            exp = p["exposure"]
            style = ok if exp.startswith("blocked") else err if exp.startswith("REACH") else muted
            key = f"{p['proto']}:{p['port']}"
            self.port_rows[key] = p
            rows.append((key, [p["proto"], str(p["port"]), p["addr"], p["proc"] or Text("(root)", style=muted),
                               Text(p["unit"], style=muted), Text(exp, style=style)]))
        self.query_one("#ns-ports", Table).set_rows(rows)
        self.query_one("#ns-ports-panel").border_subtitle = (f" {len(rows)} listening outside loopback " if rows
                                                             else " ✓ nothing listens outside loopback ")

    def port_selected(self, key: str) -> None:
        p = getattr(self, "port_rows", {}).get(key)
        if not p:
            return
        unit = p["unit"]
        info = (f"{p['proto']}/{p['port']} on {p['addr']}\nprocess: {p['proc'] or '(not visible: runs as root)'} "
                f"pid {p['pid'] or '?'}\nunit: {unit or '?'}\n{p['exposure']}")
        if unit.endswith(".service") and not unit.startswith(("user@", "app-", "dbus-:")):
            return self.app.push_screen(ConfirmModal(f"Stop {unit}?", info + "\n\nStops it and disables it at boot "
                                                     "(sudo). Undo: systemctl enable --now " + unit),
                                        lambda yes: self.term(["ports", "--stop", unit, "-y"], f"Stop {unit}") if yes
                                        else None)
        self.app.push_screen(TextModal(f"Port {p['port']}", info + "\n\nNot a system service: close the app that "
                                       "opened it.", end=False))

    # ── 3 · App firewall (OpenSnitch) ──

    def show_apps(self, d: dict) -> None:
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]
        st = d["apps"]
        t = Text()
        if not st.get("installed"):
            t.append("○ OpenSnitch is not installed", style=warn)
            t.append("  · enter on the row below installs it (sudo pacman -S opensnitch)\n", style=muted)
        else:
            t.append("● opensnitchd running" if st.get("active") else "○ opensnitchd stopped",
                     style=ok if st.get("active") else err)
            t.append(f"   default for unmatched connections: {st.get('default')}", style=muted)
            if st.get("default") != st.get("pending_default"):
                t.append(f"  (pending: {st.get('pending_default')}, A applies)", style=warn)
            t.append("\n")
        t.append("Rules are built from apps using the network now, installed apps and the sites in your Firefox "
                 "history. Escape hatch: sudo systemctl stop opensnitchd", style=muted)
        self.query_one("#ns-apps-state", Card).update(t)
        rows = []
        if not st.get("installed"):
            rows.append(("os-install", [Text("+", style=THEME["primary"]), "", Text("Install OpenSnitch", style="bold"),
                                        Text("sudo, once", style=muted), ""]))
        for r in d["rules"]:
            on = r.get("enabled", True)
            rows.append((r["id"], [Text("●" if on else "○", style=ok if on else muted),
                                   Text(r["action"], style=ok if r["action"] == "allow" else err),
                                   r.get("app") or Text("any app", style=muted),
                                   r.get("site") or Text("any site", style=muted), ""]))
        self.query_one("#ns-apps", Table).set_rows(rows)
        self.query_one("#ns-apps-panel").border_subtitle = f" {len(d['rules'])} rules · A writes them (sudo) "

    def rule_selected(self, key: str) -> None:
        if key == "os-install":
            return self.app.push_screen(ConfirmModal("Install OpenSnitch", "Installs opensnitch and starts opensnitchd "
                                                     "(sudo).\nUnmatched connections stay ALLOWED until you change the "
                                                     "default (D)."),
                                        lambda yes: self.term(["apps", "install"], "Install OpenSnitch") if yes else None)
        r = next((r for r in self.data.get("rules", []) if r["id"] == key), None)
        if r:
            self.ng_call(["apps", "disable" if r.get("enabled", True) else "enable", key])

    def action_add_app(self) -> None:
        if self.page == "apps" and ngapi.available():
            self.suggest("apps", self.pick_app)

    def action_add_site(self) -> None:
        if self.page == "apps" and ngapi.available():
            self.suggest("sites", self.pick_site)

    @work(thread=True, exclusive=True, group="ns-pick")
    def suggest(self, kind: str, then: Callable) -> None:
        self.app.call_from_thread(then, ngapi.read("apps", "suggest", kind, timeout=40) or [])

    def pick_app(self, items: list) -> None:
        muted, primary = THEME["muted"], THEME["primary"]
        rows = [("manual", [Text("✎ Type a path…", style=primary), ""])]
        for source, title in (("network now", "USING THE NETWORK NOW"), ("installed", "INSTALLED APPS")):
            rows.append((f"hdr:{source}", [Text(title, style=f"bold {primary}"), ""]))
            rows += [(f"p:{i['app']}", [i["name"], Text(i["app"], style=muted)]) for i in items if i["source"] == source]

        def done(k: Optional[str]) -> None:
            if k and not k.startswith("hdr:"):
                self.rule_form("app", "" if k == "manual" else k[2:])
        self.app.push_screen(PickModal("App rule · pick an app", ["App", "Executable"], rows), done)

    def pick_site(self, items: list) -> None:
        rows = [("manual", [Text("✎ Type a domain…", style=THEME["primary"]), ""])]
        if items:
            rows.append(("hdr:ff", [Text("FROM FIREFOX (history and bookmarks)", style=f"bold {THEME['primary']}"), ""]))
            rows += [(f"s:{i['site']}", [i["site"], Text(f"{i['weight']} visits" if i["weight"] > 1 else "bookmark/known",
                                                         style=THEME["muted"])]) for i in items]

        def done(k: Optional[str]) -> None:
            if k and not k.startswith("hdr:"):
                self.rule_form("site", "" if k == "manual" else k[2:])
        self.app.push_screen(PickModal("Site rule · pick a site", ["Site", ""], rows), done)

    def rule_form(self, kind: str, value: str) -> None:
        def check(v: dict) -> Optional[str]:
            if kind == "app" and not v["main"].startswith("/"):
                return "Full path of the executable (e.g. /usr/lib/firefox/firefox)"
            if kind == "site" and not DOMAIN_RE.fullmatch(v["main"].lower()):
                return "A domain like example.com (subdomains included)"
            if v["scope"] and kind == "app" and not DOMAIN_RE.fullmatch(v["scope"].lower()):
                return "Site: a domain like example.com"
            if v["scope"] and kind == "site" and not v["scope"].startswith("/"):
                return "App: full path of the executable, or empty for every app"
            return None

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            args = ["apps", f"add-{kind}", v["main"]] + (["--allow"] if v["action"] == "allow" else [])
            if v["scope"]:
                args += ["--site" if kind == "app" else "--app", v["scope"]]
            self.ng_call(args, "Rule added · A applies it")

        main_label = "Executable" if kind == "app" else "Domain (and its subdomains)"
        scope_label = "Only for this site (empty = any)" if kind == "app" else "Only for this app (empty = every app)"
        self.app.push_screen(FormModal(f"{kind.capitalize()} rule", [
            Field("main", main_label, value, paths=kind == "app", files=kind == "app"),
            Field("action", "Action", "deny", choices=[("deny: block it", "deny"), ("allow: always let it through", "allow")]),
            Field("scope", scope_label, "", paths=kind == "site", files=kind == "site")], validate=check), done)

    def selected_rule(self) -> Optional[str]:
        k = self.query_one("#ns-apps", Table).selected_key()
        return k if k and k not in ("os-install", "install") else None

    def action_flip(self) -> None:
        if self.page == "apps" and (k := self.selected_rule()):
            self.ng_call(["apps", "flip", k])

    def action_delete(self) -> None:
        if self.page == "apps" and (k := self.selected_rule()):
            self.ng_call(["apps", "remove", k], "Rule deleted · A applies it")

    def action_default_action(self) -> None:
        if self.page != "apps" or not ngapi.available():
            return
        if self.data.get("apps", {}).get("pending_default") == "allow":
            return self.app.push_screen(ConfirmModal(
                "Block everything not allowed?",
                "Unmatched connections will be DENIED: only apps with an allow rule go out.\n"
                "netguard adds allow rules for the essentials (DNS, NetworkManager, time, pacman, curl, iwd).\n"
                "Add your browser and apps before applying.\n\nEscape hatch: sudo systemctl stop opensnitchd"),
                lambda yes: self.ng_call(["apps", "default", "deny", "-y"], "Default: deny · A applies it") if yes else None)
        self.ng_call(["apps", "default", "allow"], "Default: allow · A applies it")

    def action_apply_rules(self) -> None:
        if self.page == "apps" and ngapi.available():
            self.term(["apps", "apply"], "Apply the OpenSnitch rules")

    # ── 4 · History ──

    def show_hist(self, d: dict) -> None:
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]
        style = {"connect": ok, "disconnect": muted, "mode": THEME["primary"], "vpn_up": ok, "vpn_down": warn,
                 "killswitch": warn, "warning": err, "suspicious": err, "ap_learned": muted}
        rows, self.hist = [], {}
        for i, e in enumerate(reversed(d["hist"])):
            k = e.get("ev", "?")
            if k == "connect":
                det = f"{e.get('name')} ({e.get('trust')})" + (f" · AP {e['bssid']}" if e.get("bssid") else "")
            elif k == "mode":
                det = f"{e.get('frm') or '—'} → {e.get('to')} · {e.get('reason', '')}"
            elif k == "killswitch":
                det = "armed" if e.get("on") else "disarmed"
            elif k in ("vpn_up", "vpn_down", "disconnect"):
                det = e.get("name", "")
            elif k == "warning":
                det = e.get("title", "")
            else:
                det = ", ".join(f"{a}={b}" for a, b in e.items() if a not in ("t", "ev", "uuid"))
            self.hist[str(i)] = e
            rows.append((str(i), [Text(time.strftime("%d/%m %H:%M:%S", time.localtime(e.get("t", 0))), style=muted),
                                  Text(k, style=style.get(k, "")), det]))
        self.query_one("#ns-hist", Table).set_rows(rows)
        self.query_one("#ns-hist-panel").border_subtitle = f" {len(rows)} events " if rows else " no events yet "

    def action_clear_history(self) -> None:
        if self.page == "hist" and ngapi.available():
            self.app.push_screen(ConfirmModal("Clear network history", "Delete every recorded event?"),
                                 lambda yes: self.ng_call(["history", "--clear"], "History cleared") if yes else None)

    # ── eventos ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key, tid = str(event.row_key.value), event.data_table.id
        if key == "install":
            return self.install()
        if tid == "ns-hard":
            self.hard_selected(key)
        elif tid == "ns-ports":
            self.port_selected(key)
        elif tid == "ns-apps":
            self.rule_selected(key)
        elif tid == "ns-hist" and (e := getattr(self, "hist", {}).get(key)):
            self.app.push_screen(TextModal("Event", json.dumps(e, indent=1, ensure_ascii=False), end=False))
