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
estado en ~/.local/state/dotfiles/netguard/
(NETGUARD_CONF_DIR / NETGUARD_STATE para copias).
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
LIB = Path("/usr/local/lib/netguard")
APPLY, AUTH = LIB / "apply", LIB / "auth"
PHYSICAL = ("802-11-wireless", "802-3-ethernet", "gsm", "cdma", "bond", "vlan", "bridge", "pppoe")
DEFAULTS = {"enabled": "off", "auto": "on", "manual_mode": "insecure", "killswitch": "on",
            "pool": "", "bypass_secs": "120"}
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
            devs = [self.props(d, "org.freedesktop.NetworkManager.Device").get("Interface", "")
                    for d in p.get("Devices", [])]
            out.append({"name": p.get("Id", ""), "uuid": p.get("Uuid", ""), "type": p.get("Type", ""),
                        "devs": [d for d in devs if d], "state": p.get("State", 0),
                        "settings": p.get("Connection", "")})
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
    return "forti" if e.startswith("forti:") else "citrix" if e == "citrix" else "wg"


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
    for s in nm.all_settings():
        c = s.get("connection", {})
        if c.get("type") == "wireguard" and c.get("id") in wg:
            for peer in s.get("wireguard", {}).get("peers", []):
                ep = peer.get("endpoint", "")
                hosts.append(ep.rsplit(":", 1)[0].strip("[]"))
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
        self.vpn_fail_notified = False
        self.next_vpn_try = 0.0
        self.last_forti = (0.0, None)
        self.st: dict = {}
        self.warned_no_pool = False
        self.next_arm_try = 0.0
        rs = root_status() if installed() else {}     # una sola vez, al arrancar
        self.armed = bool(rs.get("killswitch"))

    # decisiones
    def decide(self, conf: dict, conns: list[dict], nets: dict) -> tuple[str, str]:
        if conf.get("enabled") != "on" or not installed():
            return "off", "network zones are off" if conf.get("enabled") != "on" else "not set up"
        if conf.get("auto") != "on":
            m = conf.get("manual_mode", "insecure")
            return (m if m in ("safe", "insecure") else "insecure"), "set by hand"
        if not conns:
            return (self.mode if self.mode in ("safe", "insecure") else "insecure"), "offline"
        bad = [c for c in conns if trust_of(c, nets) != "trusted"]
        if bad:
            names = ", ".join(c["name"] for c in bad)
            return "insecure", f"untrusted: {names}" if all(trust_of(c, nets) == "untrusted" for c in bad) \
                else f"new network: {names}"
        return "safe", "trusted: " + ", ".join(c["name"] for c in conns)

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

    def apply_conn(self, c: dict, mode: str) -> None:
        if self.applied.get(c["uuid"]) == mode:
            return
        # mDNS/LLMNR por conexión (NetworkManager se lo pasa a systemd-resolved);
        # "default" = lo que diga la config global de resolved
        safe = mode == "safe"
        self.nmcli("connection", "modify", "uuid", c["uuid"], "connection.zone", "home" if safe else "drop",
                   "ipv4.dhcp-send-hostname", "yes" if safe else "no",
                   "ipv6.dhcp-send-hostname", "yes" if safe else "no",
                   "connection.mdns", "default" if safe else "no", "connection.llmnr", "default" if safe else "no")
        for d in c["devs"]:
            self.nmcli("device", "reapply", d)
        self.applied[c["uuid"]] = mode

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
            return
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
        ok = any(entry_kind(e) == "wg" for e in pool(conf)) and bool(self.endpoints)
        if not ok and not self.warned_no_pool:
            self.warned_no_pool = True
            notify("Kill switch NOT armed", "There is no WireGuard VPN in the pool to connect to. "
                   "Add one in Settings → Firewall → Zones.", "critical")
        if ok:
            self.warned_no_pool = False
        return ok

    def restore_conns(self) -> None:
        """Al apagar las zonas: las conexiones vuelven a como estaban (zona por
        defecto, nombre por DHCP, mDNS/LLMNR según resolved)."""
        for uuid in list(self.applied):
            self.nmcli("connection", "modify", "uuid", uuid, "connection.zone", "",
                       "ipv4.dhcp-send-hostname", "yes", "ipv6.dhcp-send-hostname", "yes",
                       "connection.mdns", "default", "connection.llmnr", "default")
        self.applied.clear()

    def arm(self, conf: dict) -> None:
        self.refresh_endpoints(conf, arm=False, push=False)
        if self.can_arm(conf):
            root_apply("killswitch", "on", *self.endpoints)
            self.armed = True

    def disarm(self) -> None:
        root_apply("killswitch", "off")
        self.armed = False

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
            if k == "wg" and e in names:
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

    def ensure_vpn(self, conf: dict, up: list[str], bypassing: bool) -> None:
        if up or bypassing or time.time() < self.next_vpn_try:
            if up:
                self.vpn_fail_notified = False
            return
        wg = [e for e in pool(conf) if entry_kind(e) == "wg"]
        pref = read_state().get("vpn_pref")
        order = ([pref] if pref in wg else []) + [e for e in wg if e != pref]
        for e in order:
            if self.connect_wg(e):
                notify(f"VPN connected: {e}", "Untrusted network: traffic only goes through the VPN.")
                return
        self.next_vpn_try = time.time() + 60
        if not self.vpn_fail_notified:
            self.vpn_fail_notified = True
            notify("No VPN could connect", "Untrusted network: traffic stays blocked. Settings → Firewall to pick "
                   "another VPN or open a bypass.", "critical")

    def switch_vpn(self, conf: dict, target: str, active: list[dict]) -> None:
        """Cambia de VPN con el kill switch armado (no hay hueco sin cifrar)."""
        st = read_state()
        st["vpn_pref"] = target
        write_state(st)
        if entry_kind(target) != "wg":
            return      # Forti/Citrix: login interactivo desde Settings
        for c in active:
            if c["type"] == "wireguard" and c["name"] in pool(conf) and c["name"] != target:
                self.nmcli("connection", "down", "id", c["name"])
        if not self.connect_wg(target):
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
        conf, nets = load_conf(), networks()
        active = self.nm.active()
        conns = physical(active)
        mode, reason = self.decide(conf, conns, nets)
        if mode != "off" and conf.get("auto") == "on":
            for c in conns:
                if trust_of(c, nets) == "new" and c["uuid"] not in self.asked:
                    self.asked.add(c["uuid"])
                    self.ask(c)
        self.handle_request(conf, active)
        until = bypass_until()
        bypassing = until > time.time()
        if bypassing:
            self.armed = False       # el bypass lo desarmó (y un timer root lo rearma)
        rs = {"avahi": run_ok(["systemctl", "is-active", "--quiet", "avahi-daemon"])}

        if mode != self.mode:
            if mode == "insecure":
                self.set_discovery(False, bool(rs.get("avahi")))
                if conf.get("killswitch") == "on":
                    self.arm(conf)
            else:       # safe u off: nada bloqueado, descubrimiento de vuelta
                if self.armed:
                    self.disarm()
                self.set_discovery(True, False)
                if mode == "off":
                    self.restore_conns()
            prev, self.mode = self.mode, mode
            if prev and mode != "off":
                notify("Untrusted network: protection on" if mode == "insecure" else "Trusted network",
                       reason if mode == "insecure" else "VPN optional, discovery back on.")
        if mode in ("safe", "insecure"):
            for c in conns:
                self.apply_conn(c, mode)
        up = self.vpn_state(conf, active) if mode == "insecure" else []
        if mode == "insecure":
            if conf.get("killswitch") == "on" and not bypassing and not self.armed and \
                    time.time() >= self.next_arm_try:
                self.arm(conf)          # tras un bypass, o si recién se pudo (VPN agregada al pool)
                if not self.armed:
                    self.next_arm_try = time.time() + 30
            elif conf.get("killswitch") != "on" and self.armed:
                self.disarm()
            self.ensure_vpn(conf, up, bypassing)
            if up and int(time.time()) % 300 < POLL:
                self.refresh_endpoints(conf, arm=False)     # con túnel hay DNS: actualizar IPs de los endpoints
        self.st = {"mode": mode, "reason": reason, "auto": conf.get("auto") == "on",
                   "conns": [{"uuid": c["uuid"], "name": c["name"], "type": c["type"], "devs": c["devs"],
                              "trust": trust_of(c, nets)} for c in conns],
                   "vpn_up": up, "killswitch": self.armed, "bypass_until": until,
                   "endpoints": self.endpoints, "vpn_pref": read_state().get("vpn_pref"), "time": time.time(),
                   "pid": os.getpid(), "stopped_kdeconnect": self.stopped_kdeconnect,
                   "stopped_avahi": self.stopped_avahi}
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
        if APPLY.exists():
            root_apply("killswitch", "off")
            root_apply("discovery", "on")
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
