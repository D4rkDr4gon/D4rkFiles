#!/usr/bin/env python3
"""
spotify_api.py — backend de la TUI de Spotify, sin Textual.

Maneja spotify_player (daemon, login, tokens, su config
~/.config/spotify-player/app.toml), la Web API de Spotify, las playlists
favoritas y la config propia de la TUI (~/.config/dotfiles/spotify-tui.conf).
Lo usan spotify_tui.py (el reproductor, Super+Y, y la sección Spotify de
Settings) y el autoarranque de la sesión:

    spotify_api.py --autostart   arranca el daemon si autostart=on (exec-once de config/hypr/hyprland.lua)

Por qué la Web API y no la CLI de spotify_player, y el truco de los tokens del
client de ncspot: docstring de spotify_tui.py y docs/customization.md (Spotify).
Para probar sin tocar lo real: SPOTIFY_PLAYER_BIN, SPOTIFY_PLAYER_CACHE,
XDG_CONFIG_HOME (app.toml), SPOTIFY_TUI_CONF, SPOTIFY_TUI_STATE y SPOTIFY_TUI_API.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BIN = os.environ.get("SPOTIFY_PLAYER_BIN", "spotify_player")
_CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
COVERS = _CACHE_HOME / "spotify-tui" / "covers"
SP_CACHE = Path(os.environ.get("SPOTIFY_PLAYER_CACHE") or _CACHE_HOME / "spotify-player")
SP_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "spotify-player" / "app.toml"
NCSPOT_ID = "d420a117a32841c2b3474932e49fb54b"   # client de respaldo de spotify_player
API = os.environ.get("SPOTIFY_TUI_API", "https://api.spotify.com/v1")
PAGE = 50
MAX_TRACKS = 3000   # tope por lista (una playlist de 3000 temas son 60 pedidos)
SEARCH_LIMIT = 10   # máximo que aceptan /search y /artists/{id}/albums en development mode
STATE_DIR = Path(os.environ.get("SPOTIFY_TUI_STATE") or
                 Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "dotfiles" / "spotify-tui")
FAVS = STATE_DIR / "favorites.json"   # ids de las playlists favoritas, en orden
POLL = 3            # segundos entre pedidos de estado
VOL_STEP = 5        # % por cada +/-
SEEK_MS = 10_000


class SpotifyError(Exception):
    def __init__(self, msg: str, code: int = 0) -> None:
        super().__init__(msg)
        self.code = code


# ── spotify_player: daemon, login y tokens ────────────────

def daemon_pids() -> list[int]:
    """PIDs de spotify_player (el daemon, o el interactivo del login)."""
    try:
        out = subprocess.run(["pgrep", "-x", "spotify_player"], capture_output=True, text=True).stdout
    except OSError:
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def daemon_running() -> bool:
    return bool(daemon_pids())


def logged_in() -> bool:
    """Login de streaming hecho (credenciales de librespot en el cache)."""
    return (SP_CACHE / "credentials.json").exists()


def _config() -> dict:
    try:
        import tomllib
        return tomllib.loads(SP_CONFIG.read_text())
    except (OSError, ValueError, ImportError):
        return {}


def client_id() -> str:
    return str(_config().get("client_id") or "")


def own_device() -> str:
    """Nombre del dispositivo de Spotify Connect que crea el daemon."""
    dev = _config().get("device")
    return str(dev.get("name") or "spotify-player") if isinstance(dev, dict) else "spotify-player"


def _write_private(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load_favs() -> list[str]:
    try:
        data = json.loads(FAVS.read_text())
    except (OSError, ValueError):
        return []
    return [x for x in data if isinstance(x, str)] if isinstance(data, list) else []


def save_favs(ids: list[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FAVS.with_name(FAVS.name + ".tmp")
    tmp.write_text(json.dumps(ids))
    os.replace(tmp, FAVS)


def token_expiry(tok: dict) -> datetime:
    # chrono escribe nanosegundos; fromisoformat acepta hasta microsegundos
    return datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", tok["expires_at"]).replace("Z", "+00:00"))


def sync_tokens() -> None:
    """Renueva el token de la Web API del client propio si vence en menos de 10
    min y lo copia como token del client de ncspot (ver docstring del módulo).
    Solo con el daemon parado: renovar rota el refresh token y dejaría al daemon
    con uno viejo."""
    cid = client_id()
    prim = SP_CACHE / f"{cid}_token.json"
    if not cid or cid == NCSPOT_ID or not prim.exists() or daemon_running():
        return
    try:
        tok = json.loads(prim.read_text())
        exp = token_expiry(tok)
        now = datetime.now(timezone.utc)
        if exp - now < timedelta(minutes=10) and tok.get("refresh_token"):
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": cid,
                                           "refresh_token": tok["refresh_token"]}).encode()
            req = urllib.request.Request("https://accounts.spotify.com/api/token", data=body,
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=10) as r:
                new = json.loads(r.read())
            tok.update(access_token=new["access_token"], expires_in=new.get("expires_in", 3600),
                       refresh_token=new.get("refresh_token") or tok["refresh_token"],
                       scope=new.get("scope") or tok.get("scope", ""),
                       expires_at=(now + timedelta(seconds=new.get("expires_in", 3600)))
                       .strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
            _write_private(prim, tok)
        _write_private(SP_CACHE / f"{NCSPOT_ID}_token.json", tok)
    except (OSError, ValueError, KeyError):
        pass   # sin red o token raro: spotify_player se arregla (o pide login)


def start_daemon() -> None:
    """spotify_player -d en su propia sesión (sobrevive al cierre de la TUI).
    Sin login de streaming no arranca: el daemon quedaría colgado."""
    if shutil.which(BIN) and logged_in() and not daemon_running():
        sync_tokens()
        subprocess.Popen([BIN, "-d"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


def nudge_daemon() -> None:
    """Token vencido: un pedido cualquiera a la CLI hace que el daemon lo renueve
    y reescriba el cache. Su salida (o su error) no importa."""
    if daemon_running():
        try:
            subprocess.run([BIN, "get", "key", "devices"], capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass


# ── Web API ───────────────────────────────────────────────

def api(path: str, method: str = "GET", body: Optional[dict] = None, **params) -> Any:
    """Pedido a la Web API con el token del cache de spotify_player. Devuelve el
    JSON (None si no hay contenido); SpotifyError con el código HTTP si falla."""
    if not logged_in():
        raise SpotifyError("Not logged in to Spotify (auth needed)")
    tok_file = SP_CACHE / f"{client_id() or NCSPOT_ID}_token.json"
    url = path if path.startswith("http") else API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    # PUT/POST sin cuerpo igual llevan Content-Length (si no, 411)
    data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else None)
    for attempt in range(2):
        try:
            token = json.loads(tok_file.read_text())["access_token"]
        except (OSError, ValueError, KeyError):
            raise SpotifyError("No Web API token (auth needed)") from None
        req = urllib.request.Request(url, method=method, data=data,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
            return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                nudge_daemon()   # el daemon renueva el token y lo reescribe en el cache
                continue
            if e.code == 429:
                raise SpotifyError("Spotify rate limit: try again in a moment", 429) from None
            try:
                msg = json.loads(e.read()).get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                msg = ""
            raise SpotifyError(f"Spotify API {e.code}{': ' + msg if msg else ''}", e.code) from None
        except (urllib.error.URLError, OSError, ValueError):
            raise SpotifyError("Spotify API unreachable") from None
    raise SpotifyError("Spotify API 401: token expired", 401)


def api_pages(path: str, pick=lambda x: x, limit: int = PAGE, **params):
    """Recorre una lista paginada de la Web API: rinde una lista por página."""
    n = 0
    data = api(path, limit=limit, **params)
    while data:
        page = data if "items" in data else data.get("tracks") or {}   # /albums/{id} trae tracks adentro
        items = [y for y in (pick(x) for x in page.get("items") or [] if x) if y]
        n += len(items)
        yield items
        nxt = page.get("next")
        if not nxt or n >= MAX_TRACKS:
            return
        data = api(nxt)


_ME: dict = {}


def my_id() -> str:
    if "id" not in _ME:
        _ME.update(api("/me") or {})
    return str(_ME.get("id", ""))


def context_uri(typ: str, ident: str) -> str:
    return f"spotify:user:{my_id()}:collection" if typ == "liked" else f"spotify:{typ}:{ident}"


def devices() -> list[dict]:
    return (api("/me/player/devices") or {}).get("devices") or []


def to_own_device(play: bool = False) -> str:
    """Pasa la reproducción al dispositivo del daemon (o al primero que haya).
    Hace falta cuando no hay dispositivo activo o Spotify sigue dando por activo
    un cliente cerrado (contesta 404 a todo)."""
    devs = devices()
    mine = next((d for d in devs if d.get("name") == own_device()), None) or (devs[0] if devs else None)
    if not mine:
        raise SpotifyError("No Spotify devices online" + ("" if daemon_running() else " (spotify_player is not running)"))
    api("/me/player", "PUT", {"device_ids": [mine["id"]], "play": play})
    time.sleep(0.8)   # el pase tarda en reflejarse
    return str(mine.get("name"))


# ── Datos ─────────────────────────────────────────────────

def sid(v: Any) -> str:
    """Id base62 de "spotify:track:ID", de un id pelado o de {"id": …}."""
    if isinstance(v, dict):
        v = v.get("id") or v.get("uri") or ""
    return str(v or "").rsplit(":", 1)[-1]


def mmss(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def track_of(t: dict) -> Optional[dict]:
    """Tema (o episodio) normalizado: {id, kind, name, artist, album, ms, explicit, played}.
    En un episodio, artist = el show y album = la fecha."""
    if not isinstance(t, dict) or not t.get("name"):
        return None
    if t.get("type") == "episode" or ("show" in t and "artists" not in t):
        return {"id": sid(t.get("id") or t.get("uri")), "kind": "episode", "name": t["name"],
                "artist": (t.get("show") or {}).get("name", ""), "album": t.get("release_date", ""),
                "ms": int(t.get("duration_ms") or 0), "explicit": bool(t.get("explicit")),
                "played": bool((t.get("resume_point") or {}).get("fully_played"))}
    album = t.get("album") or {}
    return {"id": sid(t.get("id") or t.get("uri")), "kind": "track", "name": t["name"],
            "artist": ", ".join(a.get("name", "") for a in t.get("artists") or []),
            "album": album.get("name", ""), "ms": int(t.get("duration_ms") or 0),
            "explicit": bool(t.get("explicit"))}


def album_row(a: dict, group: str = "") -> dict:
    return {"type": "album", "group": group, "id": sid(a), "name": a.get("name", ""),
            "artist": ", ".join(x.get("name", "") for x in a.get("artists") or []),
            "album": (a.get("release_date") or "")[:4], "ms": 0}


def playlist_of(p: dict) -> Optional[dict]:
    if not isinstance(p, dict) or "id" not in p:
        return None
    return {"id": p["id"], "name": p.get("name", ""), "owner": (p.get("owner") or {}).get("display_name", "")}


def playback_of(data: Any) -> Optional[dict]:
    """Estado normalizado de /me/player (None = ningún dispositivo activo)."""
    if not isinstance(data, dict):
        return None
    item = data.get("item") or {}
    dev = data.get("device") or {}
    album = item.get("album") or item.get("show") or {}
    images = album.get("images") or item.get("images") or []
    return {
        "track": track_of(item) if item else None, "playing": bool(data.get("is_playing")),
        "progress": int(data.get("progress_ms") or 0),
        "shuffle": bool(data.get("shuffle_state")), "repeat": str(data.get("repeat_state") or "off").lower(),
        "device": dev.get("name", ""), "volume": dev.get("volume_percent"),
        "album_id": sid(album), "cover": images[0].get("url") if images and isinstance(images[0], dict) else None,
    }


def cover_path(album_id: str, url: Optional[str]) -> Optional[Path]:
    """Carátula en ~/.cache/spotify-tui/covers (se baja una vez por álbum)."""
    if not url or not album_id:
        return None
    p = COVERS / f"{album_id}.jpg"
    if p.exists():
        return p
    try:
        COVERS.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=10) as r:
            data = r.read()
        tmp = p.with_suffix(".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return p
    except (OSError, ValueError):
        return None


# ── Config de spotify_player (app.toml) ───────────────────

# Lo que se edita desde Settings → Spotify: (sección, clave, default de spotify_player)
DEVICE_TYPES = ["computer", "speaker", "smartphone", "tablet", "tv", "avr", "stb", "audiodongle", "gameconsole"]
BITRATES = [96, 160, 320]


def config_get(key: str, section: str = "", default: Any = None) -> Any:
    data = _config()
    if section:
        data = data.get(section) if isinstance(data.get(section), dict) else {}
    return data.get(key, default)


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return json.dumps(str(v))   # string TOML básica: comillas dobles con escapes de JSON


def config_set(key: str, value: Any, section: str = "") -> None:
    """Cambia una clave de app.toml conservando comentarios y orden: reemplaza
    su línea o la agrega al final de su sección (que se crea si falta).
    Temporal + os.replace."""
    try:
        lines = SP_CONFIG.read_text().split("\n")
    except OSError:
        lines = ["# spotify_player — lo escribe Settings → Spotify (tools/spotify_api.py).",
                 "# Las claves que faltan usan los defaults de spotify_player.", ""]
    cur, start, end = "", None, None   # rango de líneas de la sección pedida
    if not section:
        start = 0
    for i, line in enumerate(lines):
        m = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
        if m:
            if cur == section and start is not None and end is None:
                end = i
            cur = m.group(1).strip()
            if cur == section:
                start = i + 1
    if start is not None and end is None:
        end = len(lines)
    new = f"{key} = {_toml_value(value)}"
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", f"[{section}]", new, ""]
    else:
        for i in range(start, end):
            if re.match(rf"^\s*{re.escape(key)}\s*=", lines[i]):
                lines[i] = new
                break
        else:
            at = end
            while at > start and not lines[at - 1].strip():   # antes de las líneas en blanco del final
                at -= 1
            lines.insert(at, new)
    SP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = SP_CONFIG.with_name(SP_CONFIG.name + ".tmp")
    tmp.write_text("\n".join(lines))
    os.replace(tmp, SP_CONFIG)


# ── Config de la TUI (spotify-tui.conf) ───────────────────

TUI_CONF = Path(os.environ.get("SPOTIFY_TUI_CONF") or
                Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dotfiles" / "spotify-tui.conf")
TUI_DEFAULTS = {"autostart": "off"}


def tui_conf() -> dict:
    conf = dict(TUI_DEFAULTS)
    try:
        for line in TUI_CONF.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip()
    except OSError:
        pass
    return conf


def tui_conf_set(key: str, value: str) -> None:
    """key=value en spotify-tui.conf, conservando los comentarios."""
    try:
        lines = TUI_CONF.read_text().splitlines()
    except OSError:
        lines = ["# spotify-tui.conf — opciones de la TUI de Spotify. Lo escribe Settings → Spotify.",
                 "# autostart: arrancar spotify_player -d al iniciar la sesión (spotify_api.py --autostart)"]
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    TUI_CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = TUI_CONF.with_name(TUI_CONF.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, TUI_CONF)


# ── Gestión (Settings → Spotify) ──────────────────────────

def stop_daemon(wait: float = 5.0) -> None:
    for pid in daemon_pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    end = time.monotonic() + wait
    while daemon_running() and time.monotonic() < end:
        time.sleep(0.2)


def restart_daemon() -> None:
    stop_daemon()
    start_daemon()


def token_status() -> dict:
    """Token de la Web API del client configurado: {exists, expires (datetime | None)}."""
    p = SP_CACHE / f"{client_id() or NCSPOT_ID}_token.json"
    try:
        return {"exists": True, "expires": token_expiry(json.loads(p.read_text()))}
    except (OSError, ValueError, KeyError):
        return {"exists": p.exists(), "expires": None}


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def clear_covers() -> None:
    shutil.rmtree(COVERS, ignore_errors=True)


def version() -> str:
    """Versión de spotify_player ("" si no está instalado)."""
    if not shutil.which(BIN):
        return ""
    try:
        out = subprocess.run([BIN, "--version"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "?"
    return out.strip().rsplit(" ", 1)[-1]


if __name__ == "__main__":
    if sys.argv[1:] == ["--autostart"]:
        if tui_conf().get("autostart") == "on":
            start_daemon()
        sys.exit(0)
    print(__doc__.strip())
    sys.exit(2)
