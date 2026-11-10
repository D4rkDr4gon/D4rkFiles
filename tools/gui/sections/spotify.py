"""Spotify (GUI): en modo GUI escuchar es la app oficial (Mod+Y abre `spotify`); acá está la paridad
con SpotifySettingsView (gestión de spotify_player, backend spotify_api.py sin Textual):
- Account & daemon: versión, daemon (arrancar/parar con confirmación, reiniciar), arranque al
  iniciar sesión, logins de la Web API y de streaming (en una kitty, con el daemon parado como en
  la TUI), client ID (32 hex), cuenta (Premium o no) y la caché de carátulas (borrar).
- Playback: app.toml (dispositivo, tipo, volumen, bitrate, normalización, autoplay, caché, avisos);
  con el daemon andando pide reiniciar para aplicar.
- Favorites: orden (subir/bajar) y quitar; los nombres se buscan en segundo plano.
También abre la TUI de spotify_player."""

from __future__ import annotations

import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import _lib as L

UI: dict = {}
STATE: dict = {"me": None, "names": {}, "names_busy": False, "dirty": False, "busy": ""}
PLAYBACK = [("name", "device", "Device name", "str", "spotify-player"),
            ("device_type", "device", "Device type", "type", "speaker"),
            ("volume", "device", "Start volume", "pct", 70),
            ("bitrate", "device", "Bitrate", "bitrate", 320),
            ("normalization", "device", "Normalization", "bool", False),
            ("autoplay", "device", "Autoplay", "bool", False),
            ("audio_cache", "device", "Audio cache", "bool", False),
            ("enable_notify", "", "Track notifications", "bool", True)]
SPDIR = L.TOOLS
LAUNCHER = Path.home() / ".config" / "waybar" / "scripts" / "spotify-launch.sh"


def SP():
    if str(SPDIR) not in sys.path:
        sys.path.insert(0, str(SPDIR))
    import spotify_api
    return spotify_api


def human(n) -> str:
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.0f} TB"


def bg(name: str, fn) -> None:
    def run():
        try:
            fn()
        finally:
            if STATE["busy"] == name:
                STATE["busy"] = ""
    STATE["busy"] = name
    threading.Thread(target=run, daemon=True).start()


def load_me() -> None:
    sp = SP()
    try:
        STATE["me"] = sp.api("/me") or {}
    except sp.SpotifyError as e:
        STATE["me"] = {"error": str(e)}


def load_names() -> None:
    sp = SP()
    if STATE["names_busy"] or not sp.logged_in():
        return
    STATE["names_busy"] = True

    def run():
        names = {}
        try:
            for page in sp.api_pages("/me/playlists", sp.playlist_of):
                names.update({p["id"]: (p["name"], p["owner"]) for p in page})
            for pid in sp.load_favs():
                if pid not in names:
                    p = sp.api(f"/playlists/{pid}", fields="name,owner(display_name)") or {}
                    names[pid] = (p.get("name", pid), (p.get("owner") or {}).get("display_name", ""))
        except sp.SpotifyError:
            pass
        finally:
            STATE["names"] = names or STATE["names"]
            STATE["names_busy"] = False
    threading.Thread(target=run, daemon=True).start()


