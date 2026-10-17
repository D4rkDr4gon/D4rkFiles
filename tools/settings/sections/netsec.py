"""Network security — endurecimiento de red que completa a las zonas (Settings → Firewall → Zones).

Cuatro páginas (tab o 1-4):

1 Hardening  lo que aplica el daemon por conexión (DNS cifrado, IPv6 y autoconexión en redes inseguras,
             detección de evil twin, aviso de puertos; netguard.conf) y lo que se instala una vez con sudo:
             sysctl de red (system/netguard/sysctl.conf) y privacidad de MAC/IPv6 (nm-privacy.conf, iwd-main.conf).
2 Ports      qué escucha fuera de loopback ahora (`ss`), con el proceso y su unidad de systemd.
3 Apps       firewall por aplicación con OpenSnitch: reglas de apps y sitios armadas desde listas dinámicas
             (lo que usa la red ahora, las apps instaladas, los sitios del historial de Firefox). La fuente es
             ~/.config/dotfiles/netguard/opensnitch.json; `A` las escribe en /etc/opensnitchd/rules/netguard-*.json (sudo).
4 History    el historial de redes del daemon (history.jsonl): redes, modo, VPN, kill switch, avisos.

Bajar la protección (DNS sin cifrar, IPv6 o autoconexión en redes inseguras, sin detección de evil twin)
pide huella o contraseña, como en Zones. Escape de OpenSnitch si algo deja de salir: `sudo systemctl stop
opensnitchd` (sin el daemon no filtra nada).
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from common import DOTFILES, root_file, run, sudo_run, tilde
from dtui import THEME, Card, ConfirmModal, DView, Field, FormModal, Panel, PickModal, Table, TextModal, css
from netzones import NG_PY, ng
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import ContentSwitcher, DataTable, Static

SRC = DOTFILES / "system" / "netguard"
PAGES = [("hard", "Hardening"), ("ports", "Ports"), ("apps", "App firewall"), ("hist", "History")]
SYSCTL_DST = "/etc/sysctl.d/90-netguard.conf"
NM_DST = "/etc/NetworkManager/conf.d/90-netguard-privacy.conf"
IWD_DST = "/etc/iwd/main.conf"
OS_RULES = "/etc/opensnitchd/rules"
OS_CONF = Path("/etc/opensnitchd/default-config.json")
OS_FILE = ng.CONF_DIR / "opensnitch.json"           # fuente de las reglas (la escribe esta vista)
# Lo mínimo que tiene que poder salir si la acción por defecto pasa a "deny"
ESSENTIAL = ["/usr/lib/systemd/systemd-resolved", "/usr/bin/NetworkManager", "/usr/lib/systemd/systemd-timesyncd",
             "/usr/bin/pacman", "/usr/bin/curl", "/usr/lib/iwd/iwd"]

# (clave de netguard.conf, nombre, valores en orden de MÁS a menos protección, descripción por valor)
DAEMON_OPTS = [
    ("dns", "Encrypted DNS", ["strict", "opportunistic", "off"],
     {"strict": "DNS over TLS to Quad9 on every network (local names of the router stop resolving)",
      "opportunistic": "TLS when the network DNS supports it, plain otherwise",
      "off": "the network DNS, unencrypted"}),
    ("ipv6_unsafe", "IPv6 on unsafe networks", ["off", "on"],
     {"off": "disabled on untrusted networks: no leaks, no address that identifies you", "on": "left as is"}),
    ("autoconnect_unsafe", "Autoconnect unsafe networks", ["off", "on"],
     {"off": "an untrusted or new network never reconnects by itself", "on": "NetworkManager decides"}),
    ("ap_check", "Fake network detection", ["on", "off"],
     {"on": "a trusted Wi-Fi with another access point or weaker security is UNSAFE (evil twin)", "off": "by name only"}),
    ("ports_warn", "Open ports warning", ["on", "off"],
     {"on": "warn about listening services on unsafe networks without firewalld", "off": "no warning"}),
]


# ── archivos de sistema ───────────────────────────────────

def installed_file(dst: str, src: Path) -> str:
    """'ours' si /etc tiene nuestra versión, 'old' si es nuestra pero distinta, 'other' si hay uno ajeno, ''."""
    try:
        cur = Path(dst).read_text()
    except OSError:
        return ""
    if cur == src.read_text():
        return "ours"
    return "old" if cur.startswith("# netguard") else "other"


def iwd_backend() -> bool:
    try:
        return any("wifi.backend=iwd" in p.read_text() for p in Path("/etc/NetworkManager/conf.d").glob("*.conf"))
    except OSError:
        return False


# ── OpenSnitch ────────────────────────────────────────────

def os_load() -> dict:
    try:
        d = json.loads(OS_FILE.read_text())
    except (OSError, ValueError):
        d = {}
    d.setdefault("default", "allow")
    d.setdefault("rules", [])
    return d


def os_save(d: dict) -> None:
    OS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1) + "\n")
    os.replace(tmp, OS_FILE)


def site_regex(domain: str) -> str:
    """example.com → el dominio y todos sus subdominios."""
    return r"^(.*\.)?" + re.escape(domain.lower().strip(".")) + r"$"


def os_rule_json(r: dict) -> dict:
    """Regla de netguard → JSON de regla de OpenSnitch (1.6+)."""
    ops = []
    if r.get("app"):
        ops.append({"type": "simple", "operand": "process.path", "sensitive": False, "data": r["app"], "list": []})
    if r.get("site"):
        ops.append({"type": "regexp", "operand": "dest.host", "sensitive": False, "data": site_regex(r["site"]),
                    "list": []})
    op = ops[0] if len(ops) == 1 else {"type": "list", "operand": "list", "sensitive": False, "data": "",
                                       "list": ops}
    now = datetime.now(timezone.utc).isoformat()
    return {"created": now, "updated": now, "name": f"netguard-{r['id']}",
            "description": "netguard (Settings → Network security)", "enabled": r.get("enabled", True),
            "precedence": True, "nolog": False, "action": r["action"], "duration": "always", "operator": op}


def os_status() -> dict:
    inst = bool(shutil.which("opensnitchd"))
    active = run(["systemctl", "is-active", "--quiet", "opensnitchd"]).returncode == 0 if inst else False
    try:
        live_default = json.loads(OS_CONF.read_text()).get("DefaultAction", "?")
    except (OSError, ValueError):
        live_default = "?"
    return {"installed": inst, "active": active, "default": live_default}


def apps_on_network() -> list[tuple[str, str]]:
    """[(ejecutable, nombre)] de los procesos con sockets de red ahora (los propios con ruta real)."""
    out = run(["ss", "-Htunap"]).stdout
    seen, res = set(), []
    for pid in sorted(set(re.findall(r"pid=(\d+)", out)), key=int):
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            try:
                exe = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")[0].decode()
                exe = shutil.which(exe) or exe
            except OSError:
                continue
        exe = exe.removesuffix(" (deleted)")
        if exe and exe not in seen:
            seen.add(exe)
            res.append((exe, Path(exe).name))
    return res


def installed_apps() -> list[tuple[str, str]]:
    """[(ejecutable real, nombre)] de las apps con .desktop (Exec → binario → realpath)."""
    dirs = [Path("/usr/share/applications"), Path.home() / ".local/share/applications"]
    res, seen = [], set()
    for d in dirs:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("NoDisplay", "false") == "true" or not e.get("Exec"):
                continue
            words = [w for w in e["Exec"].split() if not w.startswith("%") and "=" not in w and w != "env"]
            if not words:
                continue
            path = shutil.which(words[0]) or words[0]
            if not os.path.isabs(path):
                continue
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                res.append((real, e.get("Name", Path(real).name)))
    return sorted(res, key=lambda t: t[1].lower())


def firefox_sites(limit: int = 60) -> list[tuple[str, int]]:
    """[(dominio, peso)] de Firefox: visitas del historial, o marcadores/lugares si el historial está apagado."""
    profiles = list(Path.home().glob(".mozilla/firefox/*/places.sqlite")) + \
        list(Path.home().glob(".config/mozilla/firefox/*/places.sqlite"))
    counts: dict[str, int] = {}
    for db in profiles:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "places.sqlite"
            try:
                # Firefox lo tiene bloqueado y lo reciente vive en el WAL: se copian los dos y se lee la copia
                shutil.copy2(db, copy)
                if db.with_name(db.name + "-wal").exists():
                    shutil.copy2(db.with_name(db.name + "-wal"), copy.with_name(copy.name + "-wal"))
                con = sqlite3.connect(copy)
                # visitas si hay historial; si no (historial apagado), marcadores y lugares conocidos valen 1
                rows = con.execute("SELECT url, MAX(visit_count, 1) FROM moz_places WHERE url LIKE 'http%' "
                                   "ORDER BY visit_count DESC, frecency DESC LIMIT 3000").fetchall()
                con.close()
            except (OSError, sqlite3.Error):
                continue
        for url, n in rows:
            m = re.match(r"https?://([^/:]+)", url)
            if not m:
                continue
            host = m.group(1).lower().removeprefix("www.")
            parts = host.split(".")
            # dominio registrable aproximado (example.com, example.com.ar)
            dom = ".".join(parts[-3:]) if len(parts) > 2 and len(parts[-1]) == 2 and len(parts[-2]) <= 3 \
                else ".".join(parts[-2:])
            counts[dom] = counts.get(dom, 0) + n
    return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]


def unit_of(pid: str) -> str:
    try:
        cg = Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return ""
    m = re.findall(r"/([^/]+\.(?:service|scope))", cg)
    return m[-1] if m else ""


# ── vista ─────────────────────────────────────────────────

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
        self.applied_sig = ""
        self.render_tabs()
        self.load_hard()
        self.set_interval(5, self.tick)

    def tick(self) -> None:
        if not self.visible_now:
            return
        {"hard": self.load_hard, "ports": self.load_ports, "hist": self.load_hist}.get(self.page, lambda: None)()

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
        self.query_one({"hard": "#ns-hard", "ports": "#ns-ports", "apps": "#ns-apps",
                        "hist": "#ns-hist"}[name], Table).focus()
        self.action_reload()
        self.update_hints()

    def action_next_page(self, step: int) -> None:
        ids = [p for p, _ in PAGES]
        self.action_page(ids[(ids.index(self.page) + step) % len(ids)])

    def action_reload(self) -> None:
        {"hard": self.load_hard, "ports": self.load_ports, "apps": self.load_apps,
         "hist": self.load_hist}[self.page]()

    def hints(self) -> list[tuple[str, str]]:
        base = [("tab", "page"), ("1-4", "jump"), ("q", "quit")]
        if self.page == "hard":
            return [("enter", "change")] + base
        if self.page == "ports":
            return [("enter", "details / stop"), ("r", "refresh")] + base
        if self.page == "apps":
            return [("a", "app rule"), ("s", "site rule"), ("enter", "on/off"), ("x", "allow/deny"),
                    ("d", "delete"), ("A", "apply"), ("D", "default")] + base
        return [("enter", "details"), ("c", "clear")] + base

    def guarded(self, fn) -> None:
        """Bajar la protección pide huella/contraseña (agente de polkit), como en Zones."""
        if not ng.installed():
            return fn()
        self.auth_worker(fn)

    @work(thread=True, exclusive=True, group="ns-auth")
    def auth_worker(self, fn) -> None:
        if ng.authenticate():
            self.app.call_from_thread(fn)
        else:
            self.app.call_from_thread(self.app.notify_err, "Authentication failed or cancelled")

    # ── 1 · Hardening ──

    def load_hard(self) -> None:
        conf = ng.load_conf()
        ok, warn, muted, err = THEME["status_ok"], THEME["status_warn"], THEME["muted"], THEME["status_error"]
        rows = [("hdr:daemon", [Text("APPLIED PER CONNECTION BY NETGUARD", style=f"bold {THEME['primary']}"), "", ""])]
        for key, name, values, desc in DAEMON_OPTS:
            v = conf.get(key, ng.DEFAULTS.get(key, values[-1]))
            best = v == values[0]
            rows.append((f"opt:{key}", [f"  {name}", Text(("● " if best else "○ ") + v, style=ok if best else warn),
                                        Text(desc.get(v, ""), style=muted)]))
        aps = ng.load_aps()
        rows.append(("aps", ["  Known access points", Text(f"{sum(len(b) for _, b in aps.values())} in {len(aps)} networks",
                                                           style=muted),
                             Text("learned the first time on each trusted Wi-Fi · enter to forget one", style=muted)]))
        if conf.get("enabled") != "on":
            rows.append(("zones-off", ["  ⚠ Network zones are off", Text("", style=err),
                                       Text("these only apply while netguard runs: Settings → Firewall → Zones", style=warn)]))
        rows.append(("hdr:sys", [Text("SYSTEM (installed once, sudo)", style=f"bold {THEME['primary']}"), "", ""]))
        st = installed_file(SYSCTL_DST, SRC / "sysctl.conf")
        rows.append(("sysctl", ["  Kernel network hardening", self.file_state(st),
                                Text("no ICMP redirects or source routing, loose rp_filter, martians logged, SYN "
                                     "cookies", style=muted)]))
        st = installed_file(NM_DST, SRC / "nm-privacy.conf")
        iwd = installed_file(IWD_DST, SRC / "iwd-main.conf") if iwd_backend() else "n/a"
        both = st if iwd in ("n/a", st) else ("old" if "ours" in (st, iwd) else st or iwd)
        rows.append(("privacy", ["  MAC & IPv6 privacy", self.file_state(both),
                                 Text("one MAC per network (stable on each), random MAC while scanning, temporary "
                                      "IPv6 addresses" + (" · Wi-Fi MAC via iwd" if iwd != "n/a" else ""),
                                      style=muted)]))
        if iwd == "other":
            rows.append(("iwd-other", ["  ⚠ /etc/iwd/main.conf", Text("yours", style=warn),
                                       Text("not replaced: add AddressRandomization=network under [General] yourself",
                                            style=muted)]))
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
        if key == "sysctl":
            return self.toggle_file("sysctl")
        if key == "privacy":
            return self.toggle_file("privacy")

    def change_opt(self, key: str) -> None:
        _k, name, values, desc = next(o for o in DAEMON_OPTS if o[0] == key)
        cur = ng.load_conf().get(key, ng.DEFAULTS.get(key, values[-1]))
        rows = [(v, [("● " if v == cur else "  ") + v, desc[v]]) for v in values]

        def done(v: Optional[str]) -> None:
            if not v or v == cur:
                return
            def save() -> None:
                ng.write_kv(ng.CONF, {key: v})
                self.app.notify_ok(f"{name}: {v} (netguard applies it in a few seconds)")
                self.load_hard()
            # bajar la protección (ir hacia el final de la lista) pide autenticación
            if values.index(v) > values.index(cur):
                self.guarded(save)
            else:
                save()

        self.app.push_screen(PickModal(name, ["Value", ""], rows), done)

    def forget_ap(self) -> None:
        aps = ng.load_aps()
        names = ng.network_names()
        rows = [(f"{u}|{b}", [names.get(u, u[:8]), b, ng.SEC_NAMES.get(sec, "?")])
                for u, (sec, bs) in aps.items() for b in bs]
        if not rows:
            return self.app.notify_ok("No access points learned yet")

        def done(k: Optional[str]) -> None:
            if not k:
                return
            uuid, bssid = k.split("|")
            sec, bs = aps[uuid]
            left = [b for b in bs if b != bssid]
            if left:
                ng.write_kv(ng.APS, {uuid: " ".join([str(sec)] + left)})
            else:
                ng.write_kv(ng.APS, {}, remove=(uuid,))
            self.app.notify_ok(f"Forgot {bssid} (it will be asked again)")
            self.load_hard()

        self.app.push_screen(PickModal("Forget an access point", ["Network", "BSSID", "Security"], rows), done)

    def toggle_file(self, which: str) -> None:
        if which == "sysctl":
            st = installed_file(SYSCTL_DST, SRC / "sysctl.conf")
            if st == "ours":
                cmds = [["rm", "-f", SYSCTL_DST]]
                title, msg = "Remove kernel network hardening", ("Deletes " + SYSCTL_DST + ".\nThe current values "
                                                                "stay until the next reboot.")
            else:
                cmds = [["install", "-m644", str(SRC / "sysctl.conf"), SYSCTL_DST], ["sysctl", "-p", SYSCTL_DST]]
                title, msg = "Kernel network hardening", ("Installs " + SYSCTL_DST + " and applies it now:\n"
                                                         "no ICMP redirects/source routing, loose rp_filter (keeps "
                                                         "WireGuard and Tailscale working), SYN cookies.")
        else:
            st = installed_file(NM_DST, SRC / "nm-privacy.conf")
            iwd = iwd_backend()
            iwd_st = installed_file(IWD_DST, SRC / "iwd-main.conf") if iwd else ""
            if st == "ours":
                cmds = [["rm", "-f", NM_DST], ["nmcli", "general", "reload", "conf"]]
                if iwd_st == "ours":
                    cmds += [["rm", "-f", IWD_DST], ["systemctl", "restart", "iwd"]]
                title, msg = "Remove MAC & IPv6 privacy", "Back to the real MAC on the next connection" + (
                    "\nWi-Fi reconnects now (iwd restarts)." if iwd_st == "ours" else ".")
            else:
                cmds = [["install", "-m644", str(SRC / "nm-privacy.conf"), NM_DST], ["nmcli", "general", "reload", "conf"]]
                if iwd and iwd_st in ("", "ours", "old"):
                    cmds += [["install", "-D", "-m644", str(SRC / "iwd-main.conf"), IWD_DST],
                             ["systemctl", "restart", "iwd"]]
                title, msg = "MAC & IPv6 privacy", (
                    "One MAC per network, stable on each: networks cannot link you across places.\n"
                    "Temporary IPv6 addresses. Takes effect on the next connection of each network.\n"
                    + ("Wi-Fi reconnects now (iwd restarts).\n" if iwd and iwd_st != "other" else "")
                    + "\nIf your router reserves an IP or filters by MAC, update it after reconnecting.")

        def done(yes: bool) -> None:
            if yes and sudo_run(self.app, cmds, title):
                self.app.notify_ok(title + ": done")
            self.load_hard()

        removing = cmds[0][0] == "rm"
        if removing:
            self.guarded(lambda: self.app.push_screen(ConfirmModal(title, msg), done))
        else:
            self.app.push_screen(ConfirmModal(title, msg), done)

    # ── 2 · Ports ──

    @work(thread=True, exclusive=True, group="ns-ports")
    def load_ports(self) -> None:
        out = run(["ss", "-Htulnp"]).stdout
        ports = ng.listening(out)
        pids = {}
        for line in out.splitlines():
            m = re.search(r"pid=(\d+)", line)
            f = line.split()
            if m and len(f) > 4:
                pids[(f[0], f[4].rpartition(":")[2])] = m.group(1)
        fw = run(["systemctl", "is-active", "--quiet", "firewalld"]).returncode == 0
        st = ng.read_state()
        unsafe = st.get("mode") == "insecure"
        self.app.call_from_thread(self.show_ports, ports, pids, fw, unsafe)

    def show_ports(self, ports: list[dict], pids: dict, fw: bool, unsafe: bool) -> None:
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]
        rows = []
        self.port_rows = {}
        for p in ports:
            pid = pids.get((p["proto"], str(p["port"])), "")
            unit = unit_of(pid) if pid else ""
            if fw and unsafe:
                exp = Text("blocked (zone drop)", style=ok)
            elif fw:
                exp = Text("firewalld decides (zone home)", style=muted)
            else:
                exp = Text("REACHABLE (no firewalld)", style=err if unsafe else warn)
            key = f"{p['proto']}:{p['port']}"
            self.port_rows[key] = {**p, "pid": pid, "unit": unit}
            rows.append((key, [p["proto"], str(p["port"]), p["addr"], p["proc"] or Text("(root)", style=muted),
                               Text(unit, style=muted), exp]))
        self.query_one("#ns-ports", Table).set_rows(rows)
        self.query_one("#ns-ports-panel").border_subtitle = (
            f" {len(rows)} listening outside loopback · firewalld {'on' if fw else 'OFF'} " if rows
            else " ✓ nothing listens outside loopback ")

    def port_selected(self, key: str) -> None:
        p = getattr(self, "port_rows", {}).get(key)
        if not p:
            return
        unit = p["unit"]
        info = (f"{p['proto']}/{p['port']} on {p['addr']}\nprocess: {p['proc'] or '(not visible: runs as root)'} "
                f"pid {p['pid'] or '?'}\nunit: {unit or '?'}")
        if unit.endswith(".service") and not unit.startswith(("user@", "app-")) and "/user" not in unit:
            def done(yes: bool) -> None:
                if yes and sudo_run(self.app, [["systemctl", "disable", "--now", unit]], f"Stop {unit}"):
                    self.app.notify_ok(f"{unit} stopped and disabled")
                self.load_ports()
            return self.app.push_screen(ConfirmModal(f"Stop {unit}?", info + "\n\nStops it and disables it at boot "
                                                     "(sudo). Undo: systemctl enable --now " + unit), done)
        self.app.push_screen(TextModal(f"Port {p['port']}", info + "\n\nNot a system service: close the app that "
                                       "opened it.", end=False))

    # ── 3 · App firewall (OpenSnitch) ──

    @work(thread=True, exclusive=True, group="ns-apps")
    def load_apps(self) -> None:
        self.app.call_from_thread(self.show_apps, os_status(), os_load())

    def show_apps(self, st: dict, d: dict) -> None:
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]
        self.os_st, self.os_d = st, d
        t = Text()
        if not st["installed"]:
            t.append("○ OpenSnitch is not installed", style=warn)
            t.append("  · enter on the row below installs it (sudo pacman -S opensnitch)\n", style=muted)
        else:
            t.append("● opensnitchd running" if st["active"] else "○ opensnitchd stopped",
                     style=ok if st["active"] else err)
            t.append(f"   default for unmatched connections: {st['default']}", style=muted)
            want = d["default"]
            if st["default"] != want:
                t.append(f"  (pending: {want}, A applies)", style=warn)
            t.append("\n")
        sig = json.dumps(d, sort_keys=True)
        pending = sig != getattr(self, "applied_sig", "") and st["installed"]
        t.append("Rules are built from apps using the network now, installed apps and the sites in your Firefox "
                 "history. Escape hatch: sudo systemctl stop opensnitchd", style=muted)
        self.query_one("#ns-apps-state", Card).update(t)
        rows = []
        if not st["installed"]:
            rows.append(("install", [Text("+", style=THEME["primary"]), "", Text("Install OpenSnitch", style="bold"),
                                     Text("sudo, once", style=muted), ""]))
        for r in d["rules"]:
            act = Text(r["action"], style=ok if r["action"] == "allow" else err)
            rows.append((r["id"], [Text("●" if r.get("enabled", True) else "○", style=ok if r.get("enabled", True)
                                        else muted), act, r.get("app") or Text("any app", style=muted),
                                   r.get("site") or Text("any site", style=muted), ""]))
        self.query_one("#ns-apps", Table).set_rows(rows)
        self.query_one("#ns-apps-panel").border_subtitle = (
            f" {len(d['rules'])} rules · " + ("changes not applied: A " if pending else "applied ")
            if st["installed"] else " ")

    def rule_selected(self, key: str) -> None:
        if key == "install":
            return self.install_opensnitch()
        d = os_load()
        for r in d["rules"]:
            if r["id"] == key:
                r["enabled"] = not r.get("enabled", True)
        os_save(d)
        self.load_apps()

    def install_opensnitch(self) -> None:
        cmds = [["pacman", "-S", "--needed", "--noconfirm", "opensnitch"],
                ["systemctl", "enable", "--now", "opensnitchd"]]

        def done(yes: bool) -> None:
            if yes and sudo_run(self.app, cmds, "Install OpenSnitch"):
                self.app.notify_ok("OpenSnitch installed (default: allow; add rules here)")
            self.load_apps()

        self.app.push_screen(ConfirmModal("Install OpenSnitch", "Installs opensnitch and starts opensnitchd.\n"
                                          "Unmatched connections stay ALLOWED until you change the default (D).\n"
                                          "opensnitch-ui (optional, from the same package) asks per connection."),
                             done)

    def new_id(self) -> str:
        return f"{int(time.time() * 1000):x}"

    def action_add_app(self) -> None:
        if self.page != "apps":
            return
        self.pick_app_worker()

    @work(thread=True, exclusive=True, group="ns-pick")
    def pick_app_worker(self) -> None:
        now, inst = apps_on_network(), installed_apps()
        self.app.call_from_thread(self.pick_app, now, inst)

    def pick_app(self, now: list, inst: list) -> None:
        rows = [("manual", [Text("✎ Type a path…", style=THEME["primary"]), ""])]
        rows += [("hdr:now", [Text("USING THE NETWORK NOW", style=f"bold {THEME['primary']}"), ""])]
        rows += [(f"p:{exe}", [name, Text(exe, style=THEME["muted"])]) for exe, name in now]
        rows += [("hdr:inst", [Text("INSTALLED APPS", style=f"bold {THEME['primary']}"), ""])]
        rows += [(f"p:{exe}", [name, Text(exe, style=THEME["muted"])]) for exe, name in inst if exe not in dict(now)]

        def done(k: Optional[str]) -> None:
            if not k or k.startswith("hdr"):
                return
            self.app_rule_form("" if k == "manual" else k[2:])

        self.app.push_screen(PickModal("App rule · pick an app", ["App", "Executable"], rows), done)

    def app_rule_form(self, exe: str) -> None:
        def check(v: dict) -> Optional[str]:
            if not v["app"].startswith("/"):
                return "Full path of the executable (e.g. /usr/lib/firefox/firefox)"
            if v["site"] and not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", v["site"].lower()):
                return "Site: a domain like example.com"
            return None

        def done(v: Optional[dict]) -> None:
            if v:
                self.add_rule({"id": self.new_id(), "action": v["action"], "app": v["app"],
                               "site": v["site"].lower(), "enabled": True})

        self.app.push_screen(FormModal("App rule", [
            Field("app", "Executable", exe, paths=True, files=True),
            Field("action", "Action", "deny", choices=[("deny: block its connections", "deny"),
                                                       ("allow: always let it through", "allow")]),
            Field("site", "Only for this site (empty = any)", "")], validate=check), done)

    def action_add_site(self) -> None:
        if self.page != "apps":
            return
        self.pick_site_worker()

    @work(thread=True, exclusive=True, group="ns-pick")
    def pick_site_worker(self) -> None:
        self.app.call_from_thread(self.pick_site, firefox_sites())

    def pick_site(self, sites: list) -> None:
        rows = [("manual", [Text("✎ Type a domain…", style=THEME["primary"]), ""])]
        if sites:
            rows += [("hdr:ff", [Text("FROM FIREFOX (history and bookmarks)", style=f"bold {THEME['primary']}"), ""])]
            rows += [(f"s:{dom}", [dom, Text(f"{n} visits" if n > 1 else "bookmark/known", style=THEME["muted"])]) for dom, n in sites]

        def done(k: Optional[str]) -> None:
            if not k or k.startswith("hdr"):
                return
            self.site_rule_form("" if k == "manual" else k[2:])

        self.app.push_screen(PickModal("Site rule · pick a site", ["Site", ""], rows), done)

    def site_rule_form(self, site: str) -> None:
        def check(v: dict) -> Optional[str]:
            if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", v["site"].lower()):
                return "A domain like example.com (subdomains included)"
            if v["app"] and not v["app"].startswith("/"):
                return "App: full path of the executable, or empty for every app"
            return None

        def done(v: Optional[dict]) -> None:
            if v:
                self.add_rule({"id": self.new_id(), "action": v["action"], "app": v["app"],
                               "site": v["site"].lower(), "enabled": True})

        self.app.push_screen(FormModal("Site rule", [
            Field("site", "Domain (and its subdomains)", site),
            Field("action", "Action", "deny", choices=[("deny: block it", "deny"), ("allow: always allow it", "allow")]),
            Field("app", "Only for this app (empty = every app)", "", paths=True, files=True)],
            validate=check), done)

    def add_rule(self, r: dict) -> None:
        d = os_load()
        d["rules"].append(r)
        os_save(d)
        self.app.notify_ok("Rule added · A applies it")
        self.load_apps()

    def selected_rule(self) -> Optional[str]:
        k = self.query_one("#ns-apps", Table).selected_key()
        return k if k and k != "install" else None

    def action_flip(self) -> None:
        if self.page != "apps" or not (k := self.selected_rule()):
            return
        d = os_load()
        for r in d["rules"]:
            if r["id"] == k:
                r["action"] = "allow" if r["action"] == "deny" else "deny"
        os_save(d)
        self.load_apps()

    def action_delete(self) -> None:
        if self.page != "apps" or not (k := self.selected_rule()):
            return
        d = os_load()
        d["rules"] = [r for r in d["rules"] if r["id"] != k]
        os_save(d)
        self.app.notify_ok("Rule deleted · A applies it")
        self.load_apps()

    def action_default_action(self) -> None:
        if self.page != "apps":
            return
        d = os_load()
        if d["default"] == "allow":
            def to_deny(yes: bool) -> None:
                if not yes:
                    return
                have = {r.get("app") for r in d["rules"] if r["action"] == "allow" and not r.get("site")}
                for exe in ESSENTIAL:
                    if exe not in have and os.path.exists(exe):
                        d["rules"].append({"id": self.new_id() + Path(exe).name, "action": "allow", "app": exe,
                                           "site": "", "enabled": True})
                d["default"] = "deny"
                os_save(d)
                self.app.notify_ok("Default: deny · essentials allowed · A applies it")
                self.load_apps()
            return self.app.push_screen(ConfirmModal(
                "Block everything not allowed?",
                "Unmatched connections will be DENIED: only apps with an allow rule go out.\n"
                "Allow rules are added for the essentials (DNS, NetworkManager, time, pacman, curl, iwd).\n"
                "Add your browser and apps before applying.\n\n"
                "Escape hatch if something breaks: sudo systemctl stop opensnitchd"), to_deny)

        def to_allow() -> None:
            d["default"] = "allow"
            os_save(d)
            self.app.notify_ok("Default: allow · A applies it")
            self.load_apps()
        self.guarded(to_allow)

    def action_apply_rules(self) -> None:
        if self.page != "apps":
            return
        st = os_status()
        if not st["installed"]:
            return self.app.notify_err("Install OpenSnitch first (enter on the first row)")
        d = os_load()
        cmds = [["sh", "-c", f"rm -f {OS_RULES}/netguard-*.json"], ["install", "-d", "-m755", OS_RULES]]
        for r in d["rules"]:
            cmds.append(["install", "-m644", root_file(json.dumps(os_rule_json(r), indent=1)),
                         f"{OS_RULES}/netguard-{r['id']}.json"])
        if st["default"] != d["default"]:
            try:
                cfg = json.loads(OS_CONF.read_text())
            except (OSError, ValueError):
                cfg = {}
            if cfg:
                cfg["DefaultAction"] = d["default"]
                cmds.append(["install", "-m644", root_file(json.dumps(cfg, indent=2)), str(OS_CONF)])
        cmds.append(["systemctl", "restart", "opensnitchd"])
        if sudo_run(self.app, cmds, f"Apply {len(d['rules'])} OpenSnitch rules"):
            self.applied_sig = json.dumps(d, sort_keys=True)
            self.app.notify_ok("Rules applied")
        self.load_apps()

    # ── 4 · History ──

    def load_hist(self) -> None:
        ev = list(reversed(ng.read_history(800)))
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]
        style = {"connect": ok, "disconnect": muted, "mode": THEME["primary"], "vpn_up": ok, "vpn_down": warn,
                 "killswitch": warn, "warning": err, "suspicious": err, "ap_learned": muted}
        rows = []
        self.hist = {}
        for i, e in enumerate(ev):
            when = time.strftime("%d/%m %H:%M:%S", time.localtime(e.get("t", 0)))
            k = e.get("ev", "?")
            d = {kk: v for kk, v in e.items() if kk not in ("t", "ev")}
            if k == "connect":
                det = f"{d.get('name')} ({d.get('trust')}){' · AP ' + d['bssid'] if d.get('bssid') else ''}"
            elif k == "mode":
                det = f"{d.get('frm') or '—'} → {d.get('to')} · {d.get('reason', '')}"
            elif k == "killswitch":
                det = "armed" if d.get("on") else "disarmed"
            elif k in ("vpn_up", "vpn_down", "disconnect"):
                det = d.get("name", "")
            elif k == "warning":
                det = d.get("title", "")
            else:
                det = ", ".join(f"{a}={b}" for a, b in d.items() if a != "uuid")
            self.hist[str(i)] = e
            rows.append((str(i), [Text(when, style=muted), Text(k, style=style.get(k, "")), det]))
        self.query_one("#ns-hist", Table).set_rows(rows)
        self.query_one("#ns-hist-panel").border_subtitle = (f" {len(rows)} events · {tilde(ng.HISTORY)} " if rows
                                                            else " no events yet (netguard writes them) ")

    def action_clear_history(self) -> None:
        if self.page != "hist":
            return

        def done(yes: bool) -> None:
            if yes:
                ng.HISTORY.unlink(missing_ok=True)
                self.load_hist()
        self.app.push_screen(ConfirmModal("Clear network history", "Delete every recorded event?"), done)

    # ── eventos ──

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        tid = event.data_table.id
        if tid == "ns-hard":
            self.hard_selected(key)
        elif tid == "ns-ports":
            self.port_selected(key)
        elif tid == "ns-apps":
            self.rule_selected(key)
        elif tid == "ns-hist" and (e := getattr(self, "hist", {}).get(key)):
            self.app.push_screen(TextModal("Event", json.dumps(e, indent=1, ensure_ascii=False), end=False))
