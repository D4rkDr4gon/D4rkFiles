#!/usr/bin/env python3
"""netguard — zonas de red: modo seguro / inseguro según la red (Settings → Firewall).

Daemon de usuario (exec-once de Hyprland). Cada 3 s mira por D-Bus las conexiones
físicas activas de NetworkManager (Wi-Fi, cable, módem) y decide el modo:
- seguro: todas son de confianza (networks.conf).
- inseguro: alguna no lo es o es nueva. Una red nueva entra como insegura y
  pregunta por notificación "Trusted / Untrusted" (Trusted pide huella o
  contraseña: baja la protección).
`auto=off` en netguard.conf fija el modo a mano (manual_mode).

Modo inseguro:
- firewalld: zona `drop` en la conexión (nada entrante) y sin mandar el nombre
  del equipo por DHCP.
- Sin descubrimiento: Avahi y mDNS/LLMNR apagados; kdeconnectd y wayvnc parados.
- Bluetooth: no emparejable ni visible.
- Kill switch (nftables, helper root por pkexec): solo salen túneles.
- VPN obligatoria: si ninguna del pool está arriba, levanta la WireGuard del pool
  (la preferida o la siguiente si falla). Forti y Citrix cuentan como protección
  cuando están conectadas, pero son interactivas: se conectan a mano (Settings
  abre un bypass para su login).
Modo seguro: zona `home`, descubrimiento de vuelta, kill switch desarmado.

Uso: netguard.py daemon | status | off | request vpn <entrada> | bypass [seg] | captive
  off = apagado de emergencia (sin huella): desarma todo y deja enabled=off
Config (fuera del repo): ~/.config/dotfiles/netguard/netguard.conf y networks.conf;
estado en ~/.local/state/dotfiles/netguard/ (NETGUARD_CONF_DIR / NETGUARD_STATE para copias).
Helper root: system/netguard/ (lo instala Settings → Firewall → Setup).
"""

from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de scripts/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
CONF_DIR = Path(os.environ.get("NETGUARD_CONF_DIR") or CONFIG_HOME / "dotfiles" / "netguard")
CONF = CONF_DIR / "netguard.conf"
NETWORKS = CONF_DIR / "networks.conf"
STATE_DIR = Path(os.environ.get("NETGUARD_STATE") or STATE_HOME / "dotfiles" / "netguard")
STATE = STATE_DIR / "state.json"
REQUEST = STATE_DIR / "request.json"
APS = CONF_DIR / "aps.conf"             # access points conocidos de cada red de confianza
HISTORY = STATE_DIR / "history.jsonl"
LOG = STATE_DIR / "netguard.log"
LIB = Path("/usr/local/lib/netguard")
APPLY, AUTH = LIB / "apply", LIB / "auth"
HELPER = LIB / "netguard-root"
HELPER_VERSION = 2              # el que trae este repo (system/netguard)
ARMED_FLAG = Path("/run/netguard/armed")   # la escribe el helper v2 mientras el kill switch está puesto
VPN_GRACE = 45                  # s con el kill switch puesto esperando que vuelva la VPN antes de soltarlo
PHYSICAL = ("802-11-wireless", "802-3-ethernet", "gsm", "cdma", "bond", "vlan", "bridge", "pppoe")
DEFAULTS = {"enabled": "off", "auto": "on", "manual_mode": "insecure", "killswitch": "on",
            "pool": "", "bypass_secs": "120",
            # endurecimiento por conexión (Settings → Network security)
            "dns": "off",                   # off | opportunistic | strict (DNS over TLS por conexión física)
            "ipv6_unsafe": "off",           # off = IPv6 apagado en redes inseguras (sin fugas ni dirección que delate)
            "autoconnect_unsafe": "off",    # off = una red insegura o nueva no se reconecta sola
            "ap_check": "on",               # detectar evil twin: access point o seguridad distintos a los conocidos
            "ports_warn": "on"}             # avisar de puertos escuchando en una red insegura
DOT4 = "9.9.9.9#dns.quad9.net,149.112.112.112#dns.quad9.net"
DOT6 = "2620:fe::fe#dns.quad9.net,2620:fe::9#dns.quad9.net"
# Lo que se toca de cada conexión además de zona/mDNS/DHCP: se guarda el valor original para restaurarlo
SNAP_KEYS = ("ipv6.method", "connection.autoconnect", "connection.dns-over-tls", "ipv4.ignore-auto-dns",
             "ipv4.dns", "ipv6.ignore-auto-dns", "ipv6.dns")
SEC_NAMES = {0: "open", 1: "weak (WEP/OWE)", 2: "WPA2", 3: "WPA3"}
POLL = 3
sys.path.insert(0, str(DOTFILES / "tools"))


# ── config ────────────────────────────────────────────────

def read_kv(path: Path, defaults: Optional[dict] = None) -> dict:
    out = dict(defaults or {})
    try:
        for line in path.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                out[k.strip()] = v.split("  #", 1)[0].strip()
    except OSError:
        pass
    return out


