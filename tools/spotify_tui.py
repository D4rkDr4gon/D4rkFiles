#!/usr/bin/env python3
"""
spotify_tui.py — cliente de Spotify con la estética de las TUIs propias.

La TUI habla directo con la Web API de Spotify (estado, controles, listas,
búsqueda, dispositivos). `spotify_player` (paquete spotify-player) corre como
daemon (`spotify_player -d`) y hace dos cosas: es el dispositivo de Spotify
Connect que suena (el `name` de [device] en app.toml) y mantiene renovado el token de la Web API en su
cache, que la TUI solo lee. Si no está corriendo, la TUI lo arranca.

Su CLI no se usa para los pedidos: devuelve las respuestas por UDP en pedazos
de 4 KB (las grandes llegan corruptas), cuando el daemon tarda intenta levantar
su propio cliente en el mismo puerto ("Address already in use") y corre los
comandos de reproducción en segundo plano sin devolver el error. Solo se la
llama para que el daemon renueve el token (nudge_daemon) y para el login.

Paneles: Now playing (carátula + tema, barra de avance, estado), Library en dos
modos (`m`): Music (Liked songs, Queue, Saved albums, Top tracks, playlists
favoritas con `f` y el resto) y Podcasts (episodios guardados y shows), y
Tracks (lo elegido en Library o una búsqueda). `/` filtra la lista abierta si el
foco está en Tracks y busca en Spotify si está en Library. Las favoritas se
guardan en ~/.local/state/dotfiles/spotify-tui/favorites.json. Los controles manejan el
dispositivo activo (también el cliente oficial o el teléfono); si no hay
ninguno (404), la reproducción pasa al del daemon y se reintenta.

El estado se pide cada POLL segundos (cada pedido gasta cuota de la Web API) y
el avance se interpola en el medio.

Requiere Spotify Premium y dos logins: el de la Web API con el client ID propio
(`spotify_player authenticate`, token en ~/.cache/spotify-player/<id>_token.json)
y el de streaming (librespot, credentials.json), que `a` hace abriendo
spotify_player interactivo. Con un client ID propio, spotify_player 0.25 exige
además un token del client de ncspot como respaldo, cuyo login está roto
(redirect_uri: Not matching configuration): sync_tokens() renueva el token propio
y lo copia con el nombre del de ncspot antes de arrancar el daemon, así nunca lo
pide. SPOTIFY_TUI_API apunta a otra URL base (pruebas con un servidor falso).

El backend (daemon, tokens, Web API, app.toml, favoritas) está en
spotify_api.py, sin Textual, para que el autoarranque de la sesión no cargue la
TUI. Acá quedan dos vistas: SpotifyView (el reproductor: Super+Y) y
SpotifySettingsView (Settings → Spotify: logins, daemon y autoarranque, la
config de spotify_player y el orden de las favoritas), como expenses_tui.py
con FinancesView.
Doc: docs/customization.md (Spotify).

Estilo común de las TUIs: tools/dtui.py. Textos visibles en inglés.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import (THEME, ConfirmModal, DView, Field, FormModal, ImagePreview, Panel, PickModal,  # noqa: E402
                  Table, ViewApp, bar, css, human)

from rich.text import Text  # noqa: E402
from textual import work  # noqa: E402
from textual.worker import get_current_worker  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.widgets import DataTable, Static  # noqa: E402

from spotify_api import (BIN, PAGE, POLL, SEARCH_LIMIT, SEEK_MS, VOL_STEP, SpotifyError, api,  # noqa: E402
                         api_pages, context_uri, cover_path, daemon_running, devices, load_favs, logged_in,
                         mmss, playback_of, playlist_of, save_favs, start_daemon, sync_tokens,
                         to_own_device, track_of, album_row)
import spotify_api as sp  # noqa: E402

LAUNCHER = Path.home() / ".config" / "waybar" / "scripts" / "spotify-launch.sh"


# ── Vista ─────────────────────────────────────────────────

LIBRARY = [("lib:liked", "󰋑", "Liked songs"), ("lib:queue", "󰲸", "Queue"),
           ("lib:albums", "󰀥", "Saved albums"), ("lib:top", "󰔵", "Top tracks")]
REPEAT_NEXT = {"off": "context", "context": "track", "track": "off"}


class SpotifyView(DView):
    """Now playing + Library + Tracks, sobre la Web API."""

    FOCUS = "#sp-library"
    DEFAULT_CSS = css("""
    #sp-now { height: 13; }
    #sp-cover { width: 26; height: 11; }
    #sp-info { width: 1fr; padding: 0 2; }
    #sp-body { height: 1fr; }
    #sp-library-panel { width: 34; }
    #sp-tracks-panel { width: 1fr; }
    """)
    BINDINGS = [
        Binding("space", "toggle", "play/pause"),
        Binding("n", "next", "next"),
        Binding("b", "previous", "previous"),
        Binding("plus,equals_sign", "volume(1)", "volume up", show=False),
        Binding("minus", "volume(-1)", "volume down", show=False),
        # priority: la tabla con foco se comería las flechas laterales
        Binding("left", "seek(-1)", "seek back", show=False, priority=True),
        Binding("right", "seek(1)", "seek forward", show=False, priority=True),
        Binding("s", "shuffle", "shuffle", show=False),
        Binding("r", "repeat", "repeat", show=False),
        Binding("l", "like", "like the current track", show=False),
        Binding("p", "play_list", "play the whole list", show=False),
        Binding("slash", "search", "search"),
        Binding("d", "devices", "devices"),
        Binding("f", "favorite", "mark the playlist as favorite", show=False),
        Binding("m", "mode", "switch Library between music and podcasts", show=False),
        Binding("a", "auth", "log in to Spotify", show=False),
        Binding("R", "refresh", "reload the library", show=False),
    ]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.state: Optional[dict] = None
        self.fetched = 0.0              # cuándo llegó self.state (para interpolar el avance)
        self.error = ""
        self.playlists: list[dict] = []
        self.items: list[dict] = []     # lo que muestra Tracks: temas / álbumes / playlists / artistas
        self.source: tuple[str, str] = ("", "")   # (tipo, id) de la lista mostrada, para enter y `p`
        self.mode = "music"             # Library: "music" | "podcasts" (m)
        self.shows: list[dict] = []
        self.favs = load_favs()
        self.query = ""                 # filtro de Tracks (/ con el foco en Tracks)
        self.shown: dict = {"title": "", "more": False, "note": "", "search": False}
        self._started = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="sp-now", classes="panel") as now:
            now.border_title = " 󰓇  Now playing "
            yield ImagePreview(id="sp-cover")
            yield Static(id="sp-info")
        with Horizontal(id="sp-body"):
            yield Panel(Table(id="sp-library", show_header=False), title="Library", id="sp-library-panel")
            yield Panel(Table(id="sp-tracks"), title="Tracks", id="sp-tracks-panel")

    def on_mount(self) -> None:
        self.query_one("#sp-library", Table).add_column("", key="name", width=30)
        t = self.query_one("#sp-tracks", Table)
        t.add_column("Title", key="title", width=36)
        t.add_column("Artist", key="artist", width=24)
        t.add_column("Album", key="album", width=24)
        t.add_column("Time", key="time", width=7)
        self.paint_library()

    def on_show(self) -> None:
        # Arranca la primera vez que se ve: Settings monta todas las secciones al
        # abrirse y no tiene que levantar spotify_player si nadie entra acá
        if self._started:
            return
        self._started = True
        start_daemon()
        self.action_refresh()
        self.set_interval(POLL, self.tick_poll)
        self.set_interval(1, self.paint_now)

    def hints(self) -> list[tuple[str, str]]:
        if self.error and "auth" in self.error.lower():
            return [("a", "log in"), ("R", "retry"), ("esc", "close")]
        # s/r/-/+ se ven en Now playing; l like y R reload no entran (Shortcuts → Settings los lista)
        h = [("space", "play/pause"), ("n/b", "next/prev")]
        f = self.app.focused
        if f is not None and f.id == "sp-library":
            h += [("enter", "open"), ("p", "play all")]
            if self.mode == "music":
                h.append(("f", "favorite"))
            h += [("m", "podcasts" if self.mode == "music" else "music"), ("/", "search")]
        else:
            h += [("←/→", "seek"), ("enter", "play"), ("p", "play all"),
                  ("/", "search" if self.shown["search"] or not self.items else "filter")]
        return h + [("d", "devices"), ("tab", "panel")]

    # ── estado de la reproducción ──

    def tick_poll(self) -> None:
        if self.visible_now:
            self.poll()

    @work(thread=True, exclusive=True, group="poll")
    def poll(self) -> None:
        if not shutil.which(BIN):
            return self.app.call_from_thread(self.set_state, None, "spotify_player is not installed "
                                             "(pacman -S spotify-player)", None)
        try:
            st, err = playback_of(api("/me/player", additional_types="episode")), ""
        except SpotifyError as e:
            st, err = None, str(e)
        cover = cover_path(st["album_id"], st["cover"]) if st else None
        self.app.call_from_thread(self.set_state, st, err, cover)

    def set_state(self, st: Optional[dict], err: str, cover: Optional[Path]) -> None:
        changed = bool(err) != bool(self.error)
        self.state, self.error, self.fetched = st, err, time.monotonic()
        self.query_one("#sp-cover", ImagePreview).set_image(cover)
        self.paint_now()
        if changed:
            self.update_hints()

    def progress(self) -> int:
        st = self.state or {}
        p = st.get("progress", 0)
        if st.get("playing"):
            p += int((time.monotonic() - self.fetched) * 1000)
        return min(p, (st.get("track") or {}).get("ms") or p)

    def paint_now(self) -> None:
        info = self.query_one("#sp-info", Static)
        now = self.query_one("#sp-now")
        t = Text()
        if self.error:
            t.append("\n✗ ", style=f"bold {THEME['status_error']}")
            t.append(self.error + "\n\n", style=THEME["foreground"])
            if "auth" in self.error.lower():
                t.append("press ", style=THEME["muted"])
                t.append("a", style=f"bold {THEME['primary']}")
                t.append(" to log in (opens the browser, needs Spotify Premium)\n", style=THEME["muted"])
                t.append("account, logins and daemon: Settings → Spotify", style=THEME["muted"])
            now.border_subtitle = " ✗ offline "
            info.update(t)
            return
        st = self.state
        if not st or not st.get("track"):
            t.append("\nNothing playing\n\n", style=f"bold {THEME['muted']}")
            t.append("enter", style=f"bold {THEME['primary']}")
            t.append(" on a track or ", style=THEME["muted"])
            t.append("p", style=f"bold {THEME['primary']}")
            t.append(" on a list to start · ", style=THEME["muted"])
            t.append("d", style=f"bold {THEME['primary']}")
            t.append(" picks the device", style=THEME["muted"])
            now.border_subtitle = f" ○ {st['device']} " if st and st.get("device") else " ○ idle "
            info.update(t)
            return
        tr, ms = st["track"], st["track"]["ms"]
        pos = self.progress()
        t.append(f"\n{tr['name']}\n", style=f"bold {THEME['primary']}")
        t.append(f"{tr['artist']}\n", style=THEME["foreground"])
        t.append(f"{tr['album']}\n\n", style=THEME["muted"])
        t.append(mmss(pos) + "  ", style=THEME["foreground"])
        t.append_text(bar(pos * 100 / ms if ms else 0, 40))
        t.append("  " + mmss(ms) + "\n\n", style=THEME["muted"])
        on, off, key = THEME["status_ok"], THEME["muted"], f"bold {THEME['primary']}"
        t.append("● playing" if st["playing"] else "○ paused", style=on if st["playing"] else off)
        t.append("    s", style=key)   # la tecla de cada control, al lado de su estado
        t.append(" shuffle ", style=THEME["muted"])
        t.append("●" if st["shuffle"] else "○", style=on if st["shuffle"] else off)
        t.append("    r", style=key)
        t.append(" repeat ", style=THEME["muted"])
        t.append(st["repeat"], style=THEME["foreground"] if st["repeat"] != "off" else off)
        if st.get("volume") is not None:
            t.append("    -/+", style=key)
            t.append(" volume ", style=THEME["muted"])
            t.append(f"{st['volume']}%", style=THEME["foreground"])
        now.border_subtitle = f" {'●' if st['playing'] else '○'} {st['device'] or 'no device'} "
        info.update(t)

    # ── Library / Tracks ──

    def paint_library(self) -> None:
        def row(key: str, icon: str, name: str, accent: bool = False) -> tuple[str, list]:
            label = Text()
            label.append(f"{icon}  ", style=THEME["primary"] if accent else THEME["muted"])
            label.append(name)
            return key, [label]

        def group(key: str, title: str, items: list, first: bool = False) -> list:
            head = [] if first else [(f"gap:{key}", [Text("")])]
            return head + [(f"hdr:{key}", [Text(title, style=f"bold {THEME['muted']}")])] + items

        if self.mode == "music":
            rows = [row(k, icon, name, True) for k, icon, name in LIBRARY]
            by_id = {p["id"]: p for p in self.playlists}
            favs = [by_id[i] for i in self.favs if i in by_id]
            if favs:
                rows += group("fav", f"Favorites ({len(favs)})", [row(f"pl:{p['id']}", "󰓎", p["name"], True) for p in favs])
            rest = [p for p in self.playlists if p["id"] not in self.favs]
            rows += group("pl", f"Playlists ({len(rest)})", [row(f"pl:{p['id']}", "󰲸", p["name"]) for p in rest])
        else:
            rows = [row("lib:episodes", "󰃀", "Saved episodes", True)]
            rows += group("sh", f"Shows ({len(self.shows)})", [row(f"sh:{s['id']}", "󰦔", s["name"]) for s in self.shows])
        tbl = self.query_one("#sp-library", Table)
        tbl.set_rows(rows)
        panel = self.query_one("#sp-library-panel")
        panel.border_title = " Library · Music " if self.mode == "music" else " Library · Podcasts "
        panel.border_subtitle = " m podcasts " if self.mode == "music" else " m music "

    def action_mode(self) -> None:
        self.mode = "podcasts" if self.mode == "music" else "music"
        self.paint_library()
        self.query_one("#sp-library", Table).first_selectable(0)
        if self.mode == "podcasts" and not self.shows:
            self.load_shows()
        self.update_hints()

    def action_favorite(self) -> None:
        """f: marca / desmarca como favorita la playlist seleccionada en Library
        (o la que muestra Tracks)."""
        f = self.app.focused
        key = self.query_one("#sp-library", Table).selected_key() or "" if f is not None and f.id == "sp-library" else ""
        pid = key[3:] if key.startswith("pl:") else self.source[1] if self.source[0] == "playlist" else ""
        if not pid:
            return self.app.notify_err("Pick a playlist first")
        name = next((p["name"] for p in self.playlists if p["id"] == pid), "Playlist")
        if pid in self.favs:
            self.favs.remove(pid)
            self.app.notify_ok(f"Removed from favorites: {name}")
        else:
            self.favs.append(pid)
            self.app.notify_ok(f"Added to favorites: {name}")
        save_favs(self.favs)
        self.paint_library()

    @work(thread=True, exclusive=True, group="shows")
    def load_shows(self) -> None:
        try:
            shows = [x for page in api_pages("/me/shows", lambda x: x.get("show")) for x in page]
        except SpotifyError as e:
            return self.app.call_from_thread(self.app.notify_err, str(e))
        self.shows = [{"id": x["id"], "name": x.get("name", "")} for x in shows if x.get("id")]
        self.app.call_from_thread(self.paint_library)

    @work(thread=True, exclusive=True, group="library")
    def load_playlists(self) -> None:
        try:
            pls = [p for page in api_pages("/me/playlists", playlist_of) for p in page]
        except SpotifyError:
            return   # el error ya lo muestra Now playing
        self.app.call_from_thread(self.set_playlists, pls)

    def set_playlists(self, pls: list[dict]) -> None:
        self.playlists = pls
        self.paint_library()

    @work(thread=True, exclusive=True, group="tracks")
    def load_list(self, key: str) -> None:
        """Llena Tracks con lo elegido en Library (o abierto desde una búsqueda)."""
        kind, _, ident = key.partition(":")
        try:
            if key == "lib:liked":
                return self.load_pages("Liked songs", ("liked", ""), api_pages("/me/tracks", lambda x: x.get("track")))
            if key == "lib:top":
                top = (api("/me/top/tracks", limit=PAGE, time_range="medium_term") or {}).get("items") or []
                return self.app.call_from_thread(self.show_items, "Top tracks",
                                                 [dict(x, type="track") for x in map(track_of, top) if x])
            if key == "lib:episodes":
                return self.load_pages("Saved episodes", ("", ""), api_pages("/me/episodes", lambda x: x.get("episode")))
            if kind == "sh":
                show = {"name": (api(f"/shows/{ident}") or {}).get("name", "Show")}
                return self.load_pages(show["name"], ("show", ident),
                                       api_pages(f"/shows/{ident}/episodes", lambda x: dict(x, show=show)))
            if key == "lib:queue":
                q = api("/me/player/queue") or {}
                items = [dict(x, type="track") for x in map(track_of, q.get("queue") or []) if x]
                return self.app.call_from_thread(self.show_items, "Queue", items)
            if key == "lib:albums":
                items = [album_row(a) for page in api_pages("/me/albums", lambda x: x.get("album")) for a in page]
                return self.app.call_from_thread(self.show_items, "Saved albums", items)
            if kind == "pl":
                name = (api(f"/playlists/{ident}", fields="name") or {}).get("name", "Playlist")
                try:
                    return self.load_pages(name, ("playlist", ident),
                                           api_pages(f"/playlists/{ident}/items", lambda x: x.get("item") or x.get("track")))
                except SpotifyError as e:
                    if e.code != 403:
                        raise
                    # Apps en development mode: solo se leen los temas de las playlists propias.
                    # Reproducirla entera (context_uri) sí se puede.
                    return self.app.call_from_thread(self.show_items, name, [], ("playlist", ident), False, False,
                                                     "Spotify only lists your own playlists")
            if kind == "al":
                head = api(f"/albums/{ident}") or {}
                album = {"name": head.get("name", ""), "id": ident}
                return self.load_pages(head.get("name", "Album"), ("album", ident),
                                       api_pages(f"/albums/{ident}", lambda x: dict(x, album=album)))
            if kind == "ar":
                name = (api(f"/artists/{ident}") or {}).get("name", "Artist")
                try:
                    top = (api(f"/artists/{ident}/top-tracks") or {}).get("tracks") or []
                    items = [dict(x, type="track", group="Top tracks") for x in map(track_of, top) if x]
                except SpotifyError:
                    items = []   # endpoint restringido para apps en development mode: quedan los álbumes
                pages = api_pages(f"/artists/{ident}/albums", limit=SEARCH_LIMIT, include_groups="album,single")
                for page in pages:   # de a 10 (development mode): hasta 50 álbumes
                    items += [album_row(a, "Albums") for a in page]
                    if len(items) >= 50:
                        break
                return self.app.call_from_thread(self.show_items, name, items, ("artist", ident))
        except SpotifyError as e:
            self.app.call_from_thread(self.app.notify_err, str(e))

    def load_pages(self, title: str, src: tuple[str, str], pages) -> None:
        """Muestra la primera página apenas llega y suma las demás sin mover el cursor
        (corre en el worker de load_list; corta si se eligió otra lista)."""
        worker, items = get_current_worker(), []
        for i, page in enumerate(pages):
            if worker.is_cancelled:
                return
            items += [dict(x, type="track") for x in map(track_of, page) if x]
            self.app.call_from_thread(self.show_items, title, list(items), src, i > 0, True)
        self.app.call_from_thread(self.show_items, title, list(items), src, True, False)

    def show_items(self, title: str, items: list[dict], src: tuple[str, str] = ("", ""),
                   keep: bool = False, more: bool = False, note: str = "", search: bool = False) -> None:
        """keep: misma lista con más filas (conserva el cursor y el filtro); more: faltan
        páginas; note: aviso en lugar de filas; search: resultado de una búsqueda."""
        if not keep and title != self.shown["title"]:
            self.query = ""   # lista nueva: sin filtro
        self.items, self.source = items, src
        self.shown = {"title": title, "more": more, "note": note, "search": search}
        q = self.query.lower()
        rows, group = [], None
        if note:
            rows.append(("hdr:note", [Text("󰌾  Not your playlist", style=THEME["muted"]),
                                      Text("p plays it", style=f"bold {THEME['primary']}"), "", ""]))
        for i, it in enumerate(items):
            if q and q not in f"{it['name']} {it.get('artist', '')} {it.get('album', '')}".lower():
                continue
            if it.get("group") and it["group"] != group:
                group = it["group"]
                if rows:
                    rows.append((f"gap:{group}", [Text("")] * 4))
                rows.append((f"hdr:{group}", [Text(group, style=f"bold {THEME['muted']}"), "", "", ""]))
            name = Text(it["name"])
            if it.get("played"):
                name = Text.assemble(("✓ ", THEME["status_ok"]), (it["name"], THEME["muted"]))
            if it.get("explicit"):
                name.append(" 🅴", style=THEME["muted"])
            if it["type"] != "track":
                name = Text.assemble(({"album": "󰀥  ", "playlist": "󰲸  ", "artist": "󰠃  ", "show": "󰦔  "}[it["type"]],
                                      THEME["primary"]), it["name"])
            rows.append((f"it:{i}", [name, Text(it.get("artist", ""), style=THEME["foreground"]),
                                     Text(it.get("album", ""), style=THEME["muted"]),
                                     Text(mmss(it["ms"]) if it.get("ms") else "", style=THEME["muted"])]))
        tbl = self.query_one("#sp-tracks", Table)
        episodes = bool(items) and all(it.get("kind") == "episode" for it in items)
        for col, label in zip(("title", "artist", "album"),
                              ("Episode", "Show", "Date") if episodes else ("Title", "Artist", "Album")):
            if str(tbl.columns[col].label) != label:
                tbl.columns[col].label = Text(label)
                tbl.refresh()
        if not keep:
            tbl._rows_sig = None   # lista nueva: arrancar arriba aunque las claves coincidan
        tbl.set_rows(rows)
        if tbl.row_count and not keep:
            tbl.first_selectable(0)
        panel = self.query_one("#sp-tracks-panel")
        panel.border_title = f" {title} · filter: {self.query} " if self.query else f" {title} "
        shown = sum(1 for k, _ in rows if k.startswith("it:"))
        count = f"{shown} of {len(items)}" if self.query else f"{len(items)} items"
        panel.border_subtitle = (f" {note} " if note else f" {count} · loading… " if more else
                                 f" {count} " if items else " empty ")
        self.update_hints()

    def current_item(self) -> Optional[dict]:
        key = self.query_one("#sp-tracks", Table).selected_key() or ""
        if not key.startswith("it:"):
            return None
        i = int(key[3:])
        return self.items[i] if i < len(self.items) else None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tid = event.data_table.id
        if tid == "sp-library":
            key = str(event.row_key.value)
            if not key.startswith(("hdr:", "gap:")):
                self.query_one("#sp-tracks-panel").border_subtitle = " loading… "
                self.load_list(key)
        elif tid == "sp-tracks":
            it = self.current_item()
            if not it:
                return
            if it["type"] == "track":
                self.play_track(it)
            else:   # álbum / playlist / artista de una búsqueda: abrirlo
                self.load_list(f"{it['type'][:2]}:{it['id']}")

    # ── acciones ──

    @work(thread=True, group="action")
    def player(self, method: str, path: str, body: Optional[dict] = None, note: str = "", **params) -> None:
        """Comando de reproducción. Sin dispositivo activo (404) pasa la reproducción
        al del daemon y reintenta una vez. Solo avisa los errores y `note`."""
        try:
            try:
                api(path, method, body, **params)
            except SpotifyError as e:
                if e.code != 404:
                    raise
                moved = to_own_device()
                self.app.call_from_thread(self.app.notify_ok, f"No active device: playing on {moved}")
                api(path, method, body, **params)
        except SpotifyError as e:
            self.app.call_from_thread(self.app.notify_err, str(e))
            self.poll()
            return
        if note:
            self.app.call_from_thread(self.app.notify_ok, note)
        time.sleep(0.5)   # que la Web API refleje el cambio antes de pedir el estado
        self.poll()

    def play_track(self, it: dict) -> None:
        """Arranca la lista mostrada (playlist, álbum, Liked songs, show) desde ese
        tema o episodio; uno de una búsqueda, de la cola o del top suena solo."""
        typ, ident = self.source
        uri = f"spotify:{it.get('kind', 'track')}:{it['id']}"
        if typ in ("playlist", "album", "liked", "show"):
            self.start_context(typ, ident, {"uri": uri}, f"Playing {it['name']}")
        else:
            self.player("PUT", "/me/player/play", {"uris": [uri]}, note=f"Playing {it['name']}")

    @work(thread=True, group="action")
    def start_context(self, typ: str, ident: str, offset: Optional[dict], note: str) -> None:
        try:
            body = {"context_uri": context_uri(typ, ident)}   # my_id() hace un pedido: en el worker
        except SpotifyError as e:
            return self.app.call_from_thread(self.app.notify_err, str(e))
        if offset:
            body["offset"] = offset
        self.app.call_from_thread(self.player, "PUT", "/me/player/play", body, note)

    def optimistic(self, **changes) -> None:
        """Pinta el cambio ya; el poll que sigue al comando lo confirma o corrige."""
        if self.state:
            self.state["progress"], self.fetched = self.progress(), time.monotonic()
            self.state.update(changes)
            self.paint_now()

    def action_toggle(self) -> None:
        playing = bool((self.state or {}).get("playing"))
        self.optimistic(playing=not playing)
        self.player("PUT", "/me/player/pause" if playing else "/me/player/play")

    def action_next(self) -> None:
        self.player("POST", "/me/player/next")

    def action_previous(self) -> None:
        self.player("POST", "/me/player/previous")

    def action_volume(self, sign: int) -> None:
        vol = (self.state or {}).get("volume")
        if vol is None:
            return self.app.notify_err("This device doesn't allow volume control")
        vol = max(0, min(100, vol + sign * VOL_STEP))
        self.optimistic(volume=vol)
        self.player("PUT", "/me/player/volume", volume_percent=vol)

    def action_seek(self, sign: int) -> None:
        if not (self.state or {}).get("track"):
            return
        pos = max(0, self.progress() + sign * SEEK_MS)
        self.optimistic()
        self.state["progress"] = pos
        self.player("PUT", "/me/player/seek", position_ms=pos)

    def action_shuffle(self) -> None:
        on = not (self.state or {}).get("shuffle")
        self.optimistic(shuffle=on)
        self.player("PUT", "/me/player/shuffle", state=str(on).lower())

    def action_repeat(self) -> None:
        nxt = REPEAT_NEXT.get((self.state or {}).get("repeat", "off"), "off")
        self.optimistic(repeat=nxt)
        self.player("PUT", "/me/player/repeat", state=nxt)

    @work(thread=True, group="action")
    def action_like(self) -> None:
        tr = (self.state or {}).get("track")
        if not tr or tr.get("kind") != "track":
            return
        try:
            try:
                api("/me/library", "PUT", uris=f"spotify:track:{tr['id']}")
            except SpotifyError as e:
                if e.code not in (404, 405):
                    raise
                api("/me/tracks", "PUT", ids=tr["id"])   # endpoint anterior de la API
        except SpotifyError as e:
            return self.app.call_from_thread(self.app.notify_err, str(e))
        self.app.call_from_thread(self.app.notify_ok, f"Saved to Liked songs: {tr['name']}")

    def action_play_list(self) -> None:
        """p: reproduce la lista entera que muestra Tracks (o lo seleccionado en Library)."""
        typ, ident = self.source
        f = self.app.focused
        if f is not None and f.id == "sp-library":
            key = self.query_one("#sp-library", Table).selected_key() or ""
            kind, _, ident = key.partition(":")
            typ = {"pl": "playlist", "sh": "show"}.get(kind, "liked" if key == "lib:liked" else "")
        if typ == "liked" or (typ in ("playlist", "album", "artist", "show") and ident):
            return self.start_context(typ, ident, None, "Playing Liked songs" if typ == "liked" else f"Playing the {typ}")
        self.app.notify_err("This list can't be played as a whole")

    def action_search(self) -> None:
        """/ con el foco en Tracks filtra la lista abierta (vacío = sin filtro); en
        Library (o sobre un resultado de búsqueda) busca en Spotify: música o
        podcasts según el modo de Library."""
        f = self.app.focused
        if f is not None and f.id == "sp-tracks" and self.items and not self.shown["search"]:
            def filtered(vals: Optional[dict]) -> None:
                if vals is not None:
                    self.query = vals.get("q", "")
                    self.show_items(self.shown["title"], self.items, self.source, False,
                                    self.shown["more"], self.shown["note"])

            return self.app.push_screen(FormModal(f"Filter {self.shown['title']}",
                                                  [Field("q", "Title, artist or album", self.query)],
                                                  hint="empty clears the filter"), filtered)

        def done(vals: Optional[dict]) -> None:
            if vals and vals.get("q"):
                self.query_one("#sp-tracks-panel").border_subtitle = " searching… "
                self.search(vals["q"], self.mode)

        label = "Tracks, albums, artists or playlists" if self.mode == "music" else "Podcasts or episodes"
        self.app.push_screen(FormModal("Search Spotify", [Field("q", label)]), done)

    @work(thread=True, exclusive=True, group="tracks")
    def search(self, q: str, mode: str = "music") -> None:
        types = "track,album,artist,playlist" if mode == "music" else "show,episode"
        try:
            res = api("/search", q=q, type=types, limit=SEARCH_LIMIT) or {}
        except SpotifyError as e:
            self.app.call_from_thread(self.app.notify_err, str(e))
            return

        def found(kind: str) -> list[dict]:
            return [x for x in (res.get(kind) or {}).get("items") or [] if x]

        items = [dict(x, type="track", group="Tracks") for x in map(track_of, found("tracks")) if x]
        items += [album_row(a, "Albums") for a in found("albums")]
        items += [{"type": "artist", "group": "Artists", "id": a.get("id", ""), "name": a.get("name", ""),
                   "artist": "", "album": "", "ms": 0} for a in found("artists")]
        items += [dict(p, type="playlist", group="Playlists", artist=p["owner"], album="", ms=0)
                  for p in map(playlist_of, found("playlists")) if p]
        items += [{"type": "show", "group": "Shows", "id": x.get("id", ""), "name": x.get("name", ""),
                   "artist": x.get("publisher", ""), "album": "", "ms": 0} for x in found("shows")]
        items += [dict(x, type="track", group="Episodes") for x in map(track_of, found("episodes")) if x]
        self.app.call_from_thread(self.show_items, f"Search: {q}", items, ("", ""), False, False, "", True)

    @work(thread=True, exclusive=True, group="devices")
    def action_devices(self) -> None:
        try:
            devs = devices()
        except SpotifyError as e:
            self.app.call_from_thread(self.app.notify_err, str(e))
            return
        rows = []
        for d in devs:
            active = bool(d.get("is_active"))
            rows.append((str(d.get("id")),
                         [Text("●" if active else "○", style=THEME["status_ok"] if active else THEME["muted"]),
                          d.get("name", "?"), Text(str(d.get("type") or ""), style=THEME["muted"]),
                          Text(f"{d['volume_percent']}%" if d.get("volume_percent") is not None else "",
                               style=THEME["muted"])]))
        if not rows:
            self.app.call_from_thread(self.app.notify_err, "No Spotify devices online")
            return

        def done(dev: Optional[str]) -> None:
            if dev:
                self.player("PUT", "/me/player", {"device_ids": [dev], "play": bool((self.state or {}).get("playing"))},
                            note="Playback moved")

        self.app.call_from_thread(self.app.push_screen,
                                  PickModal("Play on", ["", "Device", "Type", "Volume"], rows), done)

    def action_auth(self) -> None:
        """Login en la misma terminal: spotify_player interactivo pide solo lo que
        falta (streaming) y abre el navegador; se sale con q. `authenticate` no
        sirve: fuerza también el login roto del client de ncspot."""
        if daemon_running():
            return self.app.notify_ok("Already logged in (spotify_player is running)")
        sync_tokens()
        with self.app.suspend():
            print("Log in to Spotify in the browser that opens. When spotify_player shows up, quit it with q.\n")
            subprocess.run([BIN])
        start_daemon()
        self.action_refresh()

    def action_refresh(self) -> None:
        self.poll()
        if logged_in():
            self.load_playlists()
            self.load_list("lib:liked")
            if self.mode == "podcasts":
                self.load_shows()


# ── Gestión: sección Spotify de Settings ──────────────────

# Playback: (clave, sección de app.toml, etiqueta, tipo, default de spotify_player)
PLAYBACK = [("name", "device", "Device name", "str", "spotify-player"),
            ("device_type", "device", "Device type", "type", "speaker"),
            ("volume", "device", "Start volume", "pct", 70),
            ("bitrate", "device", "Bitrate", "bitrate", 320),
            ("normalization", "device", "Normalization", "bool", False),
            ("autoplay", "device", "Autoplay", "bool", False),
            ("audio_cache", "device", "Audio cache", "bool", False),
            ("enable_notify", "", "Track notifications", "bool", True)]


class SpotifySettingsView(DView):
    """Settings → Spotify: lo que no es escuchar música. Cuenta y daemon
    (logins, arrancar/parar spotify_player, autoarranque, client ID, carátulas),
    Playback (app.toml: dispositivo, calidad, volumen…) y el orden de las
    favoritas. Escuchar sigue en la TUI (Super+Y, `o` desde acá), como Finances
    con la de gastos."""

    FOCUS = "#spm-acc"
    TABLES = ["spm-acc", "spm-cfg", "spm-fav"]
    DEFAULT_CSS = css("""
    SpotifySettingsView #spm-acc-panel { width: 1fr; }
    SpotifySettingsView #spm-right { width: 1fr; }
    SpotifySettingsView #spm-cfg-panel { height: auto; }
    SpotifySettingsView #spm-cfg { height: auto; }
    SpotifySettingsView #spm-fav-panel { height: 1fr; }
    """)
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False, description="next panel"),
        Binding("shift+tab", "cycle(-1)", show=False, description="previous panel"),
        Binding("r", "restart", "restart spotify_player"),
        Binding("K", "move(-1)", "move favorite up"),
        Binding("J", "move(1)", "move favorite down"),
        Binding("x", "remove_fav", "remove favorite"),
        Binding("o", "open_tui", "open the Spotify TUI"),
        Binding("R", "reload", "reload", show=False),
    ]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.status: dict = {}
        self.names: dict[str, tuple[str, str]] = {}   # id de playlist → (nombre, dueño)
        self.dirty = False                            # app.toml cambió con el daemon corriendo
        self._busy = False
        self._started = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Panel(Table(id="spm-acc", show_header=False), title="Account & daemon", id="spm-acc-panel")
            with Vertical(id="spm-right"):
                yield Panel(Table(id="spm-cfg", show_header=False), title="Playback", id="spm-cfg-panel")
                yield Panel(Table(id="spm-fav"), title="Favorites", id="spm-fav-panel")

    def on_mount(self) -> None:
        for tid, cols in (("spm-acc", [("", 18), ("", 44)]), ("spm-cfg", [("", 20), ("", 22)]),
                          ("spm-fav", [("#", 3), ("Playlist", 32), ("Owner", 16)])):
            t = self.query_one(f"#{tid}", Table)
            for label, w in cols:
                t.add_column(label, width=w)

    def on_show(self) -> None:
        # Como el reproductor: nada de procesos ni API hasta que se ve la sección
        if not self._started:
            self._started = True
            self.set_interval(5, lambda: self.visible_now and self.refresh_status())
            self.load_names()
        self.refresh_status()

    # ── datos ──

    @work(thread=True, exclusive=True, group="spm-status")
    def refresh_status(self) -> None:
        st = {"version": sp.version(), "pids": sp.daemon_pids(), "stream": logged_in(),
              "token": sp.token_status(), "client": sp.client_id(), "conf": sp.tui_conf(),
              "covers": sp.dir_size(sp.COVERS) if sp.COVERS.exists() else 0,
              "me": self.status.get("me")}
        if st["me"] is None and st["stream"] and st["token"]["exists"]:
            try:
                st["me"] = api("/me") or {}
            except SpotifyError as e:
                st["me"] = {"error": str(e)}
        self.app.call_from_thread(self.paint, st)

    @work(thread=True, exclusive=True, group="spm-names")
    def load_names(self) -> None:
        """Nombres de las favoritas (el archivo guarda solo los ids)."""
        if not logged_in():
            return
        names = {}
        try:
            for page in api_pages("/me/playlists", playlist_of):
                names.update({p["id"]: (p["name"], p["owner"]) for p in page})
        except SpotifyError:
            pass
        for pid in load_favs():   # una favorita que no está en la biblioteca (de otro usuario)
            if pid not in names:
                try:
                    p = api(f"/playlists/{pid}", fields="name,owner(display_name)") or {}
                    names[pid] = (p.get("name", pid), (p.get("owner") or {}).get("display_name", ""))
                except SpotifyError:
                    pass
        self.app.call_from_thread(self.set_names, names)

    def set_names(self, names: dict) -> None:
        self.names = names
        self.paint_favs()

    # ── pintar ──

    def paint(self, st: dict) -> None:
        self.status = st
        ok, warn, err, muted = THEME["status_ok"], THEME["status_warn"], THEME["status_error"], THEME["muted"]

        def row(key: str, name: str, value: Text) -> tuple[str, list]:
            return key, [Text(name, style=muted), value]

        def state(on: bool, text: str, off_style: str = muted) -> Text:
            return Text(("● " if on else "○ ") + text, style=ok if on else off_style)

        rows = []
        if st["version"]:
            rows.append(row("player", "spotify_player", Text(f"✓ {st['version']}", style=ok)))
        else:
            rows.append(row("player", "spotify_player", Text("✗ not installed (pacman -S spotify-player)", style=err)))
        pids = st["pids"]
        rows.append(row("daemon", "Daemon", state(bool(pids), f"running (pid {pids[0]})" if pids else "stopped")))
        rows.append(row("autostart", "Start on login", state(st["conf"].get("autostart") == "on",
                                                             "on" if st["conf"].get("autostart") == "on" else "off")))
        rows.append(("gap:login", [Text(""), Text("")]))
        tok = st["token"]
        if not tok["exists"]:
            web = Text("✗ no token · enter to log in", style=err)
        elif tok["expires"]:
            left = (tok["expires"] - datetime.now(timezone.utc)).total_seconds()
            web = Text("✓ token · " + (f"expires in {int(left // 60)} min" if left > 0 else
                                       "expired (the daemon renews it)"), style=ok if left > 0 or pids else warn)
        else:
            web = Text("✓ token", style=ok)
        rows.append(row("web", "Web API login", web))
        rows.append(row("stream", "Streaming login", Text("✓ credentials saved", style=ok) if st["stream"]
                        else Text("✗ missing · enter to log in", style=err)))
        rows.append(row("client", "Client ID", Text(st["client"] or "none (shared ncspot client)",
                                                    style=THEME["foreground"] if st["client"] else warn)))
        me = st.get("me") or {}
        if me.get("error"):
            acct = Text(f"✗ {me['error']}", style=err)
        elif me:
            prem = me.get("product") == "premium"
            acct = Text(f"{me.get('display_name') or me.get('id', '?')} · ", style=THEME["foreground"])
            acct.append(me.get("product", "?"), style=ok if prem else err)
            if not prem:
                acct.append(" (Premium needed to play)", style=err)
        else:
            acct = Text("not logged in", style=muted)
        rows.append(row("me", "Account", acct))
        rows.append(("gap:cache", [Text(""), Text("")]))
        rows.append(row("covers", "Cover cache", Text(human(st["covers"]) + " · enter to clear", style=muted)))
        self.query_one("#spm-acc", Table).set_rows(rows)
        self.query_one("#spm-acc-panel").border_subtitle = " ● running " if pids else " ○ stopped "
        self.paint_cfg()
        self.paint_favs()
        self.update_hints()

    def paint_cfg(self) -> None:
        rows = []
        for key, sec, label, kind, default in PLAYBACK:
            v = sp.config_get(key, sec, default)
            if kind == "bool":
                val = Text(("● on" if v else "○ off"), style=THEME["status_ok"] if v else THEME["muted"])
            else:
                val = Text(f"{v}%" if kind == "pct" else f"{v} kbps" if kind == "bitrate" else str(v))
            rows.append((key, [Text(label, style=THEME["muted"]), val]))
        self.query_one("#spm-cfg", Table).set_rows(rows)
        self.query_one("#spm-cfg-panel").border_subtitle = (" r restart to apply " if self.dirty and self.status.get("pids")
                                                            else " app.toml ")

    def paint_favs(self) -> None:
        favs = load_favs()
        rows = []
        for i, pid in enumerate(favs, 1):
            name, owner = self.names.get(pid, (pid, ""))
            rows.append((pid, [Text(str(i), style=THEME["muted"]), name, Text(owner, style=THEME["muted"])]))
        self.query_one("#spm-fav", Table).set_rows(rows)
        self.query_one("#spm-fav-panel").border_subtitle = (f" {len(favs)} · f in the player adds " if favs
                                                            else " none · f in the player adds ")

    # ── teclas ──

    def focused_table(self) -> str:
        f = self.app.focused
        return f.id if isinstance(f, Table) and f.id in self.TABLES else "spm-acc"

    def action_cycle(self, step: int) -> None:
        i = self.TABLES.index(self.focused_table())
        self.query_one(f"#{self.TABLES[(i + step) % len(self.TABLES)]}", Table).focus()

    def hints(self) -> list[tuple[str, str]]:
        tid = self.focused_table()
        h = {"spm-acc": [("enter", "toggle / log in / edit")],
             "spm-cfg": [("enter", "edit / toggle")],
             "spm-fav": [("K", "up"), ("J", "down"), ("x", "remove")]}[tid]
        if self.status.get("pids"):
            h.append(("r", "restart"))
        return h + [("o", "open player"), ("tab", "panel"), ("q", "quit")]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = event.row_key.value if event.row_key else None
        if not key or key.startswith(("hdr:", "gap:")):
            return
        if event.data_table.id == "spm-acc":
            getattr(self, f"acc_{key}", lambda: None)()
        elif event.data_table.id == "spm-cfg":
            self.edit_cfg(key)

    # Account & daemon

    def acc_daemon(self) -> None:
        if self.status.get("pids"):
            self.app.push_screen(ConfirmModal("Stop spotify_player", "Stop the daemon? Music on this device stops."),
                                 lambda yes: yes and self.run_bg(sp.stop_daemon, "spotify_player stopped"))
        elif not logged_in():
            self.app.notify_err("Log in first (Streaming login)")
        else:
            self.run_bg(start_daemon, "spotify_player started")

    def acc_autostart(self) -> None:
        on = sp.tui_conf().get("autostart") == "on"
        sp.tui_conf_set("autostart", "off" if on else "on")
        self.app.notify_ok("spotify_player won't start on login" if on else "spotify_player starts on login")
        self.refresh_status()

    def acc_web(self) -> None:
        self.login(web=True)

    def acc_stream(self) -> None:
        self.login(web=False)

    def login(self, web: bool) -> None:
        """Los dos logins corren en la misma terminal con el daemon parado
        (renovar o reescribir los tokens con el daemon andando lo deja con unos
        viejos). Web API: `authenticate` (el segundo link, del client de ncspot,
        falla: se corta con ctrl+c). Streaming: spotify_player interactivo, que
        pide solo lo que falta; se sale con q."""
        def go(yes: bool = True) -> None:
            if not yes:
                return
            was = bool(sp.daemon_pids())
            sp.stop_daemon()
            with self.app.suspend():
                if web:
                    print("Accept the FIRST link in the browser (configured client).\n"
                          "The second one (ncspot fallback client) fails: press ctrl+c when it shows up.\n")
                    try:
                        subprocess.run([BIN, "authenticate"])
                    except KeyboardInterrupt:
                        pass
                else:
                    sync_tokens()
                    print("Log in to Spotify in the browser that opens. When spotify_player shows up, quit it with q.\n")
                    subprocess.run([BIN])
            if was or logged_in():
                start_daemon()
            self.status["me"] = None
            self.refresh_status()
            self.load_names()

        if sp.daemon_pids():
            self.app.push_screen(ConfirmModal("Log in", "spotify_player has to stop while you log in. Go on?"), go)
        else:
            go()

    def acc_client(self) -> None:
        def done(v: Optional[dict]) -> None:
            if v is None:
                return
            cid = v["client"].strip()
            sp.config_set("client_id", cid)
            self.mark_dirty()
            self.app.notify_ok("Client ID saved · log in to the Web API again")
            self.refresh_status()

        self.app.push_screen(FormModal("Client ID", [Field("client", "Client ID", sp.client_id(),
                                                           "from developer.spotify.com/dashboard")],
                                       hint="redirect URI of the app: http://127.0.0.1:8989/login",
                                       validate=lambda v: None if re.fullmatch(r"[0-9a-f]{32}", v["client"].strip())
                                       else "32 hex characters"), done)

    def acc_covers(self) -> None:
        def done(yes: bool) -> None:
            if yes:
                sp.clear_covers()
                self.app.notify_ok("Cover cache cleared")
                self.refresh_status()

        self.app.push_screen(ConfirmModal("Cover cache", "Delete the downloaded album covers? They download again."),
                             done)

    def acc_me(self) -> None:
        self.status["me"] = None
        self.refresh_status()

    def acc_player(self) -> None:
        pass

    @work(thread=True, exclusive=True, group="spm-daemon")
    def run_bg(self, fn, msg: str) -> None:
        fn()
        self.app.call_from_thread(self.app.notify_ok, msg)
        self.refresh_status()

    def action_restart(self) -> None:
        if not self.status.get("pids"):
            return self.acc_daemon()
        self.dirty = False
        self.run_bg(sp.restart_daemon, "spotify_player restarted")

    # Playback

    def mark_dirty(self) -> None:
        self.dirty = bool(sp.daemon_pids())
        self.paint_cfg()
        self.update_hints()

    def edit_cfg(self, key: str) -> None:
        _k, sec, label, kind, default = next(p for p in PLAYBACK if p[0] == key)
        cur = sp.config_get(key, sec, default)
        if kind == "bool":
            sp.config_set(key, not cur, sec)
            return self.mark_dirty()
        if kind == "type":
            field = Field(key, label, str(cur), choices=[(t, t) for t in sp.DEVICE_TYPES])
        elif kind == "bitrate":
            field = Field(key, label, str(cur), choices=[(f"{b} kbps", str(b)) for b in sp.BITRATES])
        else:
            field = Field(key, label, str(cur))

        def check(v: dict) -> Optional[str]:
            x = v[key].strip()
            if kind == "pct" and not (x.isdigit() and 0 <= int(x) <= 100):
                return "0 to 100"
            if kind == "str" and not x:
                return "can't be empty"
            return None

        def done(v: Optional[dict]) -> None:
            if v is None:
                return
            x = v[key].strip()
            sp.config_set(key, int(x) if kind in ("pct", "bitrate") else x, sec)
            self.mark_dirty()

        self.app.push_screen(FormModal(label, [field], validate=check), done)

    # Favorites

    def action_move(self, step: int) -> None:
        if self.focused_table() != "spm-fav":
            return
        tbl = self.query_one("#spm-fav", Table)
        pid, favs = tbl.selected_key(), load_favs()
        if pid not in favs:
            return
        i = favs.index(pid)
        j = i + step
        if 0 <= j < len(favs):
            favs[i], favs[j] = favs[j], favs[i]
            save_favs(favs)
            self.paint_favs()
            tbl.move_cursor(row=j)

    def action_remove_fav(self) -> None:
        if self.focused_table() != "spm-fav":
            return
        pid, favs = self.query_one("#spm-fav", Table).selected_key(), load_favs()
        if pid in favs:
            favs.remove(pid)
            save_favs(favs)
            self.paint_favs()
            self.app.notify_ok(f"Removed from favorites: {self.names.get(pid, (pid,))[0]}")

    def action_open_tui(self) -> None:
        cmd = ["bash", str(LAUNCHER)] if LAUNCHER.exists() else [sys.executable, str(Path(__file__).resolve())]
        subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def action_reload(self) -> None:
        self.status["me"] = None
        self.refresh_status()
        self.load_names()



def SpotifyApp() -> ViewApp:
    return ViewApp(SpotifyView, title="Spotify")


if __name__ == "__main__":
    SpotifyApp().run()
