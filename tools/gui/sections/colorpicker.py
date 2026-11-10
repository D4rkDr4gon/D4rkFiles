"""Color picker (GUI): paridad con ColorPickerView — tomar el color de un píxel (slurp -p + grim;
la ventana se cierra antes), historial de los últimos 50 con muestra, hex/rgb/hsl; clic copia en
el formato elegido (hex, rgb o hsl, como `c` en la TUI); borrar del historial."""

from __future__ import annotations

import colorsys
import json
import subprocess
import threading
import time
from pathlib import Path

from . import _lib as L

HISTORY = L.STATE_DIR / "settings" / "colors.json"
UI: dict = {}
STATE: dict = {"fmt": "hex"}


def load() -> list[str]:
    try:
        return list(json.loads(HISTORY.read_text()))
    except (OSError, ValueError):
        return []


def save(c: list[str]) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(c[:50]))


def formats(h: str) -> dict[str, str]:
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return {"hex": h, "rgb": f"rgb({r}, {g}, {b})", "hsl": f"hsl({hh * 360:.0f}, {ss * 100:.0f}%, {ll * 100:.0f}%)"}


def get() -> dict:
    rows = []
    for h in load():
        f = formats(h)
        rows.append(L.item(f"c:{h}", h, sub=f"{f['rgb']} · {f['hsl']}", glyph="■", color=h,
                           actions=[L.action(f"del:{h}", "Delete", True)]))
    return L.page("Color picker", f"Click a color to copy it as {STATE['fmt']}", [
        L.group("Pick", [L.button("pick", "Pick from screen", "Click any pixel · copied and saved to the history", "Pick"),
                         L.choice("fmt", "Copy as", "Format that clicking a color copies", STATE["fmt"], ["hex", "rgb", "hsl"])]),
        L.group(f"History · {len(rows)}" if rows else "History", rows or [L.info("none", "No colors yet", "")])], refresh=0)


def copy(h: str) -> str:
    v = formats(h)[STATE["fmt"]]
    subprocess.run(["wl-copy"], input=v.encode())
    return v


def pick_bg() -> None:
    time.sleep(0.5)
    h = pick_hex()
    if not h:
        subprocess.run(["notify-send", "Color picker", "Pick cancelled", "-t", "2000"])
        return
    save([h] + [c for c in load() if c != h])
    subprocess.run(["notify-send", "Color picker", f"{copy(h)} copied", "-t", "2500"])


def set_value(key, value):
    if key == "fmt" and value in ("hex", "rgb", "hsl"):
        STATE["fmt"] = value
        return L.ok()
    return L.fail("Unknown setting")


def act(key: str, text=None):
    op, _, h = key.partition(":")
    if op == "pick":
        threading.Thread(target=pick_bg, daemon=True).start()
        return {"ok": True, "msg": "", "close": True}
    if op == "c":
        return L.ok(f"{copy(h)} copied")
    if op == "del":
        save([c for c in load() if c != h])
        return L.ok()
    return L.ok()


def pick_hex():
    geom = L.run(["slurp", "-p"], timeout=60).stdout.strip()
    if not geom:
        return None
    ppm = subprocess.run(["grim", "-g", geom, "-t", "ppm", "-"], capture_output=True, timeout=10).stdout
    parts = ppm.split(b"\n", 3)
    if len(parts) < 4 or len(parts[3]) < 3:
        return None
    r, g, b = parts[3][:3]
    return f"#{r:02x}{g:02x}{b:02x}"


def pick_cli() -> None:
    h = pick_hex()
    if not h:
        return
    save([h] + [c for c in load() if c != h])
    subprocess.run(["wl-copy", h])
    subprocess.run(["notify-send", "Color picker", f"{h} copied", "-t", "2500"])
