"""Backgrounds (GUI): paridad con BackgroundsView — wallpapers de common.wallpaper_dirs()
(EXTRA_WALLPAPER_DIRS de user.conf, ~/.local/share/backgrounds y assets/wallpapers); aplica con
scripts/wallpaper-set.sh sin cambiar de tema."""

from __future__ import annotations

from . import _lib as L

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def walls() -> dict[str, "L.Path"]:
    """Nombre → ruta, sin repetir nombres (el primero en el orden de wallpaper_dirs gana)."""
    out: dict = {}
    for d in L.settings_common().wallpaper_dirs():
        for p in sorted(d.iterdir()) if d.is_dir() else []:
            if p.suffix.lower() in EXTS and p.name not in out:
                out[p.name] = p
    return out


def get() -> dict:
    C = L.settings_common()
    cur = C.resolve_wallpaper(C.current_theme().get("wallpaper", "") or "")
    active = str(cur.resolve()) if cur else ""
    rows = []
    for name, p in walls().items():
        on = str(p.resolve()) == active
        rows.append(L.item(f"apply:{name}", p.stem, sub="active" if on else "click to apply", image=str(p), on=on))
    return L.page("Backgrounds", "Click a wallpaper to apply it (the theme stays the same)",
                  [L.group("Wallpapers", rows or [L.info("none", "No wallpapers found", "assets/wallpapers or ~/.local/share/backgrounds")])])


def set_value(key: str, value):
    return L.fail("Unknown field")


def act(key: str, text=None):
    op, _, name = key.partition(":")
    path = walls().get(name)
    if op != "apply" or path is None:
        return L.fail("Unknown wallpaper")
    # wallpaper-set.sh no es ejecutable en todos los clones: siempre por bash
    L.detach(["bash", str(L.DOTFILES / "scripts" / "wallpaper-set.sh"), str(path)])
    return L.ok("Applying wallpaper…")
