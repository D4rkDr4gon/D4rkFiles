"""USB guard — USBGuard: los dispositivos USB nuevos quedan bloqueados hasta que
se permiten (contra pendrives/cables "BadUSB" que se hacen pasar por teclado).

- Protection: instalarlo y activarlo (enter). La política inicial permite todo lo
  que está conectado en ese momento (`usbguard generate-policy`): cámara, huella,
  bluetooth y lo que haya enchufado siguen andando. El usuario queda en
  IPCAllowedUsers para poder permitir dispositivos sin sudo (esta sección y la
  notificación). Apagarlo deja todo permitido otra vez.
- Devices: lo conectado ahora. enter permite/bloquea (hasta desconectarlo),
  p lo permite siempre (agrega una regla permanente).

Al enchufar algo bloqueado avisa scripts/usbguard-notify.py (exec-once de
Hyprland) con botones para permitirlo. Ojo: si un firmware cambia la
identidad de un dispositivo interno (ej. el lector de huellas tras fwupd), va a
aparecer bloqueado: se permite siempre desde acá.
"""

from __future__ import annotations

import getpass
import re
import shutil

from common import DOTFILES, detach, run, sudo_run
from dtui import THEME, ConfirmModal, DView, Panel, Table, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

DAEMON_CONF = "/etc/usbguard/usbguard-daemon.conf"
RULES = "/etc/usbguard/rules.conf"
NOTIFIER = DOTFILES / "scripts" / "usbguard-notify.py"
DEV_RE = re.compile(r"^(\d+): (allow|block|reject) id (\S+)(.*)$")


def parse_devices(out: str) -> list[dict]:
    devs = []
    for line in out.splitlines():
        m = DEV_RE.match(line.strip())
        if not m:
            continue
        rest = m.group(4)
        name = n.group(1) if (n := re.search(r'name "([^"]*)"', rest)) else ""
        port = n.group(1) if (n := re.search(r'via-port "([^"]*)"', rest)) else ""
        iface = n.group(1) if (n := re.search(r"with-interface (\{[^}]*\}|\S+)", rest)) else ""
        devs.append({"id": m.group(1), "target": m.group(2), "vidpid": m.group(3), "name": name, "port": port,
                     "hid": bool(re.search(r"\b03:", iface)), "hub": bool(re.search(r"\b09:", iface))})
    return devs


def status() -> dict:
    st = {"installed": shutil.which("usbguard") is not None, "active": False, "ipc": False, "devices": [],
          "notifier": False}
    if not st["installed"]:
        return st
    st["active"] = run(["systemctl", "is-active", "usbguard"]).stdout.strip() == "active"
    if st["active"]:
        r = run(["usbguard", "list-devices"])
        st["ipc"] = r.returncode == 0
        st["devices"] = parse_devices(r.stdout)
    st["notifier"] = run(["pgrep", "-f", "usbguard-notify.py"]).returncode == 0
    return st


def setup_cmds(user: str) -> list[list[str]]:
    """Instalar, política con lo conectado ahora, IPC para el usuario y activar."""
    return [["pacman", "-S", "--needed", "--noconfirm", "usbguard"],
            ["sh", "-c", f"umask 077; usbguard generate-policy > {RULES}.new && mv {RULES}.new {RULES}"],
            # Si la clave no está en el archivo, se agrega al final
            ["sh", "-c", f"f={DAEMON_CONF}; "
                         f"if grep -q '^IPCAllowedUsers=' $f; then sed -i 's/^IPCAllowedUsers=.*/IPCAllowedUsers=root {user}/' $f; "
                         f"else echo 'IPCAllowedUsers=root {user}' >> $f; fi"],
            ["systemctl", "enable", "--now", "usbguard"]]


