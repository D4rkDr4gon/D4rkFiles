from libqtile.config import Screen

from . import user

# El wallpaper activo lo escribe scripts/theme-switch.sh en el estado del tema
# (~/.local/state/dotfiles/current_theme.json). Se lee al cargar la config, así
# que `theme <nombre>` + reload alcanza; no hay nada que reescribir en este archivo.
wallpaper = user.theme().get("wallpaper") or None

screens = [
    Screen(wallpaper=wallpaper, wallpaper_mode="fill")
    for _ in range(user.screen_count())
]
