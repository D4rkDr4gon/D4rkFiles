#!/usr/bin/env bash
# Captura de pantalla. Wayland: región con slurp -> guarda en ~/Pictures/Screenshots
# y copia al portapapeles. X11: flameshot.

if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    dir="$(xdg-user-dir PICTURES 2>/dev/null || echo "$HOME/Pictures")/Screenshots"
    mkdir -p "$dir"
    region="$(slurp)" || exit 0          # Esc: cancelar sin error ni portapapeles vacío
    file="$dir/screenshot-$(date +%Y%m%d-%H%M%S).png"
    grim -g "$region" "$file" || exit 1
    wl-copy < "$file"
    notify-send "Screenshot" "Guardado en $file y copiado al portapapeles" -t 3000
else
    flameshot gui
fi
