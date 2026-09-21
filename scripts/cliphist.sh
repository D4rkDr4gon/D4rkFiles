#!/usr/bin/env bash
# Wrapper único de cliphist: el store (wl-paste --watch, en hyprland.conf) y el
# menú (rofi/scripts/clipboard-menu.sh) tienen que usar la MISMA base.
#
# La base vive en $XDG_RUNTIME_DIR (tmpfs, 0700): el historial nunca toca el
# disco y se borra al reiniciar/cerrar sesión. Es a propósito — se copian
# tokens, hashes y credenciales. Para historial persistente, cambiar db a
# "$HOME/.cache/cliphist/db".
#
# cliphist ya descarta solo lo que la app marca como sensible
# (CLIPBOARD_STATE=sensitive que exporta wl-paste, ej. KeePassXC).
exec cliphist \
    -db-path "${XDG_RUNTIME_DIR:-/tmp}/cliphist.db" \
    -max-items 300 \
    -preview-width 120 \
    "$@"
