"""Audio: salidas y entradas de PipeWire (wpctl), volumen y silencio."""

from __future__ import annotations

import json
import re

from . import _lib as L


def nodes() -> list[dict]:
    try:
        dump = json.loads(L.run(["pw-dump"], timeout=5).stdout)
    except ValueError:
        return []
    out = []
    for n in dump:
        props = (n.get("info") or {}).get("props") or {}
        cls = props.get("media.class")
        if n.get("type") == "PipeWire:Interface:Node" and cls in ("Audio/Sink", "Audio/Source"):
            out.append({"id": n["id"], "kind": "sink" if cls == "Audio/Sink" else "source",
                        "desc": props.get("node.description") or props.get("node.name", "?")})
    return out


def default_id(kind: str):
    m = re.match(r"id (\d+),", L.run(["wpctl", "inspect", f"@DEFAULT_AUDIO_{kind.upper()}@"]).stdout)
    return int(m.group(1)) if m else None


def volume(target) -> tuple[float, bool]:
    r = L.run(["wpctl", "get-volume", str(target)]).stdout
    m = re.search(r"Volume: ([\d.]+)", r)
    return (float(m.group(1)) if m else 0.0), "MUTED" in r


def get() -> dict:
    ns = nodes()
    groups = []
    for kind, title, glyph in (("sink", "Outputs", "󰓃"), ("source", "Inputs", "󰍬")):
        dflt, rows = default_id(kind), []
        for n in (n for n in ns if n["kind"] == kind):
            vol, muted = volume(n["id"])
            on = n["id"] == dflt
            rows.append(L.item(f"default:{n['id']}", n["desc"], sub="default device" if on else "click to make default",
                               right="muted" if muted else f"{round(vol * 100)}%", glyph=glyph, on=on,
                               actions=[L.action(f"mute:{n['id']}", "Unmute" if muted else "Mute")]))
            rows.append(L.slider(f"vol:{n['id']}", "Volume", "", round(vol * 100), 0, 150, 1))
        groups.append(L.group(title, rows))
    return L.page("Audio", "Click a device to make it the default", groups, refresh=3)


def set_value(key: str, value):
    if key.startswith("vol:"):
        L.run(["wpctl", "set-volume", "-l", "1.5", key.split(":", 1)[1], f"{float(value) / 100:.2f}"])
        return L.ok()
    return L.fail("Unknown field")


def act(key: str, text=None):
    op, _, arg = key.partition(":")
    if op == "default":
        L.run(["wpctl", "set-default", arg])
        return L.ok("Default device changed")
    if op == "mute":
        L.run(["wpctl", "set-mute", arg, "toggle"])
        return L.ok()
    return L.fail("Unknown action")
