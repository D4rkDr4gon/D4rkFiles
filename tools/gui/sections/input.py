"""Input (GUI): paridad con InputDevView — teclado, mouse y touchpad de Hyprland (en vivo +
hypr/settings.lua) y el OSD de Caps/Num lock (swayosd-libinput-backend, servicio del sistema: va por rootd)."""

from __future__ import annotations

from . import _lib as L

SETTINGS = [
    ("input", "kb_layout", "Keyboard layout", "text", "us", "xkb layout(s), e.g. latam,us"),
    ("input", "kb_variant", "Layout variant", "text", "", "e.g. intl, deadtilde"),
    ("input", "kb_options", "Keyboard options", "text", "", "e.g. grp:alt_shift_toggle, caps:escape"),
    ("input", "repeat_rate", "Key repeat rate", "int:10:80", "25", "repeats per second"),
    ("input", "repeat_delay", "Key repeat delay", "int:150:1000", "600", "ms before repeating"),
    ("input", "sensitivity", "Pointer sensitivity", "float:-1:1", "0", "-1 slow … 1 fast"),
    ("input", "follow_mouse", "Focus follows mouse", "int:0:3", "1", "0 click to focus · 1 hover"),
    ("input:touchpad", "natural_scroll", "Natural scroll", "bool", "false", "scrolls like a phone"),
    ("input:touchpad", "tap-to-click", "Tap to click", "bool", "true", "tap the touchpad to click"),
    ("input:touchpad", "disable_while_typing", "Disable while typing", "bool", "true", "ignore touches while typing"),
    ("input:touchpad", "scroll_factor", "Touchpad scroll speed", "float:0.1:3", "1.0", "1 = default"),
    ("input:touchpad", "drag_lock", "Drag lock", "bool", "false", "lift the finger without dropping"),
]


def sid(block, key):
    return f"{block}|{key}"


def get() -> dict:
    C = L.settings_common()
    groups: dict[str, list] = {"Keyboard & mouse": [], "Touchpad": []}
    for block, key, name, kind, default, desc in SETTINGS:
        raw = C.hypr_block_get(block, key)
        cur = raw if raw not in (None, "") else default
        g = groups["Keyboard & mouse" if block == "input" else "Touchpad"]
        if kind == "bool":
            g.append(L.toggle(sid(block, key), name, desc, cur in ("true", "1", "yes")))
        elif kind.startswith(("int", "float")):
            t, lo, hi = kind.split(":")
            g.append(L.slider(sid(block, key), name, desc, float(cur or 0) if t == "float" else int(float(cur or 0)),
                              float(lo) if t == "float" else int(lo), float(hi) if t == "float" else int(hi),
                              0.05 if t == "float" else 1))
        else:
            g.append(L.field(sid(block, key), name, desc, cur))
    st = osd_state()
    osd = [L.info("lockosd", "Caps/Num lock OSD", "swayosd has no libinput backend (needs swayosd >= 0.1)")] if st == "missing" else \
        [L.toggle("lockosd", "Caps/Num lock OSD", "swayosd-libinput-backend (system service)", st == "on")]
    return L.page("Input", "Applied live and saved in hypr/settings.lua",
                  [L.group(k, v) for k, v in groups.items()] + [L.group("On-screen display", osd)])


OSD_UNIT = "swayosd-libinput-backend.service"


def osd_state() -> str:
    if L.run(["systemctl", "cat", OSD_UNIT]).returncode != 0:
        return "missing"
    return "on" if L.run(["systemctl", "is-active", OSD_UNIT]).stdout.strip() == "active" else "off"


def _apply(block: str, key: str, value: str) -> dict:
    C = L.settings_common()
    ok, msg = C.hypr_apply(block, key, value)
    if not ok:
        return L.fail(msg or "Hyprland rejected the value")
    C.hypr_block_set(block, key, value)
    return L.ok(f"{key} = {value or '(empty)'}")


def set_value(key: str, value):
    if key == "lockosd":
        if osd_state() == "missing":
            return L.fail("swayosd has no libinput backend unit")
        return L.root_ok([["systemctl", "enable" if value else "disable", "--now", OSD_UNIT]],
                         f"Caps/Num lock OSD {'on' if value else 'off'}")
    block, _, k = key.partition("|")
    row = next((s for s in SETTINGS if s[0] == block and s[1] == k), None)
    if not row:
        return L.fail("Unknown field")
    if row[3] == "bool":
        v = "true" if value else "false"
    elif row[3].startswith("int"):
        v = str(int(float(value)))
    else:
        v = f"{float(value):.2f}"
    return _apply(block, k, v)


def act(key: str, text=None):
    if key.startswith("edit:"):
        block, _, k = key[5:].partition("|")
        row = next((s for s in SETTINGS if s[0] == block and s[1] == k), None)
        if not row:
            return L.fail("Unknown field")
        if text is None:
            cur = L.settings_common().hypr_block_get(block, k)
            return L.ask(key, row[2], text=cur if cur not in (None,) else row[4])
        return _apply(block, k, text.strip())
    return L.ok()
