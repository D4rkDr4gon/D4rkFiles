"""Network zones — la parte de Settings → Firewall que maneja el modo seguro / inseguro.

La lógica vive en scripts/netguard.py (daemon de usuario, exec-once): esta vista
solo lee su estado (~/.local/state/dotfiles/netguard/state.json) y escribe la config
(~/.config/dotfiles/netguard/netguard.conf y networks.conf) o le deja pedidos (request.json) que el
daemon toma en el próximo tick (cada 3 s). Lo único que hace directo es
autenticar (pkexec → agente de polkit: huella o contraseña) antes de bajar la
protección: marcar una red como de confianza, pasar a seguro a mano, apagar el
kill switch, abrir un bypass.

Setup (una vez, con sudo): hyprpolkitagent, el helper root y la policy de
system/netguard/ en /usr/local/lib/netguard y /usr/share/polkit-1, el PAM de
polkit con huella (solo si hay fprintd y no existe /etc/pam.d/polkit-1), firewalld prendido con la zona home permitiendo KDE Connect,
mDNS y VNC; después, las redes actuales como de confianza y la prioridad de DNS
de las VPN del pool.

Es un mixin de FirewallView (firewall.py): pone sus tablas en la pestaña
"Zones" y sus acciones se despachan según la tabla con foco.
"""

from __future__ import annotations

import importlib.machinery
import shutil
import time
from pathlib import Path
from typing import Optional

from common import DOTFILES, detach, run, sudo_run, tilde
from dtui import THEME, ConfirmModal, Panel, PickModal, Table, TextModal
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

NG_PY = DOTFILES / "scripts" / "netguard.py"
SRC = DOTFILES / "system" / "netguard"
ng = importlib.machinery.SourceFileLoader("netguard", str(NG_PY)).load_module()
ZONE_TABLES = ["nz-state", "nz-nets", "nz-pool"]


def daemon_running() -> bool:
    return run(["pgrep", "-f", "netguard.py daemon"]).returncode == 0


def nm_profiles() -> list[dict]:
    """Conexiones guardadas en NetworkManager: [{name, uuid, type}]."""
    out = []
    for line in run(["nmcli", "-t", "-f", "NAME,UUID,TYPE", "connection", "show"]).stdout.splitlines():
        parts = line.replace("\\:", "\0").split(":")
        if len(parts) >= 3:
            out.append({"name": parts[0].replace("\0", ":"), "uuid": parts[1], "type": parts[2]})
    return out


def forti_profiles() -> list[str]:
    try:
        from vpn_tui import forti_list
        return forti_list() if shutil.which("fortivpn") else []
    except Exception:  # noqa: BLE001
        return []


def citrix_configured() -> bool:
    try:
        from vpn_tui import CITRIX_BIN, citrix_login_url
        return bool(citrix_login_url()) and Path(CITRIX_BIN).exists()
    except Exception:  # noqa: BLE001
        return False


def fprint_pam_ok() -> bool:
    """El PAM del agente de polkit con huella solo se instala si hay fprintd y no existe uno propio."""
    return Path("/usr/lib/security/pam_fprintd.so").exists() and not Path("/etc/pam.d/polkit-1").exists()