def get() -> dict:
    sp = SP()
    ver, pids, stream, tok = sp.version(), sp.daemon_pids(), sp.logged_in(), sp.token_status()
    conf = sp.tui_conf()
    if STATE["me"] is None and stream and tok["exists"]:
        STATE["me"] = {}
        threading.Thread(target=load_me, daemon=True).start()
    if not STATE["names"]:
        load_names()
    if not tok["exists"]:
        web = "✗ no token · log in"
    elif tok["expires"]:
        left = (tok["expires"] - datetime.now(timezone.utc)).total_seconds()
        web = "✓ token · " + (f"expires in {int(left // 60)} min" if left > 0 else "expired (the daemon renews it)")
    else:
        web = "✓ token"
    me = STATE["me"] or {}
    if me.get("error"):
        acct = f"✗ {me['error']}"
    elif me:
        acct = f"{me.get('display_name') or me.get('id', '?')} · {me.get('product', '?')}" + \
            ("" if me.get("product") == "premium" else " (Premium needed to play)")
    else:
        acct = "not logged in" if not stream else "…"
    player = [L.button("open", "Open Spotify", "The official app (GUI mode)", "Open"),
              L.button("tui", "Open the Spotify TUI", "spotify_player based player", "Open")]
    acc = [L.info("ver", "spotify_player", f"✓ {ver}" if ver else "✗ not installed (pacman -S spotify-player)"),
           L.toggle("daemon", "Daemon", f"running (pid {pids[0]})" if pids else "stopped", bool(pids))]
    if pids:
        acc.append(L.button("restart", "Restart spotify_player", "Applies Playback changes" if STATE["dirty"] else "", "Restart"))
    acc += [L.toggle("autostart", "Start on login", "spotify_player daemon", conf.get("autostart") == "on"),
            L.button("web", "Web API login", web, "Log in"),
            L.button("stream", "Streaming login", "✓ credentials saved" if stream else "✗ missing · log in", "Log in"),
            L.button("client", "Client ID", sp.client_id() or "none (shared ncspot client)", "Edit"),
            L.button("me", "Account", acct, "Reload"),
            L.button("covers", "Cover cache", human(sp.dir_size(sp.COVERS)) if sp.COVERS.exists() else "0 B", "Clear", danger=True)]
    if STATE["busy"]:
        acc.append(L.info("busy", "Working", STATE["busy"]))
    pb = []
    for key, sec, label, kind, default in PLAYBACK:
        v = sp.config_get(key, sec, default)
        if kind == "bool":
            pb.append(L.toggle(f"cfg:{key}", label, "app.toml", bool(v)))
        elif kind == "type":
            pb.append(L.choice(f"cfg:{key}", label, "app.toml", str(v), list(sp.DEVICE_TYPES)))
        elif kind == "bitrate":
            pb.append(L.choice(f"cfg:{key}", label, "kbps", str(v), [str(b) for b in sp.BITRATES]))
        elif kind == "pct":
            pb.append(L.slider(f"cfg:{key}", label, "%", int(v), 0, 100, 5))
        else:
            pb.append(L.button(f"cfg:{key}", label, str(v), "Edit"))
    favs = sp.load_favs()
    fr = []
    for i, pid in enumerate(favs):
        name, owner = STATE["names"].get(pid, (pid, ""))
        acts = ([L.action(f"up:{pid}", "Up")] if i else []) + ([L.action(f"down:{pid}", "Down")] if i < len(favs) - 1 else []) + \
            [L.action(f"rmfav:{pid}", "Remove", True)]
        fr.append(L.item(f"fav:{pid}", f"{i + 1}. {name}", sub=owner, glyph="󰲸", actions=acts))
    return L.page("Spotify", "Official app to listen · spotify_player management", [
        L.group("Player", player), L.group("Account & daemon · " + ("● running" if pids else "○ stopped"), acc),
        L.group("Playback · app.toml" + (" · restart to apply" if STATE["dirty"] and pids else ""), pb),
        L.group(f"Favorites · {len(favs)} · f in the player adds", fr or [L.info("nofav", "None yet", "f in the player adds one")])],
        refresh=2 if STATE["busy"] else 5)


def mark_dirty() -> None:
    STATE["dirty"] = bool(SP().daemon_pids())


def set_value(key, value):
    sp = SP()
    op, _, arg = key.partition(":")
    if key == "daemon":
        if not value:
            return act("daemon_stop")
        if not sp.logged_in():
            return L.fail("Log in first (Streaming login)")
        bg("starting spotify_player…", sp.start_daemon)
        return L.ok("Starting spotify_player…")
    if key == "autostart":
        sp.tui_conf_set("autostart", "on" if value else "off")
        return L.ok("spotify_player starts on login" if value else "spotify_player won't start on login")
    if op == "cfg":
        _k, sec, _label, kind, _d = next(p for p in PLAYBACK if p[0] == arg)
        sp.config_set(arg, bool(value) if kind == "bool" else int(float(value)) if kind in ("pct", "bitrate") else str(value), sec)
        mark_dirty()
        return L.ok()
    return L.fail("Unknown setting")