class UsbGuardView(DView):
    FOCUS = "#usb-devices"
    TABLES = ["usb-state", "usb-devices"]
    DEFAULT_CSS = css("""
    #usb-state-panel { height: auto; }
    #usb-state { height: auto; }
    #usb-devices-panel { height: 1fr; }
    """)
    BINDINGS = [Binding("tab", "cycle(1)", show=False), Binding("shift+tab", "cycle(-1)", show=False),
                Binding("p", "permanent", "allow device always"), Binding("r", "refresh", "refresh")]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="usb-state", show_header=False), title="󰕓  USB guard", id="usb-state-panel")
        yield Panel(Table(id="usb-devices"), title="Connected devices", id="usb-devices-panel")

    def on_mount(self) -> None:
        s = self.query_one("#usb-state", Table)
        s.add_column("", key="name", width=22)
        s.add_column("", key="state", width=26)
        s.add_column("", key="desc", width=70)
        d = self.query_one("#usb-devices", Table)
        d.add_column("", key="target", width=12)
        d.add_column("Device", key="name", width=40)
        d.add_column("ID", key="id", width=11)
        d.add_column("Port", key="port", width=10)
        d.add_column("", key="note", width=24)
        self.st: dict = {}
        self.action_refresh()
        self.set_interval(5, self.tick)

    def tick(self) -> None:
        if self.visible_now:
            self.action_refresh()

    def hints(self) -> list[tuple[str, str]]:
        if self.app.focused is not None and self.app.focused.id == "usb-devices":
            return [("enter", "allow/block"), ("p", "allow always"), ("tab", "panel"), ("q", "quit")]
        return [("enter", "turn on/off"), ("tab", "panel"), ("q", "quit")]

    def action_cycle(self, step: int) -> None:
        f = self.app.focused
        i = self.TABLES.index(f.id) if f is not None and f.id in self.TABLES else 0
        self.query_one(f"#{self.TABLES[(i + step) % 2]}", Table).focus()
        self.update_hints()

    @work(thread=True, exclusive=True, group="usb")
    def action_refresh(self) -> None:
        st = status()
        self.app.call_from_thread(self.show, st)

    def show(self, st: dict) -> None:
        self.st = st
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]
        if not st["installed"]:
            prot = (Text("○  not installed", style=warn),
                    "enter installs it and allows everything connected now; new devices wait for your OK")
        elif not st["active"]:
            prot = (Text("○  off", style=warn), "every USB device is allowed · enter to turn it on")
        elif not st["ipc"]:
            prot = (Text("●  on · no access", style=warn),
                    f"you are not in IPCAllowedUsers ({DAEMON_CONF}) · enter fixes it")
        else:
            blocked = sum(d["target"] != "allow" for d in st["devices"])
            prot = (Text("●  on", style=ok), f"new devices are blocked until you allow them"
                                             f"{f' · {blocked} blocked now' if blocked else ''}")
        rows = [("protection", ["󰒃  Protection", prot[0], Text(prot[1], style=muted)])]
        if st["installed"] and st["active"]:
            rows.append(("notifier", ["  Notifications",
                                      Text("●  running", style=ok) if st["notifier"] else Text("○  stopped", style=warn),
                                      Text("asks you when something gets blocked (middle-click the notification)"
                                           + ("" if st["notifier"] else " · enter to start it"), style=muted)]))
        self.query_one("#usb-state", Table).set_rows(rows)

        drows = []
        for d in st["devices"]:
            tgt = {"allow": Text("●  allowed", style=ok), "block": Text("○  blocked", style=warn),
                   "reject": Text("✗  rejected", style=err)}[d["target"]]
            note = Text("keyboard / HID", style=warn if d["target"] != "allow" else muted) if d["hid"] else \
                Text("hub", style=muted) if d["hub"] else Text("")
            drows.append((d["id"], [tgt, d["name"] or "—", Text(d["vidpid"], style=muted),
                                    Text(d["port"], style=muted), note]))
        self.query_one("#usb-devices", Table).set_rows(drows)
        self.query_one("#usb-devices-panel").border_subtitle = (
            " enter allow/block · p allow always " if drows else
            " turn protection on to list devices " if not st.get("ipc") else " nothing connected ")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tid, key = event.data_table.id, str(event.row_key.value)
        if tid == "usb-state":
            self.state_action(key)
        elif tid == "usb-devices":
            d = next((x for x in self.st.get("devices", []) if x["id"] == key), None)
            if not d:
                return
            verb = "block-device" if d["target"] == "allow" else "allow-device"
            if verb == "block-device" and d["hub"]:
                return self.app.notify_err("Blocking a hub cuts everything behind it: not from here")
            r = run(["usbguard", verb, d["id"]])
            if r.returncode:
                self.app.notify_err(r.stderr.strip() or "usbguard failed")
            else:
                self.app.notify_ok(f"{d['name'] or d['vidpid']}: " +
                                   ("blocked" if verb == "block-device" else "allowed until unplugged"))
            self.action_refresh()

    def action_permanent(self) -> None:
        if self.app.focused is None or self.app.focused.id != "usb-devices":
            return
        key = self.query_one("#usb-devices", Table).selected_key()
        d = next((x for x in self.st.get("devices", []) if x["id"] == key), None)
        if d:
            r = run(["usbguard", "allow-device", "-p", d["id"]])
            if r.returncode:
                self.app.notify_err(r.stderr.strip() or "usbguard failed")
            else:
                self.app.notify_ok(f"{d['name'] or d['vidpid']}: always allowed")
            self.action_refresh()

    def state_action(self, key: str) -> None:
        st = self.st
        if key == "notifier":
            if not st.get("notifier"):
                detach([str(NOTIFIER)])
                self.app.notify_ok("Notifications started")
            self.action_refresh()
            return
        user = getpass.getuser()
        if not st.get("installed") or (st.get("active") and not st.get("ipc")):
            cmds = setup_cmds(user) if not st.get("installed") else setup_cmds(user)[2:]
            msg = ("Install USBGuard? Everything connected right now stays allowed; anything you plug in "
                   "later is blocked until you allow it from the notification or from here."
                   if not st.get("installed") else f"Give {user} access to USBGuard ({DAEMON_CONF})?")

            def done(yes: bool) -> None:
                if yes and sudo_run(self.app, cmds, "USB guard setup"):
                    detach([str(NOTIFIER)])
                    self.app.notify_ok("USB guard on")
                self.action_refresh()

            self.app.push_screen(ConfirmModal("USB guard", msg), done)
        elif not st.get("active"):
            if sudo_run(self.app, [["systemctl", "enable", "--now", "usbguard"]], "USB guard: on"):
                detach([str(NOTIFIER)])
                self.app.notify_ok("USB guard on")
            self.action_refresh()
        else:
            def off(yes: bool) -> None:
                if yes and sudo_run(self.app, [["systemctl", "disable", "--now", "usbguard"]], "USB guard: off"):
                    self.app.notify_ok("USB guard off: every device is allowed")
                self.action_refresh()

            self.app.push_screen(ConfirmModal("USB guard", "Turn it off? Every USB device will be allowed again."),
                                 off)
