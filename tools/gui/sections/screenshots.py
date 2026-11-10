"""Screenshots (GUI): paridad con ScreenshotsView — capturar región, ventana (slurp con los
rectángulos de las ventanas visibles) o la pantalla con foco; grabar una región con wf-recorder
(y pararla); galería de ~/Pictures/Screenshots con vista previa: clic copia, abrir, borrar con
confirmación. La ventana se cierra antes de capturar para no salir en la imagen; cada captura se
guarda y se copia al portapapeles."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import _lib as L

UI: dict = {}
SHOTS = Path.home() / "Pictures" / "Screenshots"
VIDEOS = Path.home() / "Videos" / "Recordings"
CLOSE = {"ok": True, "msg": "", "close": True}


def T():
    return L.tui_module("screenshots")


def human(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.0f} TB"


def recording() -> bool:
    return L.run(["pgrep", "-x", "wf-recorder"]).returncode == 0


def notify(msg: str) -> None:
    L.detach(["notify-send", "-a", "Screenshots", "-t", "2500", "Screenshots", msg])


def capture(mode: str) -> None:
    time.sleep(0.6)  # que la ventana termine de cerrarse
    SHOTS.mkdir(parents=True, exist_ok=True)
    out = SHOTS / time.strftime("screenshot_%Y-%m-%d_%H-%M-%S.png")
    if mode == "screen":
        try:
            mon = next((m["name"] for m in json.loads(L.run(["hyprctl", "monitors", "-j"]).stdout or "[]") if m.get("focused")), None)
        except ValueError:
            mon = None
        r = L.run(["grim", *(["-o", mon] if mon else []), str(out)])
    else:
        sel = subprocess.run(["slurp"] if mode == "region" else ["slurp", "-r"], capture_output=True, text=True, timeout=60,
                             input=None if mode == "region" else T().window_boxes())
        geom = sel.stdout.strip()
        r = L.run(["grim", "-g", geom, str(out)]) if geom else sel
    if r.returncode == 0 and out.exists():
        subprocess.run(["wl-copy", "--type", "image/png"], input=out.read_bytes())
        notify(f"Saved and copied: {out.name}")
    else:
        notify("Capture cancelled")


def start_record() -> None:
    time.sleep(0.6)
    VIDEOS.mkdir(parents=True, exist_ok=True)
    geom = subprocess.run(["slurp"], capture_output=True, text=True, timeout=60).stdout.strip()
    if not geom:
        return notify("Recording cancelled")
    out = VIDEOS / time.strftime("recording_%Y-%m-%d_%H-%M-%S.mp4")
    L.detach(["wf-recorder", "-g", geom, "-f", str(out)])
    notify("Recording… open Settings → Screenshots and stop it there")


def get() -> dict:
    cap = [L.button("region", "󰩭  Region", "Select an area with the mouse", "Capture"),
           L.button("window", "  Window", "Click on a window", "Capture"),
           L.button("screen", "󰍹  Screen", "The monitor under the cursor", "Capture")]
    if shutil.which("wf-recorder"):
        rec = recording()
        cap.append(L.button("record", "󰑋  Stop recording" if rec else "󰑋  Record region",
                            "Recording…" if rec else f"Saved to {str(VIDEOS).replace(str(Path.home()), '~')}",
                            "Stop" if rec else "Record", danger=rec))
    else:
        cap.append(L.info("norecord", "󰑋  Record screen", "install wf-recorder to enable (sudo pacman -S wf-recorder)"))
    files = sorted(SHOTS.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True) if SHOTS.is_dir() else []
    rows = [L.item(f"c:{p.name}", p.stem, sub=f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))} · "
                   f"{human(p.stat().st_size)} · click to copy", image=str(p),
                   actions=[L.action(f"open:{p.name}", "Open"), L.action(f"del:{p.name}", "Delete", True)]) for p in files]
    return L.page("Screenshots", "Saved to ~/Pictures/Screenshots and copied to the clipboard", [
        L.group("Capture", cap),
        L.group(f"Gallery · {len(files)}" if files else "Gallery", rows or [L.info("none", "No screenshots yet", "")])],
        refresh=3 if shutil.which("wf-recorder") and recording() else 10)


def set_value(key, value):
    return L.fail("Unknown setting")


def act(key: str, text=None):
    op, _, name = key.partition(":")
    if op in ("region", "window", "screen"):
        threading.Thread(target=capture, args=(op,), daemon=True).start()
        return CLOSE
    if op == "record":
        if recording():
            L.run(["pkill", "-INT", "-x", "wf-recorder"])
            return L.ok(f"Recording saved in {VIDEOS}")
        threading.Thread(target=start_record, daemon=True).start()
        return CLOSE
    p = SHOTS / name
    if p.parent != SHOTS or not p.is_file():
        return L.fail("That file is gone")
    if op == "c":
        subprocess.run(["wl-copy", "--type", "image/png"], input=p.read_bytes())
        return L.ok("Image copied to the clipboard")
    if op == "open":
        L.detach(["xdg-open", str(p)])
        return L.ok()
    if op == "del":
        if not L.yes(text):
            return L.confirm(key, "Delete screenshot", f"Delete {p.name}?", ok_label="Delete")
        p.unlink(missing_ok=True)
        return L.ok("Deleted")
    return L.ok()