def login_cmd(web: bool) -> list:
    code = (f"import sys; sys.path.insert(0, {str(SPDIR)!r}); import subprocess, spotify_api as sp\n"
            "was = bool(sp.daemon_pids()); sp.stop_daemon()\n")
    if web:
        code += ("print('Accept the FIRST link in the browser (configured client).\\n'"
                 "'The second one (ncspot fallback client) fails: press ctrl+c when it shows up.\\n')\n"
                 "try:\n    subprocess.run([sp.BIN, 'authenticate'])\nexcept KeyboardInterrupt:\n    pass\n")
    else:
        code += ("sp.sync_tokens()\nprint('Log in to Spotify in the browser that opens. "
                 "When spotify_player shows up, quit it with q.\\n')\nsubprocess.run([sp.BIN])\n")
    code += "if was or sp.logged_in():\n    sp.start_daemon()\n"
    return ["kitty", "--class", "spotify-login", "--title", "Spotify login", "-e", sys.executable, "-c", code]


def act(key: str, text=None):
    sp = SP()
    op, _, arg = key.partition(":")
    if op == "open":
        L.detach(["spotify"])
        return {"ok": True, "msg": "", "close": True}
    if op == "tui":
        L.detach(["bash", str(LAUNCHER)] if LAUNCHER.exists() else [sys.executable, str(SPDIR / "spotify_tui.py")])
        return L.ok()
    if op == "daemon_stop":
        if not L.yes(text):
            return L.confirm("daemon_stop", "Stop spotify_player", "Stop the daemon? Music on this device stops.", ok_label="Stop")
        bg("stopping spotify_player…", sp.stop_daemon)
        return L.ok("spotify_player stopped")
    if op == "restart":
        STATE["dirty"] = False
        bg("restarting spotify_player…", sp.restart_daemon)
        return L.ok("Restarting spotify_player…")
    if op in ("web", "stream"):
        if sp.daemon_pids() and not L.yes(text):
            return L.confirm(op, "Log in", "spotify_player has to stop while you log in. Go on?", ok_label="Log in")
        STATE["me"], STATE["names"] = None, {}
        L.detach(login_cmd(op == "web"))
        return L.ok("Log in in the terminal that opened")
    if op == "client":
        fields = lambda v: [{"name": "client", "label": "CLIENT ID (developer.spotify.com/dashboard)", "text": v}]  # noqa: E731
        hint = "Redirect URI of the app: http://127.0.0.1:8989/login"
        if text is None:
            return L.form("client", "Client ID", fields(sp.client_id()), hint=hint)
        cid = L.parse_form(text).get("client", "").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", cid):
            return L.form("client", "Client ID", fields(cid), hint=hint, error="32 hex characters")
        sp.config_set("client_id", cid)
        mark_dirty()
        return L.ok("Client ID saved · log in to the Web API again")
    if op == "me":
        STATE["me"] = None
        load_names()
        return L.ok()
    if op == "covers":
        if not L.yes(text):
            return L.confirm("covers", "Cover cache", "Delete the downloaded album covers? They download again.", ok_label="Clear")
        sp.clear_covers()
        return L.ok("Cover cache cleared")
    if op == "cfg":
        _k, sec, label, kind, default = next(p for p in PLAYBACK if p[0] == arg)
        if text is None:
            return L.form(key, label, [{"name": "v", "label": label.upper(), "text": str(sp.config_get(arg, sec, default))}])
        v = L.parse_form(text).get("v", "").strip()
        if not v:
            return L.form(key, label, [{"name": "v", "label": label.upper(), "text": v}], error="Can't be empty")
        sp.config_set(arg, v, sec)
        mark_dirty()
        return L.ok()
    favs = sp.load_favs()
    if op in ("up", "down") and arg in favs:
        i = favs.index(arg)
        j = i - 1 if op == "up" else i + 1
        if 0 <= j < len(favs):
            favs[i], favs[j] = favs[j], favs[i]
            sp.save_favs(favs)
        return L.ok()
    if op == "rmfav" and arg in favs:
        favs.remove(arg)
        sp.save_favs(favs)
        return L.ok(f"Removed from favorites: {STATE['names'].get(arg, (arg,))[0]}")
    return L.ok()
