"""Theme editor (GUI): paridad con ThemeEditorView — borrador basado en un tema (por defecto el
activo; "Base theme" elige otro), editar nombre/ícono/wallpaper y los 11 colores (validación
#rrggbb, muestra de cada uno), armar el borrador desde un wallpaper (wallpalette.py, conserva la
forma del tema base), guardarlo como tema NUEVO (themes/<nombre>/ + preview.png si viene de un
wallpaper) o sobrescribir el base (con confirmación). Guardar aplica el tema con theme-switch.sh:
la GUI toma los colores sola (Theme.qml se regenera y Quickshell recarga)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import _lib as L

UI: dict = {}
STATE: dict = {"base": None, "draft": None, "dirty": False, "wall": None, "pick": ""}


def T():
    return L.tui_module("themeeditor")


def C():
    T()
    import common
    return common


def load_base(d: Path | None) -> None:
    c = C()
    if not d:
        d = c.active_theme_dir() or next(p for p in sorted(c.THEMES_DIR.iterdir()) if (p / "theme.json").is_file())
    STATE.update(base=d, draft=json.loads((d / "theme.json").read_text()), dirty=False, wall=None)


def pick_groups() -> list:
    t, c = T(), C()
    back = L.button("back", "Back to the draft", "", "Back")
    if STATE["pick"] == "base":
        rows = []
        for d in sorted(c.THEMES_DIR.iterdir()):
            f = d / "theme.json"
            if d.name.startswith("_") or not f.is_file():
                continue
            th = json.loads(f.read_text())
            pv = d / "preview.png"
            rows.append(L.item(f"base:{d.name}", f"{th.get('icon', '')}  {th.get('name', d.name)}", sub=d.name,
                               image=str(pv) if pv.is_file() else "", color=th.get("primary", ""), glyph="■",
                               on=d == STATE["base"]))
        return [L.group("Base theme", [back]), L.group("Themes", rows)]
    cur = c.current_theme().get("wallpaper", "")
    files = sorted({p for d in c.wallpaper_dirs() if d.is_dir() for p in d.iterdir() if p.suffix.lower() in t.IMAGE_EXT},
                   key=lambda p: p.name.lower())
    rows = [L.button("wallother", "Other image…", "Any file", "Choose")]
    if cur and Path(cur).is_file():
        rows.append(L.item(f"wall:{cur}", Path(cur).name, sub="current wallpaper", image=cur, on=True))
    rows += [L.item(f"wall:{p}", p.name, image=str(p)) for p in files if str(p) != cur]
    return [L.group("Theme from a wallpaper", [back]), L.group("Images", rows)]


def get() -> dict:
    t = T()
    if STATE["draft"] is None:
        load_base(None)
    if STATE["pick"]:
        return L.page("Theme editor", "Pick one", pick_groups())
    d = STATE["draft"]
    hexre = t.HEX
    origin = f"wallpaper {Path(STATE['wall']).name} + shape of {STATE['base'].name}" if STATE["wall"] else STATE["base"].name
    preview = [L.item("pv:sw", f"{d.get('icon', '')}  {d.get('name', '')}", sub="primary · secondary · surfaces · states",
                      color=d.get("primary", ""), glyph="■")]
    meta = [L.item(f"f:{k}", label, sub=str(d.get(k, "")).replace(str(Path.home()), "~") or "—", glyph="",
                   image=d.get("wallpaper", "") if k == "wallpaper" and Path(str(d.get("wallpaper", ""))).is_file() else "",
                   actions=[L.action(f"f:{k}", "Edit")]) for k, label in (("name", "Name"), ("icon", "Icon"), ("wallpaper", "Wallpaper"))]
    colors = [L.item(f"f:{k}", k, sub=desc, right=d.get(k, ""), glyph="■", color=d.get(k, "") if hexre.match(d.get(k, "") or "") else "",
                     actions=[L.action(f"f:{k}", "Edit")]) for k, desc in t.COLOR_KEYS]
    acts = [L.button("pick:base", "Base theme", f"Start from another theme (now {STATE['base'].name})", "Choose"),
            L.button("pick:wall", "From a wallpaper", "Background, surface ramp, accents and states from an image", "Choose"),
            L.button("save_new", "Save as new", "Creates themes/<name>/ and applies it", "Save new"),
            L.button("save", "Save", f"Overwrite themes/{STATE['base'].name}/theme.json and apply it", "Save", danger=True)]
    return L.page("Theme editor", f"Draft based on {origin}" + (" · unsaved changes" if STATE["dirty"] else ""), [
        L.group("Preview", preview), L.group("Draft", acts), L.group("Identity", meta), L.group("Colors", colors)])


def set_value(key, value):
    return L.fail("Unknown setting")


def apply(name: str) -> dict:
    L.detach(["bash", str(C().THEME_SWITCH), name])
    return L.ok(f"Applying {name}…")


def use_wall(path: str) -> dict:
    t = T()
    try:
        colors = t.theme_from(path)
    except (OSError, ValueError) as e:
        return L.fail(f"Could not read the image: {e}")
    name = re.sub(r"[-_]+", " ", Path(path).stem).strip().upper()
    STATE["draft"] = dict(STATE["draft"], **colors, name=name, icon="󰸉", wallpaper=path)
    STATE.update(wall=path, dirty=True, pick="")
    return L.ok("Palette taken from the wallpaper: Save as new keeps it")


def act(key: str, text=None):
    t, c = T(), C()
    if STATE["draft"] is None:
        load_base(None)
    op, _, arg = key.partition(":")
    d = STATE["draft"]
    if op == "back":
        STATE["pick"] = ""
        return L.ok()
    if op == "pick":
        STATE["pick"] = arg
        return L.ok()
    if op == "base":
        load_base(c.THEMES_DIR / arg)
        STATE["pick"] = ""
        return L.ok(f"Draft based on {arg}")
    if op == "wall":
        return use_wall(arg)
    if op == "wallother":
        fields = lambda v: [{"name": "path", "label": "IMAGE", "text": v}]  # noqa: E731
        if text is None:
            return L.form("wallother", "Theme from an image", fields(str(Path.home()) + "/"))
        p = Path(L.parse_form(text).get("path", "").strip()).expanduser()
        if not p.is_file():
            return L.form("wallother", "Theme from an image", fields(str(p)), error="File not found")
        return use_wall(str(p))
    if op == "f":
        is_color = arg in dict(t.COLOR_KEYS)
        label = dict(t.COLOR_KEYS).get(arg, arg).upper()
        hint = "Color picker (Tools) copies hex colors you can paste here." if is_color else ""
        if text is None:
            return L.form(key, f"Edit {arg}", [{"name": "value", "label": label, "text": str(d.get(arg, ""))}], hint=hint)
        v = L.parse_form(text).get("value", "").strip()
        err = ""
        if is_color and not t.HEX.match(v):
            err = "Use a #rrggbb color"
        elif arg == "wallpaper" and not Path(v).expanduser().is_file():
            err = "File not found"
        elif not v and arg != "icon":
            err = "Can't be empty"
        if err:
            return L.form(key, f"Edit {arg}", [{"name": "value", "label": label, "text": v}], hint=hint, error=err)
        d[arg] = str(Path(v).expanduser()) if arg == "wallpaper" else (v.lower() if is_color else v)
        STATE["dirty"] = True
        return L.ok()
    if op == "save_new":
        fields = lambda v: [{"name": "name", "label": "THEME NAME", "text": v}]  # noqa: E731
        if text is None:
            return L.form("save_new", "Save as a new theme", fields(d.get("name", "").title() if STATE["wall"] else ""),
                          hint="Created in themes/<name>/ and applied. E.g. Deep Ocean")
        name = L.parse_form(text).get("name", "").strip()
        s = t.slug(name)
        err = "The name is missing" if not s else (f"themes/{s} already exists" if (c.THEMES_DIR / s).exists() else "")
        if err:
            return L.form("save_new", "Save as a new theme", fields(name), error=err)
        nd = c.THEMES_DIR / s
        nd.mkdir(parents=True)
        draft = dict(d, name=name.upper())
        (nd / "theme.json").write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n")
        if STATE["wall"]:
            try:
                t.write_preview(STATE["wall"], draft, nd / "preview.png")
            except (OSError, ValueError):
                pass
        STATE.update(base=nd, draft=draft, dirty=False, wall=None)
        return apply(s)
    if op == "save":
        if not L.yes(text):
            return L.confirm("save", "Save theme", f"Overwrite themes/{STATE['base'].name}/theme.json and apply it?", ok_label="Save")
        (STATE["base"] / "theme.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        STATE["dirty"] = False
        return apply(STATE["base"].name)
    return L.ok()