def write_kv(path: Path, updates: dict, header: str = "", remove: tuple = ()) -> None:
    """Cambia/agrega/borra claves conservando comentarios (temporal + os.replace)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        lines = [header] if header else []
    left = dict(updates)
    out = []
    for line in lines:
        k = line.partition("=")[0].strip()
        if "=" in line and not k.startswith("#"):
            if k in remove:
                continue
            if k in left:
                v = left.pop(k)
                comment = line.split("  #", 1)[1] if "  #" in line else ""
                line = f"{k}={v}" + (f"  #{comment}" if comment else "")
        out.append(line)
    out += [f"{k}={v}" for k, v in left.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(out) + "\n")
    os.replace(tmp, path)


def load_conf() -> dict:
    return read_kv(CONF, DEFAULTS)


def pool(conf: Optional[dict] = None) -> list[str]:
    return [p.strip() for p in (conf or load_conf()).get("pool", "").split(",") if p.strip()]


def networks() -> dict[str, str]:
    """{uuid: trusted|untrusted}, más reglas por nombre: `name:<prefijo>` vale para
    toda conexión cuyo nombre empiece así (sin distinguir mayúsculas), p. ej.
    `name:Cafe=trusted` cubre "Cafe - Centro"."""
    return {k: v for k, v in read_kv(NETWORKS).items() if v in ("trusted", "untrusted")}


def trust_of(c: dict, nets: dict) -> str:
    """trusted | untrusted | new de una conexión: primero su uuid, después las
    reglas por prefijo de nombre (la más larga gana)."""
    if c["uuid"] in nets:
        return nets[c["uuid"]]
    name = c.get("name", "").lower()
    rules = sorted(((k[5:].lower(), v) for k, v in nets.items() if k.startswith("name:")),
                   key=lambda kv: -len(kv[0]))
    return next((v for prefix, v in rules if prefix and name.startswith(prefix)), "new")


def network_names() -> dict[str, str]:
    """{uuid: nombre} del comentario de cada línea de networks.conf."""
    out = {}
    try:
        for line in NETWORKS.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and "  # " in v:
                out[k.strip()] = v.split("  # ", 1)[1].strip()
    except OSError:
        pass
    return out


def set_network(uuid: str, trust: Optional[str], name: str = "") -> None:
    if trust is None:
        write_kv(NETWORKS, {}, remove=(uuid,))
    else:
        write_kv(NETWORKS, {uuid: f"{trust}  # {name}" if name else trust},
                 header="# networks.conf — redes conocidas (uuid de NetworkManager). Lo escribe netguard/Settings.")


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    os.replace(tmp, STATE)


def installed() -> bool:
    return APPLY.exists() and AUTH.exists() and Path("/usr/share/polkit-1/actions/org.dotfiles.netguard.policy").exists()


def helper_version() -> int:
    """Versión del helper instalado (0 = no hay; 1 = anterior, sin marca de armado)."""
    try:
        m = re.search(r"^HELPER_VERSION = (\d+)", HELPER.read_text(), re.M)
    except OSError:
        return 0
    return int(m.group(1)) if m else 1


def history(ev: str, **data) -> None:
    """Evento del historial de redes (Settings → Network security → History). Se recorta solo."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if HISTORY.exists() and HISTORY.stat().st_size > 1_000_000:
            HISTORY.write_text("\n".join(HISTORY.read_text().splitlines()[-4000:]) + "\n")
        with HISTORY.open("a") as f:
            f.write(json.dumps({"t": int(time.time()), "ev": ev, **data}) + "\n")
    except OSError:
        pass


def read_history(limit: int = 1000) -> list[dict]:
    try:
        lines = HISTORY.read_text().splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def ap_security(flags: int, wpa: int, rsn: int) -> int:
    """0 abierta · 1 WEP/OWE · 2 WPA2 (PSK/802.1X) · 3 WPA3 (SAE), según los flags de NM."""
    k = wpa | rsn
    if k & 0x400:
        return 3
    if k & (0x100 | 0x200):
        return 2
    if k & 0x800 or flags & 1:
        return 1
    return 0


def load_aps() -> dict[str, tuple[int, list[str]]]:
    """{uuid: (nivel de seguridad, [bssid...])} de las redes de confianza."""
    out = {}
    for uuid, v in read_kv(APS).items():
        parts = v.split()
        if parts and parts[0].isdigit():
            out[uuid] = (int(parts[0]), [b.upper() for b in parts[1:]])
    return out


def save_ap(uuid: str, sec: int, bssid: str, name: str = "") -> None:
    known = load_aps().get(uuid, (sec, []))
    bssids = sorted(set(known[1]) | {bssid.upper()})
    write_kv(APS, {uuid: " ".join([str(max(sec, known[0]))] + bssids) + (f"  # {name}" if name else "")},
             header="# aps.conf — access points conocidos de cada red de confianza (netguard). <uuid>=<seguridad> <bssid>...")


# Escuchas normales que no son un servicio expuesto: clientes DHCP y mDNS (se apaga en redes inseguras)
PORTS_IGNORE = {("udp", 68), ("udp", 546), ("udp", 5353)}


def listening(ss_out: str) -> list[dict]:
    """Sockets escuchando fuera de loopback, de `ss -Htulnp`: [{proto, port, addr, proc}]."""
    out, seen = [], set()
    for line in ss_out.splitlines():
        f = line.split()
        if len(f) < 5:
            continue
        proto, local = f[0], f[4]
        addr, _, port = local.rpartition(":")
        addr = addr.strip("[]").split("%")[0]
        if not port.isdigit() or addr.startswith("127.") or addr == "::1":
            continue
        key = (proto, int(port))
        if key in seen or key in PORTS_IGNORE:
            continue
        seen.add(key)
        m = re.search(r'users:\(\("([^"]+)"', line)
        out.append({"proto": proto, "port": int(port), "addr": addr or "*", "proc": m.group(1) if m else ""})
    return sorted(out, key=lambda p: (p["proto"], p["port"]))


def same_device(a: str, b: str) -> bool:
    """Mismo equipo: un router dual-band anuncia BSSIDs que solo cambian en el último octeto."""
    return a.upper()[:14] == b.upper()[:14]


