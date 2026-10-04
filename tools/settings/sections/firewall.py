"""Firewall — firewalld.

Leer el estado no necesita root: firewalld deja consultar por D-Bus a la
sesión activa (polkit `org.fedoraproject.FirewallD1.info`). Los cambios sí
(no hay agente de polkit corriendo), así que van con sudo en la misma ventana:
Settings se suspende, como en Snapshots. Cada cambio se hace `--permanent` y
después `--reload`, así lo que se ve es lo que queda al reiniciar.

Para que pasar por la sección sea instantáneo:
- firewall-cmd es Python y cada llamada tarda (y con firewalld parado espera
  ~10 s a D-Bus): el estado sale de systemctl, la zona por defecto de
  firewalld.conf, las zonas/servicios y los puertos de cada servicio de los XML
  de /usr/lib/firewalld y /etc/firewalld. Con firewalld prendido quedan dos
  llamadas: `--list-all` y `--get-active-zones`.
- Todo se junta en un worker; la vista muestra lo último que cargó y redibuja
  solo si algo cambió (Table.set_rows).
- Mientras se ve, cada 3 s mira systemctl (~10 ms) y recarga si cambió el
  estado; la carga completa se repite cada 30 s.

La zona de cada conexión la guarda NetworkManager (`connection.zone`, vacía =
zona por defecto): casa en `home`, Wi-Fi pública en `public`/`drop`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from common import run
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, PickModal, Table, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

NM_TYPES = ("802-11-wireless", "802-3-ethernet", "wireguard", "vpn", "gsm")
PORT_RE = re.compile(r"^\d{1,5}(-\d{1,5})?/(tcp|udp|sctp|dccp)$")
FW_DIRS = [Path("/usr/lib/firewalld"), Path("/etc/firewalld")]   # /etc pisa a /usr/lib
FW_CONF = Path("/etc/firewalld/firewalld.conf")
POLL, FULL_EVERY = 3.0, 30.0
ZONE_DESC = {"drop": "drop everything incoming, no reply", "block": "reject everything incoming",
             "public": "untrusted networks: only what's allowed", "home": "home: trust other devices a bit",
             "work": "work: like home", "internal": "internal network", "trusted": "accept everything",
             "external": "masquerading (router)", "dmz": "exposed servers", "docker": "Docker bridges",
             "nm-shared": "NetworkManager shared connections"}


def fw(*args: str) -> subprocess.CompletedProcess:
    return run(["firewall-cmd", *args])


def unit_state() -> tuple[bool, bool]:
    """(corriendo, habilitado al arranque), sin tocar firewall-cmd."""
    r = run(["systemctl", "show", "firewalld", "-p", "ActiveState", "-p", "UnitFileState"]).stdout
    return "ActiveState=active" in r, "UnitFileState=enabled" in r


def xml_names(kind: str) -> list[str]:
    """Zonas (kind="zones") o servicios ("services") definidos."""
    names = set()
    for base in FW_DIRS:
        d = base / kind
        if d.is_dir():
            names.update(f.stem for f in d.glob("*.xml"))
    return sorted(names)


def service_ports(svc: str) -> str:
    for base in reversed(FW_DIRS):
        f = base / "services" / f"{svc}.xml"
        try:
            ports = re.findall(r'<port[^>]*port="([^"]+)"[^>]*protocol="([^"]+)"', f.read_text())
            return " ".join(f"{p}/{proto}" for p, proto in ports) or "—"
        except OSError:
            continue
    return "—"


def default_zone() -> str:
    try:
        m = re.search(r"^DefaultZone=(\S+)", FW_CONF.read_text(), re.M)
        return m.group(1) if m else "public"
    except OSError:
        return "public"


def list_all(zone: str) -> dict:
    """`--list-all` parseado: {target, interfaces, services, ports, ...}."""
    out = {}
    for line in fw(f"--zone={zone}", "--list-all").stdout.splitlines()[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def active_zones() -> dict[str, list[str]]:
    """{zona: [interfaces]} de `--get-active-zones` (sources no se usan acá)."""
    zones: dict[str, list[str]] = {}
    cur = None
    for line in fw("--get-active-zones").stdout.splitlines():
        if not line.startswith(" "):
            cur = line.split()[0] if line.strip() else None
            if cur:
                zones[cur] = []
        elif cur and line.strip().startswith("interfaces:"):
            zones[cur] = line.split(":", 1)[1].split()
    return zones


def nm_connections() -> list[dict]:
    """Conexiones activas de NetworkManager con su zona (vacía = por defecto)."""
    out = []
    r = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,UUID", "connection", "show", "--active"]).stdout
    for line in r.splitlines():
        parts = re.split(r"(?<!\\):", line)
        if len(parts) < 4 or parts[1] not in NM_TYPES:
            continue
        name = parts[0].replace("\\:", ":")
        zone = run(["nmcli", "-g", "connection.zone", "connection", "show", "uuid", parts[3]]).stdout.strip()
        out.append({"name": name, "type": parts[1], "dev": parts[2], "zone": zone})
    return out


def target_text(target: str) -> str:
    return {"default": "rejects the rest", "%%REJECT%%": "rejects the rest", "REJECT": "rejects the rest",
            "DROP": "drops the rest silently", "ACCEPT": "accepts everything"}.get(target, target or "?")


class FirewallView(DView):
    FOCUS = "#fw-state"
    DEFAULT_CSS = css("""
    #fw-state-panel, #fw-conns-panel { height: auto; }
    #fw-state, #fw-conns { height: auto; }
    #fw-rules-panel { height: 1fr; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False),
        Binding("shift+tab", "cycle(-1)", show=False),
        Binding("a", "add", "allow"),
        Binding("d", "remove", "remove"),
        Binding("r", "refresh", "refresh"),
    ]
    TABLES = ["fw-state", "fw-rules", "fw-conns"]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="fw-state", show_header=False), title="󰒃  Firewall", id="fw-state-panel")
        yield Panel(Table(id="fw-rules"), title="Allowed incoming", id="fw-rules-panel")
        yield Panel(Table(id="fw-conns"), title="Connections", id="fw-conns-panel")

    def on_mount(self) -> None:
        s = self.query_one("#fw-state", Table)
        s.add_column("", key="name", width=30)
        s.add_column("", key="info", width=70)
        r = self.query_one("#fw-rules", Table)
        r.add_column("Rule", key="rule", width=28)
        r.add_column("Type", key="type", width=10)
        r.add_column("Ports", key="desc", width=60)
        c = self.query_one("#fw-conns", Table)
        c.add_column("Connection", key="name", width=28)
        c.add_column("Device", key="dev", width=14)
        c.add_column("Zone", key="zone", width=40)
        self.installed = self.running = self.enabled = False
        self.zone, self.conns = "", []
        self.loaded_at = 0.0
        self._busy = False
        self.query_one("#fw-state-panel").border_subtitle = " loading… "
        self.reload()
        self.set_interval(POLL, self.tick)

    def on_show(self) -> None:
        # Lo último cargado ya está en pantalla; solo se refresca por detrás
        if self.is_mounted:
            self.reload()

    def tick(self) -> None:
        if self.visible_now and not self._busy:
            self.probe()

    @work(thread=True, exclusive=True, group="firewall-probe")
    def probe(self) -> None:
        """Sondeo barato (systemctl): recarga solo si cambió el estado o pasó FULL_EVERY."""
        if unit_state() != (self.running, self.enabled) or time.time() - self.loaded_at > FULL_EVERY:
            self.app.call_from_thread(self.reload)

    # ── estado ──

    def reload(self) -> None:
        if not self._busy:
            self._busy = True
            self.load()

    @work(thread=True, exclusive=True, group="firewall")
    def load(self) -> None:
        try:
            d = {"installed": bool(shutil.which("firewall-cmd")), "running": False, "enabled": False,
                 "zone": default_zone(), "rules": [], "active": {}, "target": ""}
            if d["installed"]:
                d["running"], d["enabled"] = unit_state()
            if d["running"]:
                info = list_all(d["zone"])
                d["target"] = target_text(info.get("target", ""))
                d["rules"] = [("service", s, service_ports(s)) for s in info.get("services", "").split()]
                d["rules"] += [("port", p, "") for p in info.get("ports", "").split()]
                d["active"] = active_zones()
            d["conns"] = nm_connections()
        except Exception:  # noqa: BLE001 - que un fallo no deje la vista trabada en "loading"
            self.app.call_from_thread(setattr, self, "_busy", False)
            raise
        self.app.call_from_thread(self.show_data, d)

    def show_data(self, d: dict) -> None:
        self._busy = False
        self.loaded_at = time.time()
        self.installed, self.running, self.enabled = d["installed"], d["running"], d["enabled"]
        self.zone, self.conns = d["zone"], d["conns"]
        ok, muted, warn = THEME["status_ok"], THEME["muted"], THEME["status_warn"]

        if not self.installed:
            state = [("missing", [Text("✗  Firewall", style=THEME["status_error"]),
                                  Text("firewalld is not installed: sudo pacman -S firewalld", style=warn)])]
        else:
            state = [("toggle", [Text(f"{'●' if self.running else '○'}  Firewall",
                                      style=f"bold {ok}" if self.running else ""),
                                 Text(("on" if self.running else "off") +
                                      (" · starts at boot" if self.enabled else " · not started at boot"),
                                      style=muted if self.running and self.enabled else warn)])]
            state.append(("zone", ["󰒍  Default zone",
                                   Text(f"{self.zone} · {d['target']}" if self.running else self.zone,
                                        style=muted)]))
            if self.running:
                state.append(("active", ["󰛳  Active zones",
                                         Text(" · ".join(f"{z} ({', '.join(i) or '—'})"
                                                         for z, i in d["active"].items()) or "—", style=muted)]))
        self.query_one("#fw-state", Table).set_rows(state)

        self.query_one("#fw-rules", Table).set_rows(
            [(f"{kind}:{name}", [name, Text(kind, style=muted), Text(desc, style=muted)])
             for kind, name, desc in d["rules"]])
        panel = self.query_one("#fw-rules-panel")
        panel.border_title = f" Allowed incoming · {self.zone} " if self.running else " Allowed incoming "
        panel.border_subtitle = (" a allow · d remove " if self.running and d["rules"]
                                 else " nothing allowed: everything incoming is blocked · a to allow "
                                 if self.running else " firewall off ")

        self.query_one("#fw-conns", Table).set_rows([
            (c["name"], [c["name"], Text(c["dev"], style=muted),
                         c["zone"] or Text(f"default ({self.zone})", style=muted)]) for c in self.conns])
        self.query_one("#fw-conns-panel").border_subtitle = " enter to change the zone (NetworkManager) "
        self.query_one("#fw-state-panel").border_subtitle = (
            " changes ask for sudo " if self.running else " enter to turn on " if self.installed else "")
        self.update_hints()

    # ── navegación ──

    def focused_table(self) -> str:
        f = self.app.focused
        return f.id if isinstance(f, Table) and f.id in self.TABLES else "fw-state"

    def action_cycle(self, step: int) -> None:
        i = self.TABLES.index(self.focused_table())
        self.query_one(f"#{self.TABLES[(i + step) % len(self.TABLES)]}", Table).focus()

    def hints(self) -> list[tuple[str, str]]:
        tid = self.focused_table()
        if tid == "fw-rules":
            h = [("a", "allow"), ("d", "remove")]
        elif tid == "fw-conns":
            h = [("enter", "change zone")]
        else:
            h = [("enter", "select"), ("a", "allow")]
        return h + [("tab", "panel"), ("r", "refresh"), ("q", "quit")]

    def action_refresh(self) -> None:
        self.reload()
        self.app.notify_ok("refreshing…")

    # ── cambios (sudo) ──

    def sudo_run(self, cmds: list[list[str]], ok_msg: str) -> None:
        """Corre los comandos con sudo en la terminal; si alguno falla, frena
        y espera un enter para que se lea el error."""
        failed = False
        with self.app.suspend():
            os.system("clear")
            for cmd in cmds:
                print("$ sudo " + " ".join(cmd))
                if subprocess.run(["sudo", *cmd]).returncode != 0:
                    failed = True
                    break
            if failed:
                input("\nPress enter to go back to Settings...")
        self.reload()
        if failed:
            self.app.notify_err("the change failed")
        else:
            self.app.notify_ok(ok_msg)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tid, key = event.data_table.id, str(event.row_key.value)
        if tid == "fw-state":
            if key == "toggle":
                self.toggle()
            elif key == "zone":
                self.pick_default_zone()
        elif tid == "fw-conns":
            self.pick_conn_zone(key)

    def toggle(self) -> None:
        if not self.running:
            return self.sudo_run([["systemctl", "enable", "--now", "firewalld"]], "firewall on")

        def done(yes: bool) -> None:
            if yes:
                self.sudo_run([["systemctl", "disable", "--now", "firewalld"]], "firewall off")

        self.app.push_screen(ConfirmModal("Turn off firewall",
                                          "Stop firewalld and don't start it at boot?\n"
                                          "Every port will be reachable from the network."), done)

    def zone_rows(self) -> list[tuple[str, list]]:
        return [(z, [z, Text(ZONE_DESC.get(z, ""), style=THEME["muted"])]) for z in xml_names("zones")]

    def pick_default_zone(self) -> None:
        if not self.running:
            return self.app.notify_err("turn the firewall on first")

        def done(z: Optional[str]) -> None:
            if z and z != self.zone:
                self.sudo_run([["firewall-cmd", f"--set-default-zone={z}"]], f"default zone: {z}")

        self.app.push_screen(PickModal("Default zone", ["Zone", ""], self.zone_rows()), done)

    def pick_conn_zone(self, conn: str) -> None:
        if not self.running:
            return self.app.notify_err("turn the firewall on first")
        dev = next((c["dev"] for c in self.conns if c["name"] == conn), "")

        def done(z: Optional[str]) -> None:
            if z is None:
                return
            value = "" if z == "(default)" else z
            r = run(["nmcli", "connection", "modify", conn, "connection.zone", value])
            if r.returncode == 0 and dev:
                # aplica la zona al dispositivo sin desconectar
                run(["nmcli", "device", "reapply", dev], timeout=15)
            self.reload()
            if r.returncode == 0:
                self.app.notify_ok(f"{conn}: zone {z}")
            else:
                self.app.notify_err(r.stderr.strip() or "nmcli failed")

        rows = [("(default)", ["(default)", Text(f"follow the default zone ({self.zone})", style=THEME["muted"])])]
        self.app.push_screen(PickModal(f"Zone · {conn}", ["Zone", ""], rows + self.zone_rows()), done)

    def action_add(self) -> None:
        if not self.running:
            return self.app.notify_err("turn the firewall on first")
        services = set(xml_names("services"))

        def check(v: dict) -> Optional[str]:
            x = v["rule"].strip()
            return None if x in services or PORT_RE.match(x) else \
                "Not a known service or a port like 8080/tcp (see /usr/lib/firewalld/services)"

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            x = v["rule"].strip()
            flag = f"--add-service={x}" if x in services else f"--add-port={x}"
            self.sudo_run([["firewall-cmd", "--permanent", f"--zone={self.zone}", flag], ["firewall-cmd", "--reload"]],
                          f"allowed: {x}")

        self.app.push_screen(FormModal(f"Allow incoming · {self.zone}",
                                       [Field("rule", "Service or port", placeholder="e.g. ssh, kdeconnect, 5900/tcp")],
                                       hint="A firewalld service name or port/protocol (range: 1714-1764/udp).",
                                       validate=check), done)

    def action_remove(self) -> None:
        if self.focused_table() != "fw-rules":
            return
        key = self.query_one("#fw-rules", Table).selected_key()
        if not key:
            return
        kind, name = key.split(":", 1)

        def done(yes: bool) -> None:
            if yes:
                self.sudo_run([["firewall-cmd", "--permanent", f"--zone={self.zone}", f"--remove-{kind}={name}"],
                               ["firewall-cmd", "--reload"]], f"removed: {name}")

        self.app.push_screen(ConfirmModal("Remove rule", f"Stop allowing {kind} {name} in zone {self.zone}?"), done)
