"""Network zones — la parte de Settings → Firewall que maneja el modo seguro / inseguro, sobre netguard.

netguard es un proyecto aparte (https://github.com/D4rkDr4gon/netguard), opcional en D4rkFiles: el instalador lo
ofrece (--with-netguard) y, si falta, la primera fila de esta pestaña lo instala (scripts/install-netguard.sh, versión
fijada). Esta vista no tiene lógica propia: lee con `netguard … --json` y cambia con sus comandos (ngapi.py), así
que hace exactamente lo mismo que la CLI y la TUI de netguard. Lo que baja la protección lo autentica netguard
(agente de polkit: huella o contraseña); por eso los cambios corren en un worker.

Es un mixin de FirewallView (firewall.py): pone sus tablas en la pestaña "Zones" y sus acciones se despachan
según la tabla con foco.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

import ngapi
from common import sudo_run
from dtui import THEME, ConfirmModal, Field, FormModal, Panel, PickModal, Table, TextModal
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

ZONE_TABLES = ["nz-state", "nz-nets", "nz-pool"]
# firewalld de D4rkFiles en la zona home (casa): KDE Connect, mDNS y VNC. Se agrega al configurar netguard.
FIREWALLD_HOME = [["firewall-cmd", "--permanent", "--zone=home", "--add-service=kdeconnect", "--add-service=mdns"],
                  ["firewall-cmd", "--permanent", "--zone=home", "--add-port=5900/tcp"],
                  ["firewall-cmd", "--reload"]]


class NetZonesMixin:
    """Pestaña Zones de FirewallView."""

    def compose_zones(self) -> ComposeResult:
        with Vertical(id="fw-zones-box"):
            yield Panel(Table(id="nz-state", show_header=False), title="󰒃  Network zones", id="nz-state-panel")
            with Horizontal(id="nz-bottom"):
                yield Panel(Table(id="nz-nets"), title="Networks", id="nz-nets-panel")
                yield Panel(Table(id="nz-pool"), title="VPN pool", id="nz-pool-panel")

    def mount_zones(self) -> None:
        s = self.query_one("#nz-state", Table)
        s.add_column("", key="name", width=26)
        s.add_column("", key="state", width=30)
        s.add_column("", key="desc", width=70)
        n = self.query_one("#nz-nets", Table)
        n.add_column("Network", key="name", width=28)
        n.add_column("Trust", key="trust", width=13)
        n.add_column("", key="now", width=12)
        p = self.query_one("#nz-pool", Table)
        p.add_column("VPN", key="name", width=28)
        p.add_column("Kind", key="kind", width=10)
        p.add_column("State", key="state", width=22)
        self.zd: dict = {}
        self.load_zones()

    # ── datos ──

    @work(thread=True, exclusive=True, group="netzones")
    def load_zones(self, full: bool = True) -> None:
        """full: también el pool (consulta los perfiles VPN de NetworkManager); si no, estado y redes, que es lo
        que corre cada 3 s."""
        d = dict(self.zd) if not full and self.zd else {}
        d["available"] = ngapi.available()
        if d["available"]:
            d["status"] = ngapi.read("status") or {}
            d["nets"] = ngapi.read("net", "list") or []
            if full or "pool" not in d:
                d["pool"] = ngapi.read("pool", "list") or []
        self.app.call_from_thread(self.show_zones, d)

    def show_zones(self, d: dict) -> None:
        self.zd = d
        ok, warn, err, muted, primary = (THEME["status_ok"], THEME["status_warn"], THEME["status_error"],
                                         THEME["muted"], THEME["primary"])
        nets_t, pool_t = self.query_one("#nz-nets", Table), self.query_one("#nz-pool", Table)
        if not d.get("available"):
            self.query_one("#nz-state", Table).set_rows([
                ("install", ["󰒃  Install netguard", Text("○  not installed", style=warn),
                             Text("safe/unsafe per network, VPN-first kill switch, evil twin detection · "
                                  "enter installs it (git + makepkg, then setup)", style=muted)])])
            self.query_one("#nz-state-panel").border_subtitle = " netguard is optional in D4rkFiles "
            nets_t.set_rows([])
            pool_t.set_rows([])
            return
        status = d.get("status", {})
        conf, st = status.get("config", {}), status.get("state", {})
        fresh = bool(status.get("daemon"))
        enabled = conf.get("enabled") == "on"
        rows = []
        if not status.get("installed"):
            rows.append(("setup", ["󰒃  Set up", Text("○  not set up", style=warn),
                                   Text("root helper + polkit policy · asks for sudo once", style=muted)]))
        elif status.get("helper_version", 0) < 2:
            rows.append(("setup", ["󰒃  Set up again", Text("◐  helper outdated", style=warn),
                                   Text("reinstalls the root helper (sudo)", style=muted)]))
        rows.append(("enabled", ["󰖂  Network zones", Text("●  on", style=ok) if enabled else Text("○  off", style=muted),
                                 Text("safe/unsafe per network, applied by the netguard daemon", style=muted)]))
        mode = st.get("mode", "off") if fresh else "off"
        if enabled:
            label = {"safe": Text("●  SAFE", style=f"bold {ok}"), "insecure": Text("●  UNSAFE", style=f"bold {warn}"),
                     "off": Text("○  —", style=muted)}[mode if mode in ("safe", "insecure") else "off"]
            how = "automatic" if conf.get("auto") == "on" else "set by hand"
            rows.append(("mode", ["󰀂  Mode", label, Text(f"{how} · {st.get('reason', '')}", style=muted)]))
            ks_on = conf.get("killswitch") == "on"
            bypass = st.get("bypass_until", 0) - time.time()
            up = st.get("vpn_up", []) if fresh else []
            unsafe = mode == "insecure"
            lost = st.get("vpn_lost_at", 0) if fresh else 0
            if bypass > 0:
                ks, why = Text(f"◐  bypass {int(bypass)} s", style=warn), "nothing blocked until it ends"
            elif st.get("killswitch") and lost:
                ks, why = (Text("◐  VPN dropped", style=warn),
                           f"still blocking while it reconnects ({int(time.time() - lost)} s); lifted after "
                           f"{conf.get('vpn_grace', '45')} s without VPN")
            elif st.get("killswitch"):
                ks, why = Text("●  armed", style=ok), "only the VPN goes out" + (f" · {', '.join(up)}" if up else "")
            elif unsafe and ks_on and not up:
                ks, why = (Text("○  not blocking", style=err),
                           "no VPN connected: traffic is NOT protected (never blocks without a VPN)")
            elif unsafe and not ks_on:
                ks, why = Text("○  off", style=warn), "unsafe networks are NOT blocked" + (
                    f" · protected by {', '.join(up)}" if up else "")
            else:
                ks, why = (Text("○  ready" if ks_on else "○  off", style=muted),
                           "arms on unsafe networks once the VPN is up" if ks_on else "unsafe networks are NOT blocked")
            rows.append(("killswitch", ["󰌾  Kill switch", ks, Text(why, style=muted)]))
            if unsafe and fresh and not st.get("firewalld", True):
                rows.append(("firewalld", ["  firewalld", Text("○  stopped", style=err),
                                           Text("incoming connections are not blocked · start it in the Rules tab (v)",
                                                style=muted)]))
            rows.append(("captive", ["󰖟  Captive portal", Text("enter", style=primary),
                                     Text(f"opens {conf.get('bypass_secs', '120')} s without kill switch and a login "
                                          "page (hotel, airport) · asks for fingerprint", style=muted)]))
            rows.append(("bypass", ["󰒄  Bypass", Text("enter", style=primary),
                                    Text("same, without opening the browser (SAML logins)", style=muted)]))
            if st.get("last_error"):
                rows.append(("error", ["  Last error", Text(st["last_error"][:40], style=err),
                                       Text("enter shows the netguard log", style=muted)]))
            if not fresh:
                rows.append(("daemon", ["  Daemon", Text("○  stopped", style=err),
                                        Text("netguard is not running · enter starts its user service", style=muted)]))
        rows.append(("tui", ["󰒓  netguard TUI", Text("enter", style=primary),
                             Text("everything netguard does, in its own TUI (same look)", style=muted)]))
        self.query_one("#nz-state", Table).set_rows(rows)
        self.query_one("#nz-state-panel").border_subtitle = " fingerprint/password to lower protection "

        def trust_text(t: str) -> Text:
            return {"trusted": Text("● trusted", style=ok), "untrusted": Text("● untrusted", style=warn)}.get(
                t, Text("? " + t, style=err))

        nrows = []
        for n in sorted(d.get("nets", []), key=lambda n: (not n["connected"], n["name"].lower())):
            name = Text(n["name"] or n["key"][:8] + "…", style="bold" if n["connected"] else "")
            nrows.append((n["key"], [name, trust_text(n["trust"]), Text("connected" if n["connected"] else "", style=ok)]))
        nets_t.set_rows(nrows)
        self.query_one("#nz-nets-panel").border_subtitle = " enter trusted/untrusted · d forget "

        prow = []
        for p in d.get("pool", []):
            if p["position"]:
                state = Text("● connected", style=ok) if p["connected"] else Text(f"#{p['position']} in pool", style=primary)
                if p["preferred"] and not p["connected"]:
                    state.append(" · preferred", style=muted)
                prow.append((p["entry"], [p["entry"].removeprefix("manual:"), Text(p["kind"], style=muted), state]))
            else:
                prow.append((p["entry"], [Text(p["entry"], style=muted), Text(p["kind"], style=muted),
                                          Text("not in pool", style=muted)]))
        pool_t.set_rows(prow)
        self.query_one("#nz-pool-panel").border_subtitle = (" enter use now · p in/out of pool · K/J order · "
                                                            "i import OpenVPN (stealth fallback) ")

    # ── acciones ──

    def zones_hints(self, tid: str) -> list[tuple[str, str]]:
        if tid == "nz-nets":
            return [("enter", "trusted/untrusted"), ("d", "forget")]
        if tid == "nz-pool":
            return [("enter", "use now"), ("p", "pool in/out"), ("K", "up"), ("J", "down"), ("i", "import .ovpn")]
        return [("enter", "select")]

    @work(thread=True, exclusive=True, group="nz-call")
    def ng_call(self, args: list[str], ok_msg: str = "", after: Optional[Callable[[], None]] = None) -> None:
        """Comando de netguard en un worker (puede esperar la huella del agente de polkit)."""
        ok, msg = ngapi.call(*args)
        if ok:
            self.app.call_from_thread(self.app.notify_ok, ok_msg or msg or "done")
            if after:
                self.app.call_from_thread(after)
        else:
            self.app.call_from_thread(self.app.notify_err, msg or "netguard refused it")
        self.app.call_from_thread(self.load_zones)

    def zones_row_selected(self, tid: str, key: str) -> None:
        if tid == "nz-state":
            self.zone_state_action(key)
        elif tid == "nz-nets":
            self.toggle_trust(key)
        elif tid == "nz-pool":
            self.use_vpn(key)

    def zone_state_action(self, key: str) -> None:
        conf = self.zd.get("status", {}).get("config", {})
        if key == "install":
            return self.install_netguard()
        if key == "setup":
            return self.setup_zones()
        if key == "tui":
            ngapi.term(self.app, ["tui"])
            return self.load_zones()
        if key == "error":
            log = Path.home() / ".local/state/netguard/netguard.log"
            try:
                text = "\n".join(log.read_text().splitlines()[-120:])
            except OSError:
                text = "(no log yet)"
            return self.app.push_screen(TextModal("netguard log", text))
        if key == "firewalld":
            return self.action_switch()     # pestaña Rules: ahí se prende firewalld
        if key == "daemon":
            return self.ng_daemon()
        if key == "enabled":
            if conf.get("enabled") == "on":
                return self.ng_call(["config", "set", "enabled", "off"], "Network zones off: back to normal")
            return self.ng_call(["on"], "Network zones on")
        if key == "mode":
            return self.pick_mode()
        if key == "killswitch":
            return self.ng_call(["killswitch", "off" if conf.get("killswitch") == "on" else "on"])
        if key in ("bypass", "captive"):
            return self.ng_call([key], f"Bypass: {conf.get('bypass_secs', '120')} s without kill switch")

    @work(thread=True, exclusive=True, group="nz-call")
    def ng_daemon(self) -> None:
        import subprocess
        r = subprocess.run(["systemctl", "--user", "enable", "--now", "netguard"], capture_output=True, text=True)
        if r.returncode == 0:
            self.app.call_from_thread(self.app.notify_ok, "netguard started")
        else:
            self.app.call_from_thread(self.app.notify_err, (r.stderr or "could not start netguard").strip()[:100])
        self.app.call_from_thread(self.load_zones)

    def pick_mode(self) -> None:
        muted = THEME["muted"]
        rows = [("auto", ["󰁪  Automatic", Text("by network: trusted = safe, anything else = unsafe", style=muted)]),
                ("unsafe", ["󰒃  Unsafe (by hand)", Text("VPN required everywhere, even at home", style=muted)]),
                ("safe", ["󰒄  Safe (by hand)", Text("relaxed everywhere · asks for fingerprint", style=muted)])]
        self.app.push_screen(PickModal("Mode", ["Mode", ""], rows),
                             lambda k: self.ng_call(["mode", k], f"Mode: {k}") if k else None)

    def toggle_trust(self, key: str) -> None:
        n = next((n for n in self.zd.get("nets", []) if n["key"] == key), None)
        if not n:
            return
        if key.startswith("name:"):
            prefix = key[5:]
            return self.ng_call(["net", "rule", prefix, "untrusted" if n["trust"] == "trusted" else "trusted"])
        self.ng_call(["net", "untrust" if n["trust"] == "trusted" else "trust", key])

    def action_forget(self) -> None:
        key = self.query_one("#nz-nets", Table).selected_key()
        if not key:
            return
        if key.startswith("name:"):
            return self.ng_call(["net", "rule", key[5:], "del"], "Rule removed")
        self.ng_call(["net", "forget", key], "Forgotten: it is treated as new (unsafe) next time")

    def use_vpn(self, entry: str) -> None:
        p = next((p for p in self.zd.get("pool", []) if p["entry"] == entry), None)
        if not p or not p["position"]:
            return self.app.notify_err("Add it to the pool first (p)")
        if entry.startswith("manual:"):
            # Login interactivo: netguard abre el bypass si hace falta y corre nmcli --ask en la terminal
            ngapi.term(self.app, ["pool", "use", entry], f"Connecting {entry[7:]}")
            return self.load_zones()
        self.ng_call(["pool", "use", entry], f"Switching to {entry}… (the kill switch stays armed)")

    def action_import_ovpn(self) -> None:
        """Importa un .ovpn (p. ej. de Proton, TCP 443) y lo suma al pool: respaldo para redes que bloquean
        WireGuard."""
        if self.focused_table() != "nz-pool":
            return

        def check(v: dict) -> Optional[str]:
            f = Path(v["file"]).expanduser()
            return None if f.is_file() and f.suffix == ".ovpn" else "Pick an existing .ovpn file"

        self.app.push_screen(FormModal("Import OpenVPN (.ovpn)", [
            Field("file", "File", str(Path.home()) + "/", paths=True, files=True)],
            hint="TCP 443 configs pass where WireGuard is blocked (hotels, offices).", validate=check),
            lambda v: self.ng_call(["pool", "import", str(Path(v["file"]).expanduser())],
                                   after=lambda: self.load_zones(full=True)) if v else None)

    def action_pool(self) -> None:
        if self.focused_table() != "nz-pool":
            return
        key = self.query_one("#nz-pool", Table).selected_key()
        p = next((p for p in self.zd.get("pool", []) if p["entry"] == key), None)
        if p:
            self.ng_call(["pool", "remove" if p["position"] else "add", key.removeprefix("manual:")],
                         after=lambda: self.load_zones(full=True))

    def action_move(self, step: int) -> None:
        if self.focused_table() != "nz-pool":
            return
        key = self.query_one("#nz-pool", Table).selected_key()
        p = next((p for p in self.zd.get("pool", []) if p["entry"] == key), None)
        if p and p["position"]:
            self.ng_call(["pool", "move", key.removeprefix("manual:"), "up" if step < 0 else "down"],
                         after=lambda: self.load_zones(full=True))

    def install_netguard(self) -> None:
        def done(yes: bool) -> None:
            if yes and ngapi.install(self.app, setup=True):
                sudo_run(self.app, FIREWALLD_HOME, "firewalld: zone home for KDE Connect, mDNS and VNC")
                self.app.notify_ok("netguard installed and set up")
            self.load_zones()

        self.app.push_screen(ConfirmModal(
            "Install netguard",
            "netguard is a separate project (github.com/D4rkDr4gon/netguard), optional in D4rkFiles.\n"
            "This downloads the pinned version, builds it with makepkg (sudo) and runs its setup:\n"
            "  · root helper + polkit policy (kill switch, Avahi)\n"
            "  · the networks you are connected to now become trusted\n"
            "  · the netguard user service starts\n\n"
            "Any other network will be UNSAFE: VPN required (add one to the pool)."), done)

    def setup_zones(self) -> None:
        def done(yes: bool) -> None:
            if yes and ngapi.term(self.app, ["setup", "--enable-service", "-y"], "netguard setup"):
                self.app.notify_ok("netguard set up")
            self.load_zones()

        self.app.push_screen(ConfirmModal(
            "Set up netguard", "Runs `netguard setup` (sudo): root helper and polkit policy.\n"
            "Your trusted networks and VPN pool stay as they are."), done)