def log(msg: str) -> None:
    """Log propio (el stderr de un exec-once no lo lee nadie). Se recorta solo."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 200_000:
            LOG.write_text("\n".join(LOG.read_text().splitlines()[-1000:]) + "\n")
        with LOG.open("a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


# ── root (pkexec) ─────────────────────────────────────────

def root_apply(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["pkexec", str(APPLY), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def authenticate(*args: str) -> bool:
    """Huella o contraseña (agente de polkit). Sin args: solo verifica."""
    try:
        return subprocess.run(["pkexec", str(AUTH), *(args or ("check",))], capture_output=True,
                              timeout=120).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def root_status() -> dict:
    """Estado real (con root). Solo al arrancar el daemon: después el daemon lleva
    la cuenta él mismo (es el único que arma/desarma) y lee el bypass de
    /run/netguard/bypass_until, que es legible sin root."""
    r = root_apply("status")
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {}


def run_ok(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def bypass_until() -> int:
    try:
        return int(Path("/run/netguard/bypass_until").read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


# ── NetworkManager (D-Bus) ────────────────────────────────

class NM:
    def __init__(self) -> None:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        self.GLib = GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)

    def call(self, path: str, iface: str, method: str, args=None):
        try:
            return self.bus.call_sync("org.freedesktop.NetworkManager", path, iface, method, args, None, 0, 4000,
                                      None).unpack()
        except self.GLib.Error:
            return None

    def props(self, path: str, iface: str) -> dict:
        r = self.call(path, "org.freedesktop.DBus.Properties", "GetAll", self.GLib.Variant("(s)", (iface,)))
        return r[0] if r else {}

    def active(self) -> list[dict]:
        out = []
        for a in self.props("/org/freedesktop/NetworkManager", "org.freedesktop.NetworkManager") \
                .get("ActiveConnections", []):
            p = self.props(a, "org.freedesktop.NetworkManager.Connection.Active")
            if not p:
                continue
            devs, ap = [], None
            for d in p.get("Devices", []):
                dp = self.props(d, "org.freedesktop.NetworkManager.Device")
                if dp.get("Interface"):
                    devs.append(dp["Interface"])
                if dp.get("DeviceType") == 2 and ap is None:      # Wi-Fi: el access point al que está asociado
                    path = self.props(d, "org.freedesktop.NetworkManager.Device.Wireless").get("ActiveAccessPoint")
                    a = self.props(path, "org.freedesktop.NetworkManager.AccessPoint") if path and path != "/" else {}
                    if a.get("HwAddress"):
                        ap = {"bssid": a["HwAddress"].upper(),
                              "sec": ap_security(a.get("Flags", 0), a.get("WpaFlags", 0), a.get("RsnFlags", 0))}
            out.append({"name": p.get("Id", ""), "uuid": p.get("Uuid", ""), "type": p.get("Type", ""),
                        "devs": devs, "state": p.get("State", 0), "settings": p.get("Connection", ""), "ap": ap})
        return out

    def settings(self, path: str) -> dict:
        r = self.call(path, "org.freedesktop.NetworkManager.Settings.Connection", "GetSettings")
        return r[0] if r else {}

    def all_settings(self) -> list[dict]:
        r = self.call("/org/freedesktop/NetworkManager/Settings", "org.freedesktop.NetworkManager.Settings",
                      "ListConnections")
        return [self.settings(p) for p in (r[0] if r else [])]


def physical(conns: list[dict]) -> list[dict]:
    return [c for c in conns if c["type"] in PHYSICAL and c["state"] == 2]   # 2 = activated


# ── VPN ───────────────────────────────────────────────────

def entry_kind(e: str) -> str:
    """wg (WireGuard de NM) · ovpn:<nombre> (OpenVPN de NM: respaldo "stealth" por TCP 443 para redes que
    bloquean WireGuard) · forti:<perfil> · citrix. wg y ovpn se conectan solas; forti y citrix, a mano."""
    if e.startswith("forti:"):
        return "forti"
    if e == "citrix":
        return "citrix"
    return "ovpn" if e.startswith("ovpn:") else "wg"


AUTO_KINDS = ("wg", "ovpn")


def nm_name(e: str) -> str:
    """Nombre de la conexión de NetworkManager de una entrada wg/ovpn del pool."""
    return e[5:] if e.startswith("ovpn:") else e


def auto_entries(conf: dict) -> list[str]:
    """Las que se conectan solas, en el orden de failover: primero WireGuard, después OpenVPN."""
    p = pool(conf)
    return [e for e in p if entry_kind(e) == "wg"] + [e for e in p if entry_kind(e) == "ovpn"]


def forti_up() -> Optional[str]:
    try:
        from vpn_tui import forti_status_detail
        up, name = forti_status_detail()
        return name if up else None
    except Exception:  # noqa: BLE001
        return None


def citrix_up() -> bool:
    try:
        from vpn_tui import citrix_connected
        return citrix_connected()
    except Exception:  # noqa: BLE001
        return False


def resolve(host: str) -> list[str]:
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except OSError:
        return []


def endpoint_hosts(nm: NM, entries: list[str]) -> list[str]:
    """Hosts/IPs a los que hay que poder llegar sin túnel para levantar uno."""
    hosts = []
    wg = {e for e in entries if entry_kind(e) == "wg"}
    ovpn = {nm_name(e) for e in entries if entry_kind(e) == "ovpn"}
    for s in nm.all_settings():
        c = s.get("connection", {})
        if c.get("type") == "wireguard" and c.get("id") in wg:
            for peer in s.get("wireguard", {}).get("peers", []):
                ep = peer.get("endpoint", "")
                hosts.append(ep.rsplit(":", 1)[0].strip("[]"))
        elif c.get("type") == "vpn" and c.get("id") in ovpn:
            # OpenVPN: vpn.data["remote"] = "host[:puerto[:proto]], host2 …"
            for r in re.split(r"[,\s]+", s.get("vpn", {}).get("data", {}).get("remote", "")):
                if r:
                    hosts.append(r.strip("[]") if r.count(":") > 2 else r.split(":", 1)[0])
    for e in entries:
        if entry_kind(e) == "forti":
            r = subprocess.run(["fortivpn", "view", e[6:]], capture_output=True, text=True, timeout=6) \
                if shutil_which("fortivpn") else None
            m = re.search(r"Remote Gateway:\s*([^\s:]+)", r.stdout if r else "")
            if m:
                hosts.append(m.group(1))
        elif e == "citrix":
            try:
                from vpn_tui import citrix_login_url
                url = citrix_login_url() or ""
                m = re.match(r"\w+://([^/:]+)", url)
                if m:
                    hosts.append(m.group(1))
            except Exception:  # noqa: BLE001
                pass
    return [h for h in hosts if h]


def is_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def shutil_which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


def notify(title: str, body: str = "", urgency: str = "normal", actions: tuple = ()) -> str:
    args = ["notify-send", "-a", "Network zones", "-i", "security-high", "-u", urgency]
    for key, label in actions:
        args += ["-A", f"{key}={label}"]
    try:
        r = subprocess.run(args + [title, body], capture_output=True, text=True,
                           timeout=600 if actions else 10)
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ── daemon ────────────────────────────────────────────────

class Guard:
    def __init__(self) -> None:
        self.nm = NM()
        self.mode = ""                  # safe | insecure | off
        self.applied: dict = {}         # uuid → modo aplicado a esa conexión
        self.asked: set[str] = set()
        self.endpoints: list[str] = read_state().get("endpoints", [])
        prev = read_state()
        self.stopped_kdeconnect = bool(prev.get("stopped_kdeconnect"))   # sobrevive a reiniciar el daemon
        self.stopped_avahi = bool(prev.get("stopped_avahi"))
        self.next_vpn_try = 0.0
        self.last_forti = (0.0, None)
        self.stopped_bt = bool(prev.get("stopped_bt"))
        self.modified: set[str] = set(prev.get("modified", []))   # conexiones a restaurar al apagar
        self.orig: dict[str, dict] = prev.get("orig", {})            # valores originales (SNAP_KEYS) por conexión
        self.pending: dict[str, dict] = prev.get("pending", {})      # cambios de perfil para cuando se desconecte
        self.asked_aps: set[str] = set()
        self.prev_conns: dict[str, str] = {}
        self.prev_vpn: set[str] = set()
        self.prev_armed: Optional[bool] = None
        self.next_ports = 0.0
        self.ports: list[dict] = []
        self.st: dict = {}
        self.warned: set[str] = set()   # avisos que ya se mostraron (uno por situación)
        self.next_arm_try = 0.0
        self.next_disarm_try = 0.0
        self.vpn_lost_at = 0.0
        self.last_error = prev.get("last_error", "")
        self.helper_v = helper_version()
        if self.helper_v >= 2:
            self.armed = ARMED_FLAG.exists()
        else:   # helper viejo: una sola consulta con root, al arrancar
            self.armed = bool((root_status() if installed() else {}).get("killswitch"))
        log(f"daemon started (helper v{self.helper_v}, kill switch {'armed' if self.armed else 'off'})")

    # decisiones
    def trust(self, c: dict, nets: dict, conf: dict, aps: dict) -> tuple[str, str]:
        """(trusted | untrusted | new | suspicious, motivo). Una red de confianza por Wi-Fi se compara
        con sus access points conocidos: otro BSSID o menos seguridad = posible evil twin."""
        t = trust_of(c, nets)
        ap = c.get("ap")
        if t != "trusted" or conf.get("ap_check") != "on" or not ap:
            return t, ""
        known = aps.get(c["uuid"])
        if not known:       # primera vez que se la ve con esta función: se aprende el access point
            save_ap(c["uuid"], ap["sec"], ap["bssid"], c["name"])
            history("ap_learned", name=c["name"], uuid=c["uuid"], bssid=ap["bssid"], sec=SEC_NAMES[ap["sec"]])
            return "trusted", ""
        sec, bssids = known
        if ap["sec"] < sec:
            return "suspicious", f"{c['name']}: security dropped ({SEC_NAMES[sec]} → {SEC_NAMES[ap['sec']]})"
        if not any(same_device(ap["bssid"], b) for b in bssids):
            self.ask_ap(c)
            return "suspicious", f"{c['name']}: unknown access point {ap['bssid']}"
        return "trusted", ""

    def decide(self, conf: dict, conns: list[dict], trust: dict) -> tuple[str, str]:
        if conf.get("enabled") != "on" or not installed():
            return "off", "network zones are off" if conf.get("enabled") != "on" else "not set up"
        if conf.get("auto") != "on":
            m = conf.get("manual_mode", "insecure")
            return (m if m in ("safe", "insecure") else "insecure"), "set by hand"
        if not conns:
            return (self.mode if self.mode in ("safe", "insecure") else "insecure"), "offline"
        bad = [c for c in conns if trust[c["uuid"]][0] != "trusted"]
        if bad:
            why = [trust[c["uuid"]][1] for c in bad if trust[c["uuid"]][0] == "suspicious"]
            if why:
                return "insecure", "possible fake network: " + "; ".join(why)
            names = ", ".join(c["name"] for c in bad)
            return "insecure", f"untrusted: {names}" if all(trust[c["uuid"]][0] == "untrusted" for c in bad) \
                else f"new network: {names}"
        return "safe", "trusted: " + ", ".join(c["name"] for c in conns)

    def ask_ap(self, c: dict) -> None:
        """Access point desconocido en una red de confianza: preguntar una vez por BSSID."""
        ap = c["ap"]
        if ap["bssid"] in self.asked_aps:
            return
        self.asked_aps.add(ap["bssid"])
        history("suspicious", name=c["name"], uuid=c["uuid"], bssid=ap["bssid"], sec=SEC_NAMES[ap["sec"]])
        log(f"unknown access point {ap['bssid']} for trusted network {c['name']}")

        def run() -> None:
            ans = notify(f"Unknown access point: {c['name']}",
                         f"Same name, different access point ({ap['bssid']}, {SEC_NAMES[ap['sec']]}). It may be a "
                         "fake network (evil twin): treated as UNSAFE.\nMiddle-click to choose.", "critical",
                         (("same", "It is my network (new router/AP)"), ("unsafe", "Keep it unsafe")))
            if ans == "same" and authenticate():
                save_ap(c["uuid"], ap["sec"], ap["bssid"], c["name"])
                history("ap_learned", name=c["name"], uuid=c["uuid"], bssid=ap["bssid"], sec=SEC_NAMES[ap["sec"]])
        threading.Thread(target=run, daemon=True).start()

    def ask(self, c: dict) -> None:
        """Notificación por red nueva (en un hilo: espera la respuesta)."""
        def run() -> None:
            ans = notify(f"New network: {c['name']}", "Treated as UNSAFE until you say otherwise.\n"
                         "Middle-click to choose.", "critical",
                         (("trusted", "Trusted (home, office)"), ("untrusted", "Untrusted (public)")))
            if ans == "trusted":
                if authenticate():
                    set_network(c["uuid"], "trusted", c["name"])
                else:
                    notify(f"{c['name']} stays untrusted", "Authentication failed or cancelled.")
            elif ans == "untrusted":
                set_network(c["uuid"], "untrusted", c["name"])
        threading.Thread(target=run, daemon=True).start()

    # aplicar
    def nmcli(self, *args: str) -> None:
        subprocess.run(["nmcli", *args], capture_output=True, timeout=20)

    def snapshot(self, uuid: str) -> None:
        """Guarda una vez los valores originales de SNAP_KEYS (se restauran al apagar las zonas)."""
        if uuid in self.orig:
            return
        try:
            r = subprocess.run(["nmcli", "-g", ",".join(SNAP_KEYS), "connection", "show", uuid],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return
        if r.returncode == 0:
            vals = r.stdout.split("\n")
            self.orig[uuid] = {k: (vals[i] if i < len(vals) else "").replace("\\:", ":")
                               for i, k in enumerate(SNAP_KEYS)}

    def desired(self, uuid: str, mode: str, trusted: bool, conf: dict, bypassing: bool) -> tuple[dict, dict]:
        """(lo que se aplica en vivo con `device reapply`, lo que va al perfil cuando se desconecte)."""
        safe, o = mode == "safe", self.orig.get(uuid, {})
        # mDNS/LLMNR por conexión (NetworkManager se lo pasa a systemd-resolved); "default" = config global
        live = {"connection.zone": "home" if safe else "drop",
                "ipv4.dhcp-send-hostname": "yes" if safe else "no", "ipv6.dhcp-send-hostname": "yes" if safe else "no",
                "connection.mdns": "default" if safe else "no", "connection.llmnr": "default" if safe else "no"}
        # IPv6 apagado en una red que no es de confianza: el kill switch ya lo corta, así tampoco hay
        # dirección que delate ni fugas si la VPN es solo IPv4
        live["ipv6.method"] = "disabled" if not trusted and conf.get("ipv6_unsafe") != "on" \
            else (o.get("ipv6.method") or "auto")
        dns = conf.get("dns", "off")
        orig_dns = {"connection.dns-over-tls": o.get("connection.dns-over-tls") or "-1",
                    "ipv4.ignore-auto-dns": o.get("ipv4.ignore-auto-dns") or "no", "ipv4.dns": o.get("ipv4.dns", ""),
                    "ipv6.ignore-auto-dns": o.get("ipv6.ignore-auto-dns") or "no", "ipv6.dns": o.get("ipv6.dns", "")}
        if dns == "strict" and not bypassing:   # durante un bypass el portal cautivo necesita el DNS de la red
            live.update({"connection.dns-over-tls": "yes", "ipv4.ignore-auto-dns": "yes", "ipv4.dns": DOT4,
                         "ipv6.ignore-auto-dns": "yes", "ipv6.dns": DOT6})
        else:
            live.update(orig_dns)
            if dns == "opportunistic" and not bypassing:
                live["connection.dns-over-tls"] = "opportunistic"
        # Una red insegura o nueva no se reconecta sola. `autoconnect` no se puede reaplicar con la
        # conexión activa: se guarda en el perfil cuando se desconecta
        profile = {"connection.autoconnect": "no" if not trusted and conf.get("autoconnect_unsafe") != "on"
                   else (o.get("connection.autoconnect") or "yes")}
        return live, profile

    def apply_conn(self, c: dict, mode: str, trusted: bool, conf: dict, bypassing: bool) -> None:
        self.snapshot(c["uuid"])
        live, profile = self.desired(c["uuid"], mode, trusted, conf, bypassing)
        key = json.dumps([live, profile], sort_keys=True)
        if self.applied.get(c["uuid"]) == key:
            return
        self.nmcli("connection", "modify", "uuid", c["uuid"], *[x for kv in live.items() for x in kv])
        for d in c["devs"]:
            r = subprocess.run(["nmcli", "device", "reapply", d], capture_output=True, text=True, timeout=20)
            if r.returncode != 0:
                self.error(f"reapply {d}: {(r.stderr or r.stdout).strip()[:140]}")
        self.pending[c["uuid"]] = profile
        self.applied[c["uuid"]] = key
        self.modified.add(c["uuid"])

    def flush_pending(self, active_uuids: set[str]) -> None:
        """Aplica los cambios de perfil (autoconnect) de las conexiones que ya no están activas."""
        for uuid in [u for u in self.pending if u not in active_uuids]:
            self.nmcli("connection", "modify", "uuid", uuid, *[x for kv in self.pending.pop(uuid).items() for x in kv])

    def check_ports(self, fw: bool) -> None:
        """Qué escucha fuera de loopback. Sin firewalld, en una red insegura eso está expuesto: se avisa."""
        try:
            out = subprocess.run(["ss", "-Htulnp"], capture_output=True, text=True, timeout=5).stdout
        except (OSError, subprocess.TimeoutExpired):
            return
        self.ports = listening(out)
        if fw:
            return
        for p in self.ports:
            self.warn_once(f"port:{p['proto']}:{p['port']}", f"Open port on an untrusted network: {p['proto']}/{p['port']}",
                           f"{p['proc'] or 'A system service'} listens on {p['addr']} and firewalld is stopped, so it "
                           "is reachable from this network. Settings → Network security → Ports.")

    def set_discovery(self, on: bool, avahi_was_on: bool) -> None:
        if not on:
            if avahi_was_on:
                self.stopped_avahi = True
            root_apply("discovery", "off")
            if subprocess.run(["pkill", "-x", "kdeconnectd"], capture_output=True).returncode == 0:
                self.stopped_kdeconnect = True
            subprocess.run(["pkill", "-x", "wayvnc"], capture_output=True)
            subprocess.run(["bluetoothctl", "pairable", "off"], capture_output=True, timeout=5)
            subprocess.run(["bluetoothctl", "discoverable", "off"], capture_output=True, timeout=5)
            self.stopped_bt = True
            return
        if self.stopped_bt:
            subprocess.run(["bluetoothctl", "pairable", "on"], capture_output=True, timeout=5)
            self.stopped_bt = False
        if self.stopped_avahi:
            root_apply("discovery", "on")
            self.stopped_avahi = False
        if self.stopped_kdeconnect:
            subprocess.Popen(["kdeconnectd"], start_new_session=True, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            self.stopped_kdeconnect = False

    def can_arm(self, conf: dict) -> bool:
        """Nunca armar el kill switch si no hay con qué salir: sin una WireGuard en
        el pool (las únicas que se conectan solas) o sin sus endpoints, armarlo deja
        la máquina sin red. En ese caso se avisa una vez y no se bloquea."""
        ok = bool(auto_entries(conf)) and bool(self.endpoints)
        if not ok:
            self.warn_once("nopool", "Kill switch NOT armed", "There is no WireGuard VPN in the pool (or its "
                           "server could not be resolved). Add one in Settings → Firewall → Zones.")
        else:
            self.warned.discard("nopool")
        return ok

    def warn_once(self, key: str, title: str, body: str, urgency: str = "critical") -> None:
        if key not in self.warned:
            self.warned.add(key)
            log(f"{title}: {body}")
            history("warning", title=title)
            notify(title, body, urgency)

    def error(self, msg: str) -> None:
        self.last_error = f"{time.strftime('%H:%M')} {msg}"
        log("ERROR " + msg)

    def restore_conns(self) -> None:
        """Al apagar las zonas: las conexiones vuelven a como estaban (zona por
        defecto, nombre por DHCP, mDNS/LLMNR según resolved)."""
        for uuid in sorted(self.modified | set(self.applied)):
            o = self.orig.get(uuid, {})
            back = {"connection.zone": "", "ipv4.dhcp-send-hostname": "yes", "ipv6.dhcp-send-hostname": "yes",
                    "connection.mdns": "default", "connection.llmnr": "default"}
            back.update({k: v for k, v in o.items() if k in SNAP_KEYS})
            if "connection.autoconnect" in back and not back["connection.autoconnect"]:
                back["connection.autoconnect"] = "yes"
            self.nmcli("connection", "modify", "uuid", uuid, *[x for kv in back.items() for x in kv])
        if self.modified:
            log(f"restored {len(self.modified)} connection(s)")
        self.applied.clear()
        self.modified.clear()
        self.pending.clear()
        self.orig.clear()

    def arm(self, conf: dict) -> bool:
        """Arma solo si el helper confirma (código 0). Devuelve si quedó armado."""
        self.refresh_endpoints(conf, arm=False, push=False)
        if not self.can_arm(conf):
            return False
        r = root_apply("killswitch", "on", *self.endpoints)
        if r.returncode != 0:
            self.error(f"could not arm the kill switch: {(r.stderr or r.stdout).strip()[:160]}")
            self.warn_once("armfail", "Kill switch could not be armed", "Traffic is NOT blocked. "
                           "Settings → Firewall → Zones shows the error.")
            return False
        self.warned.discard("armfail")
        self.armed = True
        log(f"kill switch armed ({len(self.endpoints)} endpoint(s))")
        return True

    def disarm(self) -> bool:
        """Desarma y verifica. Si falla, sigue figurando armado (es la verdad) y se reintenta."""
        r = root_apply("killswitch", "off")
        if r.returncode != 0 and not (self.helper_v >= 2 and not ARMED_FLAG.exists()):
            self.error(f"could not disarm the kill switch: {(r.stderr or r.stdout).strip()[:160]}")
            self.next_disarm_try = time.time() + 10
            self.warn_once("disarmfail", "Kill switch still on", "Could not lift it. Emergency: "
                           "`netguard.py off`, or `sudo nft delete table inet netguard`.")
            return False
        self.warned.discard("disarmfail")
        self.armed = False
        log("kill switch disarmed")
        return True

    def refresh_endpoints(self, conf: dict, arm: bool, push: bool = True) -> None:
        ips = []
        for h in endpoint_hosts(self.nm, pool(conf)):
            ips += [h] if is_ip(h) else resolve(h)
        if ips:     # sin DNS (kill switch armado, sin túnel) se quedan los últimos conocidos
            self.endpoints = sorted(set(ips))
        if push and self.armed:
            root_apply("killswitch", "refresh", *self.endpoints)

    def vpn_state(self, conf: dict, active: list[dict]) -> list[str]:
        """Entradas del pool conectadas ahora."""
        up = []
        names = {c["name"] for c in active if c["type"] in ("wireguard", "vpn") and c["state"] == 2}
        for e in pool(conf):
            k = entry_kind(e)
            if k in AUTO_KINDS and nm_name(e) in names:
                up.append(e)
            elif k == "forti":
                t, name = self.last_forti
                if time.time() - t > 15:
                    self.last_forti = (time.time(), forti_up())
                if self.last_forti[1] == e[6:]:
                    up.append(e)
            elif k == "citrix" and citrix_up():
                up.append(e)
        return up

    def connect_wg(self, name: str) -> bool:
        r = subprocess.run(["nmcli", "connection", "up", "id", name], capture_output=True, text=True, timeout=40)
        return r.returncode == 0

    def ensure_vpn(self, conf: dict, retry_secs: int = 60) -> bool:
        """Intenta las WireGuard del pool (la preferida primero). True si alguna levantó."""
        if time.time() < self.next_vpn_try:
            return False
        wg = auto_entries(conf)
        if not wg:
            self.warn_once("nopool", "Untrusted network: no VPN in the pool",
                           "Traffic is NOT protected. Add a WireGuard VPN in Settings → Firewall → Zones.")
            return False
        pref = read_state().get("vpn_pref")
        order = ([pref] if pref in wg else []) + [e for e in wg if e != pref]
        for e in order:
            if self.connect_wg(nm_name(e)):
                log(f"VPN connected: {e}")
                self.warned.discard("novpn")
                notify(f"VPN connected: {e}", "Untrusted network: traffic goes through the VPN.")
                return True
            log(f"VPN {e} did not connect")
        self.next_vpn_try = time.time() + retry_secs
        return False

    def switch_vpn(self, conf: dict, target: str, active: list[dict]) -> None:
        """Cambia de VPN con el kill switch armado (no hay hueco sin cifrar)."""
        st = read_state()
        st["vpn_pref"] = target
        write_state(st)
        if entry_kind(target) not in AUTO_KINDS:
            return      # Forti/Citrix: login interactivo desde Settings
        mine = {nm_name(e) for e in auto_entries(conf)}
        for c in active:
            if c["type"] in ("wireguard", "vpn") and c["name"] in mine and c["name"] != nm_name(target):
                self.nmcli("connection", "down", "id", c["name"])
        if not self.connect_wg(nm_name(target)):
            notify(f"Could not connect {target}", "Trying the next VPN in the pool.", "critical")

    def handle_request(self, conf: dict, active: list[dict]) -> None:
        try:
            req = json.loads(REQUEST.read_text())
            REQUEST.unlink()
        except (OSError, ValueError):
            return
        if req.get("vpn"):
            self.switch_vpn(conf, req["vpn"], active)

    def tick(self) -> None:
        conf, nets, aps = load_conf(), networks(), load_aps()
        active = self.nm.active()
        conns = physical(active)
        trust = {c["uuid"]: self.trust(c, nets, conf, aps) for c in conns}
        mode, reason = self.decide(conf, conns, trust)
        if mode != "off" and conf.get("auto") == "on":
            for c in conns:
                if trust[c["uuid"]][0] == "new" and c["uuid"] not in self.asked:
                    self.asked.add(c["uuid"])
                    self.ask(c)
        # Historial: redes que aparecen y se van
        now_conns = {c["uuid"]: c["name"] for c in conns}
        for c in conns:
            if c["uuid"] not in self.prev_conns:
                history("connect", name=c["name"], uuid=c["uuid"], type=c["type"],
                        bssid=(c.get("ap") or {}).get("bssid", ""), trust=trust[c["uuid"]][0])
        for uuid, name in self.prev_conns.items():
            if uuid not in now_conns:
                history("disconnect", name=name, uuid=uuid)
        self.prev_conns = now_conns
        self.flush_pending({c["uuid"] for c in active})
        self.handle_request(conf, active)
        until = bypass_until()
        bypassing = until > time.time()
        now = time.time()
        if self.helper_v >= 2:
            self.armed = ARMED_FLAG.exists()     # estado real (el helper borra la marca en un bypass)
        elif bypassing:
            self.armed = False
        rs = {"avahi": run_ok(["systemctl", "is-active", "--quiet", "avahi-daemon"])}

        if mode != self.mode:
            log(f"mode {self.mode or '-'} → {mode} ({reason})")
            history("mode", frm=self.mode or "", to=mode, reason=reason)
            self.next_ports = 0.0     # revisar puertos ya, no en 30 s
            if mode == "insecure":
                self.set_discovery(False, bool(rs.get("avahi")))
            else:       # safe u off: descubrimiento de vuelta
                self.set_discovery(True, False)
                if mode == "off":
                    self.restore_conns()
            prev, self.mode = self.mode, mode
            self.vpn_lost_at = 0.0
            self.warned -= {"novpn", "vpndown", "firewalld"}
            if prev and mode != "off":
                notify("Untrusted network: protection on" if mode == "insecure" else "Trusted network",
                       reason if mode == "insecure" else "VPN optional, discovery back on.")
        if mode in ("safe", "insecure"):
            for c in conns:
                self.apply_conn(c, mode, trust[c["uuid"]][0] == "trusted", conf, bypassing)

        fw = run_ok(["systemctl", "is-active", "--quiet", "firewalld"])
        up = self.vpn_state(conf, active) if mode == "insecure" else []
        if fw != getattr(self, "prev_fw", fw):
            self.next_ports = 0.0       # firewalld cambió: lo expuesto cambió también
        self.prev_fw = fw
        if mode != "off" and now >= self.next_ports:
            self.next_ports = now + 30
            if mode == "insecure" and conf.get("ports_warn") == "on":
                self.check_ports(fw)
            else:
                self.ports = []
        if mode == "insecure":
            if not fw:
                self.warn_once("firewalld", "firewalld is stopped", "Incoming connections are not blocked on "
                               "this untrusted network. Start it in Settings → Firewall → Rules.")
            ks = conf.get("killswitch") == "on"
            if bypassing:
                pass                                    # el bypass manda: ni armar ni conectar
            elif up:
                # Con la VPN arriba recién se bloquea lo demás (nunca antes: sin VPN quedaría sin red)
                self.vpn_lost_at = 0.0
                self.warned -= {"novpn", "vpndown"}
                if ks and not self.armed and now >= self.next_arm_try and not self.arm(conf):
                    self.next_arm_try = now + 30
                elif not ks and self.armed and now >= self.next_disarm_try:
                    self.disarm()
            elif self.armed:
                # La VPN se cayó con el kill switch puesto: no hay fuga mientras reconecta. Si en
                # VPN_GRACE segundos no vuelve, se suelta (sin VPN no se bloquea) y se avisa.
                if not self.vpn_lost_at:
                    self.vpn_lost_at = now
                    log("VPN dropped with the kill switch armed: reconnecting")
                if not self.ensure_vpn(conf, retry_secs=10) and now - self.vpn_lost_at > VPN_GRACE:
                    if self.disarm():
                        self.warn_once("vpndown", "VPN down: traffic NOT protected",
                                       "No VPN of the pool came back, so nothing is blocked. "
                                       "Retrying every minute.")
            else:
                # Sin VPN y sin bloqueo: primero conectar; con la VPN arriba, el próximo tick arma
                if not self.ensure_vpn(conf) and auto_entries(conf) \
                        and "vpndown" not in self.warned:
                    self.warn_once("novpn", "No VPN could connect", "Untrusted network: traffic is NOT "
                                   "blocked and NOT protected. Retrying every minute; Settings → Firewall "
                                   "to pick another VPN.")
            if up and int(now) % 300 < POLL:
                self.refresh_endpoints(conf, arm=False)     # con túnel hay DNS: actualizar IPs de los endpoints
        elif self.armed and now >= self.next_disarm_try:
            # Seguro o apagado: nada bloqueado (cubre también un rearmado que quedó de antes)
            self.disarm()
        # Historial: VPN y kill switch
        for e in set(up) - self.prev_vpn:
            history("vpn_up", name=e)
        for e in self.prev_vpn - set(up):
            history("vpn_down", name=e)
        self.prev_vpn = set(up)
        if self.prev_armed is not None and self.armed != self.prev_armed:
            history("killswitch", on=self.armed)
        self.prev_armed = self.armed
        self.st = {"mode": mode, "reason": reason, "auto": conf.get("auto") == "on",
                   "conns": [{"uuid": c["uuid"], "name": c["name"], "type": c["type"], "devs": c["devs"],
                              "trust": trust[c["uuid"]][0], "why": trust[c["uuid"]][1], "ap": c.get("ap")}
                             for c in conns],
                   "vpn_up": up, "killswitch": self.armed, "bypass_until": until,
                   "endpoints": self.endpoints, "vpn_pref": read_state().get("vpn_pref"), "time": time.time(),
                   "pid": os.getpid(), "stopped_kdeconnect": self.stopped_kdeconnect,
                   "stopped_avahi": self.stopped_avahi, "stopped_bt": self.stopped_bt,
                   "modified": sorted(self.modified), "firewalld": fw, "helper_version": self.helper_v,
                   "vpn_lost_at": self.vpn_lost_at, "last_error": self.last_error,
                   "orig": self.orig, "pending": self.pending, "ports": self.ports}
        write_state(self.st)

    def run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - el daemon no se cae por un error puntual
                print(f"netguard: {e}", file=sys.stderr)
            time.sleep(POLL)


def request(**kw) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REQUEST.write_text(json.dumps(kw))


def bypass(secs: Optional[int] = None) -> bool:
    secs = secs or int(load_conf().get("bypass_secs", "120") or 120)
    return authenticate("bypass", str(secs))


def main() -> None:
    cmd = sys.argv[1:] or ["status"]
    if cmd[0] == "daemon":
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        lock = open(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "netguard.lock", "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit(0)     # ya hay uno
        Guard().run()
    elif cmd[0] == "off":
        # Apagado de emergencia: sin huella, sin Settings, aunque el daemon esté trabado.
        # Desarma el kill switch, devuelve Avahi y deja las zonas apagadas (el daemon,
        # si corre, restaura las conexiones en su próximo tick).
        write_kv(CONF, {"enabled": "off"})
        log("emergency off")
        if APPLY.exists():
            r = root_apply("killswitch", "off")
            root_apply("discovery", "on")
            if r.returncode != 0:
                print("could not disarm through polkit; run: sudo nft delete table inet netguard", file=sys.stderr)
                sys.exit(1)
        print("network zones off: kill switch disarmed, nothing blocked")
    elif cmd[0] == "status":
        print(json.dumps(read_state(), indent=1))
    elif cmd[:2] == ["request", "vpn"] and len(cmd) == 3:
        request(vpn=cmd[2])
    elif cmd[0] == "bypass":
        sys.exit(0 if bypass(int(cmd[1]) if len(cmd) > 1 else None) else 1)
    elif cmd[0] == "captive":
        if bypass():
            subprocess.Popen(["xdg-open", "http://neverssl.com"], start_new_session=True)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
