#!/usr/bin/env python3
"""
webapps_tui.py — gestor de webapps (Settings → WEBAPPS).

Lista las PWAs instaladas con firefoxpwa; permite abrirlas, crear una nueva
pegando la URL (detecta manifest, nombre e ícono), reinstalarlas y
borrarlas. Las nuevas se agregan a ~/.config/dotfiles/webapps.conf (se crea
desde webapps.conf.example al primer cambio, así no se pierde la lista por
defecto) y las instala scripts/webapps.sh.

Estilo común de las TUIs: tools/dtui.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, Table, TextModal, ViewApp, css  # noqa: E402

from rich.text import Text  # noqa: E402
from textual import work  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.widgets import DataTable, Static  # noqa: E402

# Raíz del repo: DOTFILES_DIR si está exportado; si no, un nivel arriba de tools/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or Path(__file__).resolve().parents[1])
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONF = Path(os.environ.get("WEBAPPS_CONF") or CONFIG_HOME / "dotfiles" / "webapps.conf")
EXAMPLE = DOTFILES / "webapps.conf.example"
WEBAPPS_SH = DOTFILES / "scripts" / "webapps.sh"
FFPWA_CONFIG = Path.home() / ".local/share/firefoxpwa/config.json"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


# ── webapps.conf: nombre|manifest|página inicial|ícono ──
# Sin webapps.conf propio rige el ejemplo del repo (igual que scripts/webapps.sh).

def ensure_conf() -> None:
    """Primer cambio propio: partir de la lista por defecto para no perderla."""
    if not CONF.exists():
        CONF.parent.mkdir(parents=True, exist_ok=True)
        CONF.write_text(EXAMPLE.read_text() if EXAMPLE.exists() else "")


def conf_names() -> set[str]:
    try:
        return {l.split("|", 1)[0] for l in (CONF if CONF.exists() else EXAMPLE).read_text().splitlines()
                if l.strip() and not l.lstrip().startswith("#")}
    except OSError:
        return set()


def conf_append(name: str, manifest: str, url: str, icon: str) -> None:
    ensure_conf()
    with CONF.open("a") as f:
        f.write(f"{name}|{manifest}|{url}|{icon}\n")


def conf_remove(name: str) -> None:
    ensure_conf()
    lines = CONF.read_text().splitlines()
    keep = [l for l in lines if l.lstrip().startswith("#") or l.split("|", 1)[0] != name]
    CONF.write_text("\n".join(keep) + "\n")


def installed() -> list[dict]:
    """[{id, name, url, manifest}] de las webapps instaladas, por nombre."""
    try:
        sites = json.loads(FFPWA_CONFIG.read_text()).get("sites", {})
    except (OSError, ValueError):
        return []
    out = []
    for sid, s in sites.items():
        cfg, man = s.get("config", {}), s.get("manifest", {})
        out.append({"id": sid, "name": cfg.get("name") or man.get("name") or sid,
                    "url": cfg.get("document_url") or man.get("start_url") or "",
                    "manifest": cfg.get("manifest_url") or ""})
    return sorted(out, key=lambda x: x["name"].lower())


# ── detección (igual que el gestor anterior) ──

def _get(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.manifest, self.icons, self.title, self._in_title = None, [], "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "link" and a.get("href") and not a["href"].startswith("data:"):
            rel = (a.get("rel") or "").lower().split()
            if "manifest" in rel and not self.manifest:
                self.manifest = a["href"]
            elif "apple-touch-icon" in rel:
                self.icons.insert(0, a["href"])
            elif "icon" in rel:
                self.icons.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def detect(url: str) -> dict:
    """{url, name, manifest, icon}. manifest vacío si el sitio no es PWA; en
    ese caso icon apunta al mejor ícono del HTML o a /favicon.ico."""
    url, html = _get(url)
    h = _Head()
    h.feed(html)
    out = {"url": url, "name": h.title.strip(), "manifest": "", "icon": ""}
    if h.manifest:
        murl = urljoin(url, h.manifest)
        try:
            m = json.loads(_get(murl)[1])
            out["manifest"] = murl
            out["name"] = m.get("short_name") or m.get("name") or out["name"]
        except Exception:
            pass
    if not out["manifest"]:
        out["icon"] = urljoin(url, h.icons[0]) if h.icons else urljoin(url, "/favicon.ico")
    if not out["name"]:
        out["name"] = re.sub(r"^https?://(www\.)?([^/.]+).*", r"\2", url)
    return out


class WebappsView(DView):
    """Lista de webapps + detalle. Se usa sola (WebappsApp) o en Settings."""

    DEFAULT_CSS = css("""
    #list-panel { height: 1fr; }
    #detail { height: auto; }
    #detail Static { height: auto; }
    """)

    BINDINGS = [
        Binding("n", "new", "new"),
        Binding("r", "reinstall", "reinstall"),
        Binding("d", "delete", "delete"),
        Binding("j", "down", show=False),
        Binding("k", "up", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="table"), title="󰖟  Webapps", id="list-panel")
        yield Panel(Static(id="info"), title="Details", id="detail")

    def hints(self) -> list[tuple[str, str]]:
        return [("enter", "open"), ("n", "new"), ("r", "reinstall"), ("d", "delete"), ("q", "quit")]

    def on_mount(self) -> None:
        t = self.query_one("#table", DataTable)
        t.add_column("Name", key="name", width=24)
        t.add_column("Page", key="url", width=56)
        self.busy_msg = ""
        self.reload()

    def reload(self, select: Optional[str] = None) -> None:
        t = self.query_one("#table", DataTable)
        cur = select or (self.current() or {}).get("name")
        self.apps = installed()
        t.clear()
        for a in self.apps:
            t.add_row(Text(a["name"]), Text(a["url"], style=THEME["muted"]), key=a["id"])
        names = [a["name"] for a in self.apps]
        if cur in names:
            t.move_cursor(row=names.index(cur))
        self.update_subtitle()
        self.update_detail()

    def update_subtitle(self) -> None:
        panel = self.query_one("#list-panel")
        panel.border_subtitle = f" {self.busy_msg} " if self.busy_msg else f" {len(self.apps)} installed "

    def current(self) -> Optional[dict]:
        t = self.query_one("#table", DataTable)
        if not getattr(self, "apps", None) or t.cursor_row is None or t.cursor_row >= len(self.apps):
            return None
        return self.apps[t.cursor_row]

    def on_data_table_row_highlighted(self, _event) -> None:
        self.update_detail()

    def update_detail(self) -> None:
        a = self.current()
        info = self.query_one("#info", Static)
        if not a:
            info.update(Text("No webapps yet: press n to create one.", style=THEME["muted"]))
            return
        t = Text()
        for label, value in (("Page", a["url"]), ("Manifest", a["manifest"] or "—"), ("ID", a["id"])):
            t.append(f"{label:<10}", style=f"bold {THEME['muted']}")
            t.append(value + "\n")
        t.append(f"{'Config':<10}", style=f"bold {THEME['muted']}")
        if a["name"] in conf_names():
            t.append("in webapps.conf (reinstalled on other machines)", style=THEME["status_ok"])
        else:
            t.append("not in webapps.conf", style=THEME["status_warn"])
        info.update(t)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "table" and (a := self.current()):
            subprocess.Popen(["firefoxpwa", "site", "launch", a["id"]], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.app.exit()

    def action_down(self) -> None:
        self.query_one("#table", DataTable).action_cursor_down()

    def action_up(self) -> None:
        self.query_one("#table", DataTable).action_cursor_up()

    def set_busy(self, msg: str) -> None:
        self.busy_msg = msg
        self.update_subtitle()

    # ── nueva ──

    def action_new(self) -> None:
        if self.busy_msg:
            return

        def got_url(v: Optional[dict]) -> None:
            if v:
                url = v["url"] if re.match(r"^https?://", v["url"]) else f"https://{v['url']}"
                self.set_busy(f"analyzing {url}…")
                self.analyze(url)

        self.app.push_screen(FormModal("New webapp", [Field("url", "URL", placeholder="https://...")],
                                       validate=lambda v: None if v["url"] else "The URL is missing"), got_url)

    @work(thread=True, exclusive=True)
    def analyze(self, url: str) -> None:
        try:
            info = detect(url)
        except Exception as e:  # noqa: BLE001
            self.app.call_from_thread(self.set_busy, "")
            self.app.call_from_thread(self.app.notify_err, f"Could not open {url}: {e}")
            return
        self.app.call_from_thread(self.confirm_new, info)

    def confirm_new(self, info: dict) -> None:
        self.set_busy("")
        taken = conf_names() | {a["name"] for a in self.apps}
        hint = (f"Manifest: {info['manifest']}" if info["manifest"]
                else f"Not a PWA: a manifest will be generated. Icon: {info['icon']}")

        def check(v: dict) -> Optional[str]:
            name = v["name"].replace("|", "").strip()
            if not name:
                return "The name is missing"
            if name in taken:
                return f"There is already a webapp called {name}"
            return None

        def done(v: Optional[dict]) -> None:
            if v:
                name = v["name"].replace("|", "").strip()
                conf_append(name, info["manifest"], v["url"].strip() or info["url"], info["icon"])
                self.set_busy(f"installing {name}…")
                self.install(name, new=True)

        self.app.push_screen(FormModal("Create webapp", [Field("name", "Name", info["name"]),
                                                         Field("url", "Start page", info["url"])],
                                       hint=hint, validate=check), done)

    @work(thread=True, exclusive=True)
    def install(self, name: str, new: bool = False, uninstall_id: str = "") -> None:
        if uninstall_id:
            subprocess.run(["firefoxpwa", "site", "uninstall", "--quiet", uninstall_id],
                           capture_output=True)
        r = subprocess.run(["bash", str(WEBAPPS_SH), name], capture_output=True, text=True)
        if r.returncode != 0 and new:
            conf_remove(name)   # si falló, no dejar la entrada en el conf
        self.app.call_from_thread(self.install_done, name, r)

    def install_done(self, name: str, r: subprocess.CompletedProcess) -> None:
        self.set_busy("")
        self.reload(select=name)
        if r.returncode == 0:
            self.app.notify_ok(f"{name} is ready: it's in the launcher")
        else:
            self.app.push_screen(TextModal(f"Could not install {name}", (r.stdout or "") + (r.stderr or "")))

    # ── reinstalar / borrar ──

    def action_reinstall(self) -> None:
        a = self.current()
        if not a or self.busy_msg:
            return
        if a["name"] not in conf_names():
            self.app.notify_err(f"{a['name']} is not in webapps.conf: don't know how to reinstall it")
            return
        self.set_busy(f"reinstalling {a['name']}…")
        self.install(a["name"], uninstall_id=a["id"])

    def action_delete(self) -> None:
        a = self.current()
        if not a or self.busy_msg:
            return

        def done(yes: bool) -> None:
            if not yes:
                return
            r = subprocess.run(["firefoxpwa", "site", "uninstall", "--quiet", a["id"]], capture_output=True)
            if r.returncode == 0:
                if a["name"] in conf_names():
                    conf_remove(a["name"])
                self.app.notify_ok(f"{a['name']} deleted")
            else:
                self.app.notify_err(f"Could not delete {a['name']}")
            self.reload()

        self.app.push_screen(ConfirmModal("Delete webapp", f"Delete {a['name']}? Its session will be lost."), done)


def WebappsApp() -> ViewApp:
    return ViewApp(WebappsView, title="Webapps")


if __name__ == "__main__":
    if not shutil.which("firefoxpwa"):
        sys.exit("firefoxpwa is not installed: sudo pacman -S firefoxpwa")
    WebappsApp().run()
