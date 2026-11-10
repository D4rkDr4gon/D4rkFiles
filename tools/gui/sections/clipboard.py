"""Clipboard (GUI): paridad con ClipboardView — historial de cliphist con los fijados arriba
(clipboard_tui: se guardan en disco y sobreviven al cierre de sesión), búsqueda, miniaturas de las
imágenes, ver el texto completo, copiar (en la ventana suelta de Mod+V cierra y avisa con el OSD,
como la TUI), fijar/desfijar (solo texto, hasta MAX_PIN), borrar (sobre un fijado lo desfija) y
vaciar el historial con confirmación (los fijados quedan)."""

from __future__ import annotations

import shutil
import subprocess
import sys

from . import _lib as L

UI: dict = {}
STATE: dict = {"items": {}}


def C():
    p = str(L.TOOLS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import clipboard_tui
    return clipboard_tui


def get() -> dict:
    c = C()
    items = c.entries()
    q = (UI.get("search") or "").strip().lower()
    shown = [e for e in items if not q or q in e["preview"].lower() or q in e.get("text", "").lower()]
    STATE["items"] = {e["id"]: e for e in items}
    pinned, rows = [], []
    for e in shown[:200]:
        prev = " ".join(e["preview"].split())
        if e.get("pinned"):
            pinned.append(L.item(f"c:{e['id']}", prev[:140], sub="pinned · click to copy", glyph="󰐃", on=True,
                                 actions=[L.action(f"view:{e['id']}", "View"), L.action(f"pin:{e['id']}", "Unpin")]))
            continue
        img = ""
        if e["image"]:
            try:
                img = str(c.thumb(e) or "")
            except OSError:
                img = ""
        acts = ([] if e["image"] else [L.action(f"view:{e['id']}", "View"), L.action(f"pin:{e['id']}", "Pin")]) + \
            [L.action(f"del:{e['id']}", "Delete", True)]
        rows.append(L.item(f"c:{e['id']}", "Image" if e["image"] else prev[:140], sub=prev[:80] if e["image"] else "",
                           glyph="󰋩" if e["image"] else "󰈙", image=img, actions=acts))
    c.prune_thumbs(items)
    n_pin = sum(1 for e in items if e.get("pinned"))
    sub = (f"{len(shown)} of {len(items)}" if q else
           f"{n_pin} pinned · {len(items) - n_pin} in memory, cleared at logout" if items else "Empty — copy something first")
    groups = []
    if pinned:
        groups.append(L.group("Pinned", pinned))
    groups.append(L.group("History", rows or [L.info("none", "Nothing here", "")]))
    groups.append(L.group("Actions", [L.button("wipe", "Clear history", "Pinned items are kept", "Clear", danger=True)]))
    p = L.page("Clipboard", sub, groups, refresh=4)
    p["search"] = "Type to search…"
    return p


def set_value(key, value):
    return L.fail("Unknown setting")


def act(key: str, text=None):
    c = C()
    op, _, i = key.partition(":")
    if op == "wipe":
        if not L.yes(text):
            return L.confirm("wipe", "Clear clipboard history", "Delete the whole clipboard history? (pinned items are kept)",
                             ok_label="Clear")
        c.clip("wipe")
        c.prune_thumbs([])
        return L.ok("Clipboard history cleared")
    e = STATE["items"].get(i) or next((x for x in c.entries() if x["id"] == i), None)
    if not e:
        return L.fail("That entry is gone")
    if op == "c":
        subprocess.run(["wl-copy"], input=c.data_of(e))
        if UI.get("standalone"):
            if shutil.which("swayosd-client"):
                L.detach(["swayosd-client", "--custom-message", "Copied", "--custom-icon", "edit-copy-symbolic"])
            return {"ok": True, "msg": "", "close": True}
        return L.ok("Copied to the clipboard")
    if op == "view":
        full = c.data_of(e).decode(errors="replace")
        return L.text_view("Pinned" if e.get("pinned") else "Clipboard entry", full[:20000] + ("\n…" if len(full) > 20000 else ""))
    if op == "pin" or (op == "del" and e.get("pinned")):
        if e["image"]:
            return L.fail("Images can't be pinned")
        pins = c.load_pins()
        if e.get("pinned"):
            pins.remove(e["text"])
            msg = "Unpinned"
        else:
            t = c.data_of(e).decode(errors="replace")
            if len(t) > c.MAX_PIN:
                return L.fail(f"Too long to pin (over {c.MAX_PIN} characters)")
            pins = [t] + [x for x in pins if x != t]
            msg = "Pinned (kept across restarts, saved on disk)"
        c.save_pins(pins)
        return L.ok(msg)
    if op == "del":
        c.clip("delete", data=e["line"].encode())
        return L.ok("Deleted")
    return L.ok()
