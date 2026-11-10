"""Firewall (GUI): paridad con FirewallView (settings/sections/firewall.py + netzones.py).

Dos pestañas, como la TUI: Zones (modo seguro/inseguro por red, kill switch, bypass y pool de
VPN; scripts/netguard.py) y Rules (firewalld: prender/apagar, zona por defecto, servicios y
puertos permitidos, zona de cada conexión).

Lectura SIN firewall-cmd ni D-Bus (cada llamada podía disparar polkit = huella): las reglas salen
de los XML (/etc/firewalld pisa a /usr/lib/firewalld), que es lo que queda porque todo cambio se
hace --permanent + --reload; el estado de systemctl y las zonas de las conexiones de nmcli.
Los cambios y la "autenticación para bajar la protección" de netguard van por el helper root de
la GUI (rootd.py: una sola huella por apertura); netguard-root --via=auth es lo mismo que
`pkexec …/netguard/auth`, pero sin un pedido de huella extra.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import _lib as L

UI: dict = {}
NGR = "/usr/local/lib/netguard/netguard-root"
FW_DIRS = [Path("/usr/lib/firewalld"), Path("/etc/firewalld")]   # /etc pisa a /usr/lib
_cache: dict = {"t": 0.0, "heavy": {}}


def T():
    return L.tui_module("firewall")


def NZ():
    T()
    import netzones
    return netzones


def ng():
    return NZ().ng


# ── firewalld sin D-Bus ──

def zone_conf(zone: str) -> dict:
    for base in reversed(FW_DIRS):
        f = base / "zones" / f"{zone}.xml"
        try:
            x = f.read_text()
        except OSError:
            continue
        m = re.search(r'<zone[^>]*target="([^"]+)"', x)
        return {"target": m.group(1) if m else "default",
                "services": re.findall(r'<service name="([^"]+)"', x),
                "ports": [f"{p}/{proto}" for p, proto in re.findall(r'<port[^>]*port="([^"]+)"[^>]*protocol="([^"]+)"', x)]
                + [f"{p}/{proto}" for proto, p in re.findall(r'<port[^>]*protocol="([^"]+)"[^>]*port="([^"]+)"', x)]}
    return {"target": "default", "services": [], "ports": []}


def svc_ports(svc: str) -> str:
    """Puertos de un servicio (el XML trae protocol y port en cualquier orden)."""
    for base in reversed(FW_DIRS):
        try:
            x = (base / "services" / f"{svc}.xml").read_text()
        except OSError:
            continue
        out = []
        for tag in re.findall(r"<port\b[^>]*>", x):
            p, pr = re.search(r'port="([^"]+)"', tag), re.search(r'protocol="([^"]+)"', tag)
            if p and pr:
                out.append(f"{p.group(1)}/{pr.group(1)}")
        return " ".join(out) or "—"
    return "—"


def auth(*args: str) -> tuple[bool, str]:
    """Lo que en la TUI es ng.authenticate(): verificación (o bypass) con root, por el helper de la GUI."""
    if not Path(NGR).exists():
        return False, "Set up network zones first"
    return L.root_run([[NGR, "--via=auth", *(args or ("check",))]], timeout=60)


# ════════════════════════════════════════════════════════════════
#  páginas
# ════════════════════════════════════════════════════════════════

def heavy(force: bool = False) -> dict:
    """Perfiles de NM, Forti, Citrix y el daemon (procesos): cada 30 s o a pedido."""
    if force or time.time() - _cache["t"] > 30 or not _cache["heavy"]:
        nz = NZ()
        profiles = nz.nm_profiles()
        _cache["heavy"] = {"profiles": profiles, "wg": [p["name"] for p in profiles if p["type"] == "wireguard"],
                           "ovpn": nz.ovpn_profiles(profiles), "forti": nz.forti_profiles(), "citrix": nz.citrix_configured(),
                           "agent": Path("/usr/lib/systemd/user/hyprpolkitagent.service").exists()}
        _cache["t"] = time.time()
    return _cache["heavy"]


def zones_page() -> list:
    n, nz = ng(), NZ()
    h = heavy()
    conf, st = n.load_conf(), n.read_state()
    fresh = time.time() - st.get("time", 0) < 15
    daemon = fresh or nz.daemon_running()
    installed = n.installed()
    enabled = conf.get("enabled") == "on"
    rows = []
    if not installed:
        rows.append(L.button("nz:setup", "Set up network zones", "Polkit agent, root helper, firewalld · asks for root once", "Set up"))
    elif n.helper_version() < n.HELPER_VERSION:
        rows.append(L.button("nz:setup", "Set up again", "The installed root helper is outdated (can't report the real kill switch state)",
                             "Update"))
    rows.append(L.toggle("nz:enabled", "Network zones", "Safe/unsafe per network, applied by the netguard daemon", enabled))
    if enabled:
        mode = st.get("mode", "off") if fresh else "off"
        how = "automatic" if conf.get("auto") == "on" else "set by hand"
        cur = "auto" if conf.get("auto") == "on" else conf.get("manual_mode", "insecure")
        reason = st.get("reason", "")
        rows.append(L.choice("nz:mode", "Mode", f"Now {dict(safe='SAFE', insecure='UNSAFE').get(mode, '—')} · {how}"
                             + (f" · {reason}" if reason and reason != how else ""),
                             cur, ["auto", "insecure", "safe"]))
        ks_on = conf.get("killswitch") == "on"
        bypass = st.get("bypass_until", 0) - time.time()
        up = st.get("vpn_up", []) if fresh else []
        unsafe = mode == "insecure"
        lost = st.get("vpn_lost_at", 0) if fresh else 0
        if bypass > 0:
            why = f"Bypass {int(bypass)} s: nothing blocked until it ends"
        elif st.get("killswitch") and lost:
            why = f"VPN dropped: still blocking while it reconnects ({int(time.time() - lost)} s)"
        elif st.get("killswitch"):
            why = "Armed: only the VPN goes out" + (f" · {', '.join(up)}" if up else "")
        elif unsafe and ks_on and not up:
            why = "Not blocking: no VPN connected, traffic is NOT protected"
        elif unsafe and not ks_on:
            why = "Unsafe networks are NOT blocked" + (f" · protected by {', '.join(up)}" if up else "")
        else:
            why = "Arms on unsafe networks once the VPN is up" if ks_on else "Unsafe networks are NOT blocked"
        rows.append(L.toggle("nz:killswitch", "Kill switch", why, ks_on))
        if unsafe and fresh and not st.get("firewalld", True):
            rows.append(L.button("nz:firewalld", "firewalld stopped", "Incoming connections are not blocked", "Start"))
        secs = conf.get("bypass_secs", "120")
        rows.append(L.button("nz:captive", "Captive portal", f"Opens {secs} s without kill switch and a login page (hotel, airport)", "Open"))
        rows.append(L.button("nz:bypass", "Bypass", "Same, without opening the browser (SAML login of Forti/Citrix)", "Bypass"))
        if st.get("last_error"):
            rows.append(L.button("nz:log", "Last error", st["last_error"][:80], "Log", danger=True))
        if not daemon:
            rows.append(L.button("nz:daemon", "Daemon stopped", "netguard.py is not running", "Start", danger=True))
    if installed and not h["agent"]:
        rows.append(L.info("agent", "Polkit agent missing", "run Set up again"))

    names = {**n.network_names(), **{p["uuid"]: p["name"] for p in h["profiles"]}}
    nets = n.networks()
    now = {c["uuid"]: c for c in st.get("conns", [])} if fresh else {}
    trust = {"trusted": "● trusted", "untrusted": "● untrusted"}
    nrows, seen = [], set()
    for uuid, c in now.items():
        seen.add(uuid)
        t = n.trust_of({"uuid": uuid, "name": c["name"]}, nets)
        nrows.append(L.item(f"net:{uuid}", c["name"], sub=f"{trust.get(t, '? new')} · connected", on=t == "trusted",
                            glyph="󰖩", actions=[L.action(f"net:{uuid}", "Untrust" if t == "trusted" else "Trust"),
                                                L.action(f"forget:{uuid}", "Forget", True)]))
    for uuid, t in sorted(nets.items(), key=lambda kv: names.get(kv[0], kv[0]).lower()):
        if uuid not in seen:
            nrows.append(L.item(f"net:{uuid}", names.get(uuid, uuid[:8] + "…"), sub=trust.get(t, "? new"), on=t == "trusted",
                                glyph="󰖪", actions=[L.action(f"net:{uuid}", "Untrust" if t == "trusted" else "Trust"),
                                                    L.action(f"forget:{uuid}", "Forget", True)]))

    pool = n.pool(conf)
    upset = set(st.get("vpn_up", [])) if fresh else set()
    avail = h["wg"] + [f"ovpn:{p}" for p in h["ovpn"]] + [f"forti:{p}" for p in h["forti"]] + (["citrix"] if h["citrix"] else [])
    prow = []
    for i, e in enumerate(pool):
        state = "● connected" if e in upset else f"#{i + 1} in pool"
        if e == st.get("vpn_pref") and e not in upset:
            state += " · preferred"
        prow.append(L.item(f"use:{e}", e.removeprefix("forti:").removeprefix("ovpn:"), sub=f"{n.entry_kind(e)} · {state}",
                           on=e in upset, glyph="󰖂",
                           actions=[L.action(f"use:{e}", "Use now"), L.action(f"up:{e}", "↑"), L.action(f"down:{e}", "↓"),
                                    L.action(f"pool:{e}", "Remove", True)]))
    for e in avail:
        if e not in pool:
            prow.append(L.item(f"pool:{e}", e.removeprefix("forti:").removeprefix("ovpn:"), sub=f"{n.entry_kind(e)} · not in pool",
                               glyph="󰖂", actions=[L.action(f"pool:{e}", "Add to pool")]))
    prow.append(L.button("ovpn", "Import OpenVPN (.ovpn)", "TCP 443 fallback for networks that block WireGuard", "Import"))
    return [L.group("Network zones", rows), L.group("Networks", nrows or [L.info("none", "No known networks", "")]),
            L.group("VPN pool", prow)]


def rules_page() -> list:
    t = T()
    import shutil
    installed = bool(shutil.which("firewall-cmd"))
    if not installed:
        return [L.group("Firewall", [L.info("missing", "firewalld is not installed", "sudo pacman -S firewalld")])]
    running, enabled = t.unit_state()
    zone = t.default_zone()
    zc = zone_conf(zone)
    st = [L.toggle("fw:toggle", "Firewall", ("on" if running else "off") + (" · starts at boot" if enabled else " · not started at boot"),
                   running),
          L.choice("fw:zone", "Default zone", f"{t.ZONE_DESC.get(zone, '')} · {t.target_text(zc['target'])}", zone,
                   t.xml_names("zones"))]
    rules = [L.item(f"rule:service:{s}", s, sub=f"service · {svc_ports(s)}", glyph="󰒍",
                    actions=[L.action(f"rmrule:service:{s}", "Remove", True)]) for s in zc["services"]]
    rules += [L.item(f"rule:port:{p}", p, sub="port", glyph="󰒍", actions=[L.action(f"rmrule:port:{p}", "Remove", True)])
              for p in zc["ports"]]
    rules.append(L.button("allow", "Allow incoming", "A firewalld service (ssh, kdeconnect…) or a port like 5900/tcp", "Allow"))
    conns = [L.item(f"conn:{c['name']}", c["name"], sub=f"{c['dev']} · zone {c['zone'] or f'default ({zone})'}", glyph="󰈀",
                    actions=[L.action(f"conn:{c['name']}", "Change zone")]) for c in t.nm_connections()]
    return [L.group("Firewall", st),
            L.group(f"Allowed incoming · {zone}" + ("" if rules[:-1] else " · nothing allowed: everything incoming is blocked"), rules),
            L.group("Connections", conns)]


def get() -> dict:
    tab = UI.get("tab") or "zones"
    try:
        groups = zones_page() if tab == "zones" else rules_page()
    except Exception as e:  # noqa: BLE001
        groups = [L.group("Error", [L.info("err", "Couldn't read the state", str(e)[:120])])]
    p = L.page("Firewall", "Changes ask for your fingerprint once per GUI session", groups, refresh=5 if tab == "zones" else 15)
    p.update(tabs=[{"key": "zones", "label": "Zones"}, {"key": "rules", "label": "Rules"}], tab=tab)
    return p


# ════════════════════════════════════════════════════════════════
#  acciones
# ════════════════════════════════════════════════════════════════

def set_value(key, value):
    n = ng()
    conf = n.load_conf()
    if key == "nz:enabled":
        if not value:
            ok, out = auth()
            if not ok:
                return L.fail(out or "Authentication failed or cancelled")
            n.write_kv(n.CONF, {"enabled": "off"})
            return L.ok("Network zones off: back to normal")
        if not n.installed():
            return act("nz:setup")
        n.write_kv(n.CONF, {"enabled": "on"})
        if not NZ().daemon_running():
            L.detach([str(NZ().NG_PY), "daemon"])
        return L.ok("Network zones on")
    if key == "nz:mode":
        upd = {"auto": "on"} if value == "auto" else {"auto": "off", "manual_mode": value}
        if value == "safe":
            ok, out = auth()
            if not ok:
                return L.fail(out or "Authentication failed or cancelled")
        n.write_kv(n.CONF, upd)
        return L.ok(f"Mode: {value}")
    if key == "nz:killswitch":
        if conf.get("killswitch") == "on" and not value:
            ok, out = auth()
            if not ok:
                return L.fail(out or "Authentication failed or cancelled")
            n.write_kv(n.CONF, {"killswitch": "off"})
            return L.ok("Kill switch off")
        n.write_kv(n.CONF, {"killswitch": "on" if value else "off"})
        return L.ok("Kill switch on for unsafe networks" if value else "Kill switch off")
    if key == "fw:toggle":
        if value:
            return L.root_ok([["systemctl", "enable", "--now", "firewalld"]], "Firewall on")
        return L.confirm("fw:off", "Turn off firewall", "Stop firewalld and don't start it at boot?\n"
                         "Every port will be reachable from the network.", ok_label="Turn off")
    if key == "fw:zone":
        return L.root_ok([["firewall-cmd", f"--set-default-zone={value}"]], f"Default zone: {value}")
    return L.fail("Unknown setting")


def act(key: str, text=None):
    n = ng()
    t = T()
    op, _, arg = key.partition(":")
    if key == "fw:off":
        return L.root_ok([["systemctl", "disable", "--now", "firewalld"]], "Firewall off") if L.yes(text) else L.ok()
    if op == "nz":
        conf = n.load_conf()
        if arg == "setup":
            return setup(text)
        if arg == "log":
            try:
                body = "\n".join(n.LOG.read_text().splitlines()[-120:])
            except OSError:
                body = "(no log yet)"
            return L.text_view("netguard log", body)
        if arg == "daemon":
            L.detach([str(NZ().NG_PY), "daemon"])
            return L.ok("netguard started")
        if arg == "firewalld":
            return L.root_ok([["systemctl", "enable", "--now", "firewalld"]], "Firewall on")
        if arg in ("bypass", "captive"):
            secs = conf.get("bypass_secs", "120")
            ok, out = auth("bypass", secs)
            if not ok:
                return L.fail(out or "Authentication failed or cancelled")
            if arg == "captive":
                L.detach(["xdg-open", "http://neverssl.com"])
            return L.ok(f"Bypass: {secs} s without kill switch")
    if op == "net":
        nets = n.networks()
        st = n.read_state()
        name = next((c["name"] for c in st.get("conns", []) if c["uuid"] == arg), "") or \
            next((p["name"] for p in heavy()["profiles"] if p["uuid"] == arg), "")
        if nets.get(arg) == "trusted":
            n.set_network(arg, "untrusted", name)
            return L.ok(f"{name}: untrusted")
        ok, out = auth()
        if not ok:
            return L.fail(out or "Authentication failed or cancelled")
        n.set_network(arg, "trusted", name)
        return L.ok(f"{name}: trusted")
    if op == "forget":
        if not L.yes(text):
            return L.confirm(key, "Forget network", "It is treated as new (unsafe) next time.", ok_label="Forget")
        n.set_network(arg, None)
        return L.ok("Forgotten")
    if op == "use":
        kind = n.entry_kind(arg)
        if kind in n.AUTO_KINDS:
            n.request(vpn=arg)
            return L.ok(f"Switching to {arg}… (the kill switch stays armed)")
        st = n.read_state()
        if st.get("killswitch"):
            ok, out = auth("bypass", n.load_conf().get("bypass_secs", "120"))
            if not ok:
                return L.fail(out or "Authentication failed or cancelled")
        n.request(vpn=arg)
        if kind == "citrix":
            import vpn_tui
            vpn_tui.citrix_open_login()
            return L.ok("Citrix login opened in the browser")
        L.detach(["bash", str(L.Path.home() / ".config/waybar/scripts/vpn-launch.sh")])
        return L.ok("Connect Forti in VPN (the bypass is open)")
    if op in ("pool", "up", "down"):
        pool = n.pool(n.load_conf())
        if op == "pool":
            if arg in pool:
                pool.remove(arg)
            else:
                pool.append(arg)
                if n.entry_kind(arg) in n.AUTO_KINDS:     # DNS solo por la VPN mientras esté arriba
                    L.run(["nmcli", "connection", "modify", "id", n.nm_name(arg), "ipv4.dns-priority", "-50", "ipv6.dns-priority", "-50"])
        elif arg in pool:
            i = pool.index(arg)
            j = max(0, min(len(pool) - 1, i + (-1 if op == "up" else 1)))
            pool[i], pool[j] = pool[j], pool[i]
        n.write_kv(n.CONF, {"pool": ",".join(pool)})
        _cache["t"] = 0
        return L.ok()
    if op == "ovpn":
        if text is None:
            return L.form("ovpn", "Import OpenVPN (.ovpn)", [{"name": "file", "label": "FILE", "text": str(L.Path.home()) + "/"}],
                          hint="TCP 443 configs pass where WireGuard is blocked (hotels, offices).", ok_label="Import")
        v = L.parse_form(text)
        f = L.Path(v.get("file", "")).expanduser()
        if not f.is_file() or f.suffix != ".ovpn":
            return L.form("ovpn", "Import OpenVPN (.ovpn)", [{"name": "file", "label": "FILE", "text": v.get("file", "")}],
                          error="Pick an existing .ovpn file", ok_label="Import")
        r = L.run(["nmcli", "connection", "import", "type", "openvpn", "file", str(f)], timeout=30)
        m = re.search(r"Connection '(.+)' \(", r.stdout)
        if r.returncode != 0 or not m:
            return L.fail((r.stderr or r.stdout).strip()[:120] or "Import failed (is networkmanager-openvpn installed?)")
        name = m.group(1)
        L.run(["nmcli", "connection", "modify", "id", name, "ipv4.dns-priority", "-50", "ipv6.dns-priority", "-50",
               "connection.autoconnect", "no"])
        n.write_kv(n.CONF, {"pool": ",".join(n.pool(n.load_conf()) + [f"ovpn:{name}"])})
        _cache["t"] = 0
        return L.ok(f"Imported {name} · added to the pool as fallback")

    # ── reglas de firewalld ──
    if op == "allow":
        services = set(t.xml_names("services"))
        if text is None:
            return L.form("allow", f"Allow incoming · {t.default_zone()}",
                          [{"name": "rule", "label": "SERVICE OR PORT", "text": ""}],
                          hint="A firewalld service name (ssh, kdeconnect…) or port/protocol (5900/tcp, 1714-1764/udp).", ok_label="Allow")
        x = L.parse_form(text).get("rule", "").strip()
        if not (x in services or t.PORT_RE.match(x)):
            return L.form("allow", f"Allow incoming · {t.default_zone()}", [{"name": "rule", "label": "SERVICE OR PORT", "text": x}],
                          error="Not a known service or a port like 8080/tcp", ok_label="Allow")
        flag = f"--add-service={x}" if x in services else f"--add-port={x}"
        return L.root_ok([["firewall-cmd", "--permanent", f"--zone={t.default_zone()}", flag], ["firewall-cmd", "--reload"]],
                         f"Allowed: {x}")
    if op == "rmrule":
        kind, _, name = arg.partition(":")
        zone = t.default_zone()
        if not L.yes(text):
            return L.confirm(key, "Remove rule", f"Stop allowing {kind} {name} in zone {zone}?", ok_label="Remove")
        return L.root_ok([["firewall-cmd", "--permanent", f"--zone={zone}", f"--remove-{kind}={name}"], ["firewall-cmd", "--reload"]],
                         f"Removed: {name}")
    if op == "rule":
        return L.ok()
    if op == "conn":
        zones = ["(default)"] + t.xml_names("zones")
        if text is None:
            return L.form(key, f"Zone · {arg}", [{"name": "zone", "label": "ZONE", "text": "(default)", "choices": zones}],
                          hint=f"(default) follows the default zone ({t.default_zone()}).")
        z = L.parse_form(text).get("zone", "(default)")
        value = "" if z == "(default)" else z
        dev = next((c["dev"] for c in t.nm_connections() if c["name"] == arg), "")
        r = L.run(["nmcli", "connection", "modify", arg, "connection.zone", value])
        if r.returncode != 0:
            ok, out = L.root_run([["nmcli", "connection", "modify", arg, "connection.zone", value]])
            if not ok:
                return L.fail(out[:120] or "nmcli failed")
        if dev:
            L.run(["nmcli", "device", "reapply", dev], timeout=15)
        return L.ok(f"{arg}: zone {z}")
    return L.ok()


def setup(text):
    n, nz = ng(), NZ()
    first = not n.installed()
    if not L.yes(text):
        if not first:
            return L.confirm("nz:setup", "Update the network zones helper",
                             "Reinstalls (root) the root helper and polkit policy from the repo.\n"
                             "Your trusted networks and VPN pool stay as they are.\n\n"
                             "Then restart netguard so it reads the real kill switch state.", danger=False, ok_label="Update")
        return L.confirm("nz:setup", "Set up network zones",
                         "This installs (root, once):\n"
                         "  · hyprpolkitagent: fingerprint/password prompts outside the terminal\n"
                         "  · /usr/local/lib/netguard + polkit policy (kill switch, Avahi)\n"
                         "  · /etc/pam.d/polkit-1 with fingerprint\n"
                         "  · firewalld on; zone home allows KDE Connect, mDNS and VNC\n\n"
                         "The networks you are connected to now are marked as trusted.\n"
                         "Any other network will be UNSAFE: VPN required, nothing else goes out.", danger=False, ok_label="Set up")
    ok, out = L.root_run(nz.setup_cmds(), timeout=900)
    if not ok:
        return L.fail(out.splitlines()[-1][:160] if out else "Setup failed")
    L.run(["systemctl", "--user", "start", "hyprpolkitagent"])
    if first:
        for line in L.run(["nmcli", "-t", "-f", "UUID,TYPE,NAME", "connection", "show", "--active"]).stdout.splitlines():
            uuid, typ, name = (line.split(":", 2) + ["", ""])[:3]
            if typ in n.PHYSICAL:
                n.set_network(uuid, "trusted", name.replace("\\:", ":"))
    wg = [p["name"] for p in nz.nm_profiles() if p["type"] == "wireguard"]
    for name in wg:
        L.run(["nmcli", "connection", "modify", "id", name, "ipv4.dns-priority", "-50", "ipv6.dns-priority", "-50"])
    upd = {"enabled": "on"}
    if not n.pool():
        upd["pool"] = ",".join(wg)
    n.write_kv(n.CONF, upd)
    if not nz.daemon_running():
        L.detach([str(nz.NG_PY), "daemon"])
    _cache["t"] = 0
    return L.ok("Network zones on · current networks trusted" if first else "Root helper updated · restart netguard to use it")