def setup_cmds() -> list[list[str]]:
    lib = "/usr/local/lib/netguard"
    return [["pacman", "-S", "--needed", "--noconfirm", "hyprpolkitagent", "nftables"],
            ["install", "-d", "-m755", lib],
            ["install", "-m755", "-o", "root", "-g", "root", str(SRC / "netguard-root"), str(SRC / "apply"),
             str(SRC / "auth"), lib],
            ["install", "-m644", str(SRC / "org.dotfiles.netguard.policy"), "/usr/share/polkit-1/actions/"],
            *([["install", "-m644", str(SRC / "polkit-1.pam"), "/etc/pam.d/polkit-1"]] if fprint_pam_ok() else []),
            ["systemctl", "enable", "--now", "firewalld"],
            # firewall-cmd no deja mezclar --add-service y --add-port en una llamada
            ["firewall-cmd", "--permanent", "--zone=home", "--add-service=kdeconnect", "--add-service=mdns"],
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
        """full: también perfiles de NM, Forti y Citrix (procesos); si no, solo
        archivos (estado del daemon y config): es lo que corre cada 3 s."""
        conf = ng.load_conf()
        st = ng.read_state()
        d = dict(self.zd) if not full and self.zd else {}
        if full or not d:
            profiles = nm_profiles()
            d.update({"profiles": profiles, "wg": [p["name"] for p in profiles if p["type"] == "wireguard"],
                      "forti": forti_profiles(), "citrix": citrix_configured(), "daemon": daemon_running(),
                      "agent": Path("/usr/lib/systemd/user/hyprpolkitagent.service").exists()})
        d.update({"conf": conf, "state": st, "nets": ng.networks(), "installed": ng.installed(),
                  "helper": ng.helper_version(),
                  "fresh": time.time() - st.get("time", 0) < 15})
        if not full:
            d["daemon"] = d["fresh"] or daemon_running()
        self.app.call_from_thread(self.show_zones, d)

    def show_zones(self, d: dict) -> None:
        self.zd = d
        ok, warn, err, muted, primary = (THEME["status_ok"], THEME["status_warn"], THEME["status_error"],
                                         THEME["muted"], THEME["primary"])
        conf, st = d["conf"], d["state"]
        enabled = conf.get("enabled") == "on"
        rows = []
        if not d["installed"]:
            rows.append(("setup", ["󰒃  Set up", Text("○  not installed", style=warn),
                                   Text("polkit agent (fingerprint), root helper, firewalld · asks for sudo once",
                                        style=muted)]))
        elif d["helper"] < ng.HELPER_VERSION:
            rows.append(("setup", ["󰒃  Set up again", Text("◐  helper outdated", style=warn),
                                   Text("the installed root helper cannot report the real kill switch state and "
                                        "may rearm after a bypass · enter (sudo)", style=muted)]))
        rows.append(("enabled", ["󰖂  Network zones",
                                 Text("●  on", style=ok) if enabled else Text("○  off", style=muted),
                                 Text("safe/unsafe per network, applied by the netguard daemon", style=muted)]))
        mode = st.get("mode", "off") if d["fresh"] else "off"
        if enabled:
            label = {"safe": Text("●  SAFE", style=f"bold {ok}"), "insecure": Text("●  UNSAFE", style=f"bold {warn}"),
                     "off": Text("○  —", style=muted)}[mode if mode in ("safe", "insecure") else "off"]
            how = "automatic" if conf.get("auto") == "on" else "set by hand"
            rows.append(("mode", ["󰀂  Mode", label, Text(f"{how} · {st.get('reason', '')}", style=muted)]))
            ks_on = conf.get("killswitch") == "on"
            bypass = st.get("bypass_until", 0) - time.time()
            up = st.get("vpn_up", []) if d["fresh"] else []
            unsafe = mode == "insecure"
            lost = st.get("vpn_lost_at", 0) if d["fresh"] else 0
            if bypass > 0:
                ks, why = Text(f"◐  bypass {int(bypass)} s", style=warn), "nothing blocked until it ends"
            elif st.get("killswitch") and lost:
                ks, why = (Text("◐  VPN dropped", style=warn),
                           f"still blocking while it reconnects ({int(time.time() - lost)} s); lifted after "
                           f"{ng.VPN_GRACE} s without VPN")
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
            if unsafe and d["fresh"] and not st.get("firewalld", True):
                rows.append(("firewalld", ["  firewalld", Text("○  stopped", style=err),
                                           Text("incoming connections are not blocked · start it in the Rules tab (v)",
                                                style=muted)]))
            rows.append(("captive", ["󰖟  Captive portal", Text("enter", style=primary),
                                     Text(f"opens {conf.get('bypass_secs', '120')} s without kill switch and a login "
                                          "page (hotel, airport) · asks for fingerprint", style=muted)]))
            rows.append(("bypass", ["󰒄  Bypass", Text("enter", style=primary),
                                    Text("same, without opening the browser (SAML login of Forti/Citrix)",
                                         style=muted)]))
            if st.get("last_error"):
                rows.append(("error", ["  Last error", Text(st["last_error"][:40], style=err),
                                       Text(f"log: {tilde(ng.LOG)}", style=muted)]))
            if not d["daemon"]:
                rows.append(("daemon", ["  Daemon", Text("○  stopped", style=err),
                                        Text("netguard.py is not running · enter to start it", style=muted)]))
        self.query_one("#nz-state", Table).set_rows(rows)
        sub = " fingerprint/password to lower protection " if d["installed"] else " enter on Set up "
        if d["installed"] and not d["agent"]:
            sub = " polkit agent missing: run Set up again "
        self.query_one("#nz-state-panel").border_subtitle = sub

        # Redes: las conectadas primero, después las conocidas
        names = {**ng.network_names(), **{p["uuid"]: p["name"] for p in d["profiles"]}}
        now = {c["uuid"]: c for c in st.get("conns", [])} if d["fresh"] else {}
        nrows, seen = [], set()

        def trust_text(t: str) -> Text:
            return {"trusted": Text("● trusted", style=ok), "untrusted": Text("● untrusted", style=warn)}.get(
                t, Text("? new", style=err))

        for uuid, c in now.items():
            seen.add(uuid)
            nrows.append((uuid, [Text(c["name"], style="bold"), trust_text(ng.trust_of({"uuid": uuid, "name": c["name"]}, d["nets"])),
                                 Text("connected", style=ok)]))
        for uuid, t in sorted(d["nets"].items(), key=lambda kv: names.get(kv[0], kv[0]).lower()):
            if uuid not in seen:
                nrows.append((uuid, [names.get(uuid, uuid[:8] + "…"), trust_text(t), Text("", style=muted)]))
        self.query_one("#nz-nets", Table).set_rows(nrows)
        self.query_one("#nz-nets-panel").border_subtitle = " enter trusted/untrusted · d forget "

        # Pool: en orden, y después lo disponible que no está
        pool = ng.pool(conf)
        up = set(st.get("vpn_up", [])) if d["fresh"] else set()
        avail = d["wg"] + [f"forti:{p}" for p in d["forti"]] + (["citrix"] if d["citrix"] else [])
        prow = []
        for i, e in enumerate(pool):
            kind = ng.entry_kind(e)
            state = Text("● connected", style=ok) if e in up else Text(f"#{i + 1} in pool", style=primary)
            if e == st.get("vpn_pref") and e not in up:
                state.append(" · preferred", style=muted)
            prow.append((e, [e.removeprefix("forti:"), Text(kind, style=muted), state]))
        for e in avail:
            if e not in pool:
                prow.append((e, [Text(e.removeprefix("forti:"), style=muted), Text(ng.entry_kind(e), style=muted),
                                 Text("not in pool", style=muted)]))
        self.query_one("#nz-pool", Table).set_rows(prow)
        self.query_one("#nz-pool-panel").border_subtitle = " enter use now · p in/out of pool · K/J order "

    # ── acciones ──

    def zones_hints(self, tid: str) -> list[tuple[str, str]]:
        if tid == "nz-nets":
            return [("enter", "trusted/untrusted"), ("d", "forget")]
        if tid == "nz-pool":
            return [("enter", "use now"), ("p", "pool in/out"), ("K", "up"), ("J", "down")]
        return [("enter", "select")]

    @work(thread=True, exclusive=True, group="nz-auth")
    def with_auth(self, then, *auth_args: str) -> None:
        """Pide huella/contraseña (agente de polkit) sin trabar la UI y, si sale
        bien, corre `then` en el hilo de la UI."""
        if not self.zd.get("installed"):
            self.app.call_from_thread(self.app.notify_err, "Set up network zones first")
            return
        ok = ng.authenticate(*auth_args)
        if ok:
            self.app.call_from_thread(then)
        else:
            self.app.call_from_thread(self.app.notify_err, "Authentication failed or cancelled")

    def zones_row_selected(self, tid: str, key: str) -> None:
        if tid == "nz-state":
            self.zone_state_action(key)
        elif tid == "nz-nets":
            self.toggle_trust(key)
        elif tid == "nz-pool":
            self.use_vpn(key)

    def zone_state_action(self, key: str) -> None:
        conf = self.zd.get("conf", {})
        if key == "setup":
            return self.setup_zones()
        if key == "error":
            try:
                text = "\n".join(ng.LOG.read_text().splitlines()[-120:])
            except OSError:
                text = "(no log yet)"
            return self.app.push_screen(TextModal("netguard log", text))
        if key == "firewalld":
            return self.action_switch()     # pestaña Rules: ahí se prende firewalld
        if key == "daemon":
            detach([str(NG_PY), "daemon"])
            self.app.notify_ok("netguard started")
        elif key == "enabled":
            if conf.get("enabled") == "on":
                def off() -> None:
                    ng.write_kv(ng.CONF, {"enabled": "off"})
                    self.app.notify_ok("Network zones off: back to normal")
                    self.load_zones()
                return self.with_auth(off)
            if not self.zd.get("installed"):
                return self.setup_zones()
            ng.write_kv(ng.CONF, {"enabled": "on"})
            if not self.zd.get("daemon"):
                detach([str(NG_PY), "daemon"])
            self.app.notify_ok("Network zones on")
        elif key == "mode":
            return self.pick_mode()
        elif key == "killswitch":
            if conf.get("killswitch") == "on":
                def ks_off() -> None:
                    ng.write_kv(ng.CONF, {"killswitch": "off"})
                    self.app.notify_ok("Kill switch off")
                    self.load_zones()
                return self.with_auth(ks_off)
            ng.write_kv(ng.CONF, {"killswitch": "on"})
            self.app.notify_ok("Kill switch on for unsafe networks")
        elif key in ("bypass", "captive"):
            secs = conf.get("bypass_secs", "120")

            def opened() -> None:
                if key == "captive":
                    detach(["xdg-open", "http://neverssl.com"])
                self.app.notify_ok(f"Bypass: {secs} s without kill switch")
                self.load_zones()
            return self.with_auth(opened, "bypass", secs)
        self.load_zones()

    def pick_mode(self) -> None:
        muted = THEME["muted"]
        rows = [("auto", ["󰁪  Automatic", Text("by network: trusted = safe, anything else = unsafe", style=muted)]),
                ("insecure", ["󰒃  Unsafe (by hand)", Text("VPN required everywhere, even at home", style=muted)]),
                ("safe", ["󰒄  Safe (by hand)", Text("relaxed everywhere · asks for fingerprint", style=muted)])]

        def picked(k: Optional[str]) -> None:
            if not k:
                return
            upd = {"auto": "on"} if k == "auto" else {"auto": "off", "manual_mode": k}

            def save() -> None:
                ng.write_kv(ng.CONF, upd)
                self.app.notify_ok(f"Mode: {k}")
                self.load_zones()
            if k == "safe":
                self.with_auth(save)
            else:
                save()

        self.app.push_screen(PickModal("Mode", ["Mode", ""], rows), picked)

    def toggle_trust(self, uuid: str) -> None:
        cur = self.zd.get("nets", {}).get(uuid, "new")
        name = next((c["name"] for c in self.zd.get("state", {}).get("conns", []) if c["uuid"] == uuid), "") or \
            next((p["name"] for p in self.zd.get("profiles", []) if p["uuid"] == uuid), "")
        if cur == "trusted":
            ng.set_network(uuid, "untrusted", name)
            self.app.notify_ok(f"{name}: untrusted")
            return self.load_zones()

        def trust() -> None:
            ng.set_network(uuid, "trusted", name)
            self.app.notify_ok(f"{name}: trusted")
            self.load_zones()
        self.with_auth(trust)

    def action_forget(self) -> None:
        key = self.query_one("#nz-nets", Table).selected_key()
        if key and key in self.zd.get("nets", {}):
            ng.set_network(key, None)
            self.app.notify_ok("Forgotten: it is treated as new (unsafe) next time")
            self.load_zones()

    def use_vpn(self, entry: str) -> None:
        kind = ng.entry_kind(entry)
        if kind == "wg":
            ng.request(vpn=entry)
            return self.app.notify_ok(f"Switching to {entry}… (the kill switch stays armed)")
        st = self.zd.get("state", {})

        def go() -> None:
            ng.request(vpn=entry)
            if kind == "citrix":
                from vpn_tui import citrix_open_login
                citrix_open_login()
                self.app.notify_ok("Citrix login opened in the browser")
            else:
                self.app.notify_ok("Connect Forti in VPN (the bypass is open)")
                self.app.restart("vpn")
        # Su login es web/interactivo: con el kill switch armado hace falta un bypass
        if st.get("killswitch"):
            self.with_auth(go, "bypass", self.zd.get("conf", {}).get("bypass_secs", "120"))
        else:
            go()

    def action_pool(self) -> None:
        if self.focused_table() != "nz-pool":
            return
        key = self.query_one("#nz-pool", Table).selected_key()
        if not key:
            return
        pool = ng.pool(self.zd.get("conf"))
        if key in pool:
            pool.remove(key)
        else:
            pool.append(key)
            if ng.entry_kind(key) == "wg":
                # DNS solo por la VPN mientras esté arriba (sin fugas)
                run(["nmcli", "connection", "modify", "id", key, "ipv4.dns-priority", "-50",
                     "ipv6.dns-priority", "-50"])
        ng.write_kv(ng.CONF, {"pool": ",".join(pool)})
        self.load_zones()

    def action_move(self, step: int) -> None:
        if self.focused_table() != "nz-pool":
            return
        key = self.query_one("#nz-pool", Table).selected_key()
        pool = ng.pool(self.zd.get("conf"))
        if key not in pool:
            return
        i = pool.index(key)
        j = max(0, min(len(pool) - 1, i + step))
        pool[i], pool[j] = pool[j], pool[i]
        ng.write_kv(ng.CONF, {"pool": ",".join(pool)})
        self.load_zones()

    def setup_zones(self) -> None:
        # Repetir el Setup (helper desactualizado) solo reinstala: no marca como de confianza la
        # red de ese momento, que puede ser un bar
        first = not self.zd.get("installed")

        def done(yes: bool) -> None:
            if not yes:
                return
            if not sudo_run(self.app, setup_cmds(), "Network zones setup"):
                return self.load_zones()
            run(["systemctl", "--user", "start", "hyprpolkitagent"])
            # La primera vez, las redes de ahora quedan como de confianza (el setup ya pidió sudo)
            active = run(["nmcli", "-t", "-f", "UUID,TYPE,NAME", "connection", "show", "--active"]).stdout if first else ""
            for line in active.splitlines():
                uuid, typ, name = (line.split(":", 2) + ["", ""])[:3]
                if typ in ng.PHYSICAL:
                    ng.set_network(uuid, "trusted", name.replace("\\:", ":"))
            wg = [p["name"] for p in nm_profiles() if p["type"] == "wireguard"]
            for name in wg:
                run(["nmcli", "connection", "modify", "id", name, "ipv4.dns-priority", "-50",
                     "ipv6.dns-priority", "-50"])
            upd = {"enabled": "on"}
            if not ng.pool():
                upd["pool"] = ",".join(wg)
            ng.write_kv(ng.CONF, upd)
            if not daemon_running():
                detach([str(NG_PY), "daemon"])
            self.app.notify_ok("Network zones on · current networks trusted" if first else
                               "Root helper updated · restart netguard to use it")
            self.load_zones()

        if not first:
            return self.app.push_screen(ConfirmModal(
                "Update the network zones helper",
                "Reinstalls (sudo) the root helper and polkit policy from the repo.\n"
                "Nothing else changes: your trusted networks and VPN pool stay as they are.\n\n"
                "Then restart netguard (the daemon row) so it reads the real kill switch state."), done)
        self.app.push_screen(ConfirmModal(
            "Set up network zones",
            "This installs (sudo, once):\n"
            "  · hyprpolkitagent: fingerprint/password prompts outside the terminal\n"
            "  · /usr/local/lib/netguard + polkit policy (kill switch, Avahi)\n"
            "  · /etc/pam.d/polkit-1 with fingerprint\n"
            "  · firewalld on; zone home allows KDE Connect, mDNS and VNC\n\n"
            "The networks you are connected to now are marked as trusted.\n"
            "Any other network will be UNSAFE: VPN required, nothing else goes out."), done)

