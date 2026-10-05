"""Phone — teléfonos vinculados por KDE Connect (kdeconnectd, exec-once de Hyprland).

Estado (alcanzable, batería por D-Bus) y acciones: hacer sonar, ping, mandar
el portapapeles, compartir un archivo o un texto/URL, bloquear y ver las
notificaciones del teléfono.

"Lock when it leaves": scripts/phone-proximity.py (exec-once) bloquea la sesión
cuando el teléfono deja de estar al alcance un rato (proximity_grace). Config en
~/.config/dotfiles/phone.conf; enter lo prende/apaga y pregunta los minutos.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Optional

from common import CONF_DIR, DOTFILES, atomic_write, detach, run
from dtui import THEME, DView, Field, FormModal, Panel, Table, TextModal, charge10, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static

DBUS = "org.kde.kdeconnect"
PHONE_CONF = Path(os.environ.get("PHONE_CONF", CONF_DIR / "phone.conf"))
PROXIMITY = DOTFILES / "scripts" / "phone-proximity.py"


def load_conf() -> dict:
    conf = {"proximity_lock": "off", "proximity_grace": "120", "proximity_device": ""}
    try:
        for line in PHONE_CONF.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not k.strip().startswith("#"):
                conf[k.strip()] = v.strip()
    except OSError:
        pass
    return conf


def save_conf(updates: dict) -> None:
    """Cambia claves conservando comentarios y orden."""
    try:
        lines = PHONE_CONF.read_text().splitlines()
    except OSError:
        lines = ["# phone.conf — opciones del teléfono (KDE Connect). Lo escribe Settings → Phone."]
    left = dict(updates)
    for i, line in enumerate(lines):
        k = line.partition("=")[0].strip()
        if k in left and not k.startswith("#"):
            lines[i] = f"{k}={left.pop(k)}"
    lines += [f"{k}={v}" for k, v in left.items()]
    atomic_write(PHONE_CONF, "\n".join(lines) + "\n")


def devices() -> list[dict]:
    """Dispositivos conocidos: [{id, name, paired, reachable}]."""
    out = []
    for line in run(["kdeconnect-cli", "-l"]).stdout.splitlines():
        m = re.match(r"- (.+): (\w+) .*\((.+)\)", line)
        if m:
            state = m.group(3)
            out.append({"id": m.group(2), "name": m.group(1), "paired": "paired" in state,
                        "reachable": "reachable" in state})
    return out


def prop(dev: str, path: str, iface: str, name: str) -> Optional[str]:
    r = run(["busctl", "--user", "get-property", DBUS, f"/modules/kdeconnect/devices/{dev}{path}", iface, name])
    return r.stdout.split(" ", 1)[1].strip().strip('"') if r.returncode == 0 and " " in r.stdout else None


class PhoneView(DView):
    FOCUS = "#phone-actions"
    DEFAULT_CSS = css("""
    #phone-status-panel { height: auto; }
    #phone-status { height: auto; }
    #phone-actions-panel { height: 1fr; }
    """)
    BINDINGS = [Binding("r", "refresh", "refresh")]

    def compose(self) -> ComposeResult:
        yield Panel(Static(id="phone-status"), title="󰏲  Phone", id="phone-status-panel")
        yield Panel(Table(id="phone-actions", show_header=False), title="Actions", id="phone-actions-panel")

    def on_mount(self) -> None:
        t = self.query_one("#phone-actions", Table)
        t.add_column("", key="name", width=36)
        t.add_column("", key="desc", width=70)
        for key, name, desc in (
                ("ring", "󰂞  Find my phone", "make it ring at full volume"),
                ("ping", "󰘬  Ping", "send a ping notification"),
                ("clip", "󰅌  Send clipboard", "copy this computer's clipboard to the phone"),
                ("file", "󰈔  Share a file", "send a file to the phone"),
                ("text", "󰉿  Share text or URL", "open it on the phone"),
                ("notif", "  Phone notifications", "list the notifications on the phone"),
                ("lock", "  Lock the phone", "if the phone allows it")):
            t.add_row(name, Text(desc, style=THEME["muted"]), key=key)
        t.add_row("󰌾  Lock when it leaves", self.proximity_desc(), key="proximity")
        self.dev: Optional[dict] = None
        self.action_refresh()
        self.set_interval(15, self.tick)

    def tick(self) -> None:
        if self.visible_now:
            self.action_refresh()

    def proximity_desc(self) -> Text:
        c = load_conf()
        if c.get("proximity_lock") != "on":
            return Text("off · lock this computer when the phone is out of reach", style=THEME["muted"])
        mins = max(1, int(c.get("proximity_grace", "120") or 120) // 60)
        return Text(f"● on · locks after {mins} min out of reach", style=THEME["status_ok"])

    def toggle_proximity(self) -> None:
        c = load_conf()
        t = self.query_one("#phone-actions", Table)
        if c.get("proximity_lock") == "on":
            save_conf({"proximity_lock": "off"})
            t.update_cell("proximity", "desc", self.proximity_desc())
            return self.app.notify_ok("Proximity lock off")

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            save_conf({"proximity_lock": "on", "proximity_grace": str(int(float(v["mins"]) * 60)),
                       "proximity_device": self.dev["id"] if self.dev else ""})
            if run(["pgrep", "-f", "phone-proximity.py"]).returncode != 0:
                detach([str(PROXIMITY)])
            t.update_cell("proximity", "desc", self.proximity_desc())
            self.app.notify_ok("Proximity lock on")

        def check(v: dict) -> Optional[str]:
            try:
                return None if 0.5 <= float(v["mins"]) <= 60 else "Between 0.5 and 60 minutes"
            except ValueError:
                return "A number of minutes"

        mins = int(c.get("proximity_grace", "120") or 120) / 60
        self.app.push_screen(FormModal("Lock when the phone leaves", [
            Field("mins", "Minutes out of reach before locking", f"{mins:g}")],
            hint="Only after the phone was seen in this session, never without network or with KDE Connect down.",
            validate=check), done)

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "run"), ("r", "refresh"), ("q", "quit")]

    @work(thread=True, exclusive=True, group="phone")
    def action_refresh(self) -> None:
        devs = devices() if shutil.which("kdeconnect-cli") else []
        dev = next((d for d in devs if d["paired"] and d["reachable"]), None) or \
            next((d for d in devs if d["paired"]), None)
        info = {}
        if dev and dev["reachable"]:
            charge = prop(dev["id"], "/battery", "org.kde.kdeconnect.device.battery", "charge")
            charging = prop(dev["id"], "/battery", "org.kde.kdeconnect.device.battery", "isCharging")
            info = {"charge": int(charge) if charge and charge.lstrip("-").isdigit() else None,
                    "charging": charging == "true"}
        self.app.call_from_thread(self.show, dev, info, len(devs))

    def show(self, dev: Optional[dict], info: dict, total: int) -> None:
        self.dev = dev
        ok, muted, warn = THEME["status_ok"], THEME["muted"], THEME["status_warn"]
        st = Text()
        if not shutil.which("kdeconnect-cli"):
            st.append("KDE Connect is not installed", style=warn)
        elif not dev:
            st.append("○  No paired phone", style=muted)
            st.append("   pair one from the KDE Connect app on the phone", style=muted)
        else:
            st.append(f"{'●' if dev['reachable'] else '○'}  {dev['name']}",
                      style=f"bold {ok}" if dev["reachable"] else muted)
            st.append("   reachable" if dev["reachable"] else "   not reachable (same network? app open?)",
                      style=muted)
            if info.get("charge") is not None:
                st.append("\n   battery  ", style=muted)
                st.append_text(charge10(info["charge"]))
                st.append("  charging" if info["charging"] else "", style=ok)
        self.query_one("#phone-status", Static).update(st)
        self.query_one("#phone-status-panel").border_subtitle = f" {total} known device(s) " if total else ""

    def cli(self, *args: str, ok: str) -> None:
        if not self.dev or not self.dev["reachable"]:
            return self.app.notify_err("No reachable phone")
        r = run(["kdeconnect-cli", "-d", self.dev["id"], *args], timeout=20)
        if r.returncode == 0:
            self.app.notify_ok(ok)
        else:
            self.app.notify_err((r.stderr or r.stdout).strip() or "kdeconnect-cli failed")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "phone-actions":
            return
        key = event.row_key.value
        if key == "proximity":
            self.toggle_proximity()
        elif key == "ring":
            self.cli("--ring", ok="Ringing the phone")
        elif key == "ping":
            self.cli("--ping", ok="Ping sent")
        elif key == "clip":
            self.cli("--send-clipboard", ok="Clipboard sent")
        elif key == "lock":
            self.cli("--lock", ok="Lock requested")
        elif key == "notif":
            if self.dev and self.dev["reachable"]:
                r = run(["kdeconnect-cli", "-d", self.dev["id"], "--list-notifications"], timeout=20)
                self.app.push_screen(TextModal("Phone notifications", r.stdout.strip() or "(none)", end=False))
        elif key == "file":
            def done(v: Optional[dict]) -> None:
                if v:
                    self.cli("--share", str(Path(v["path"]).expanduser()), ok="File sent")
            self.app.push_screen(FormModal("Share a file", [Field("path", "File", str(Path.home()) + "/",
                                                                  files=True)],
                                           validate=lambda v: None if Path(v["path"]).expanduser().is_file()
                                           else "File not found"), done)
        elif key == "text":
            def done_text(v: Optional[dict]) -> None:
                if v:
                    self.cli("--share-text", v["text"], ok="Sent to the phone")
            self.app.push_screen(FormModal("Share text or URL", [Field("text", "Text or URL")],
                                           validate=lambda v: None if v["text"] else "Nothing to send"), done_text)
