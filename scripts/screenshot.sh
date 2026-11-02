#!/usr/bin/env bash
# Captura de una región con slurp -> guarda en ~/Pictures/Screenshots y la copia
# al portapapeles.

dir="$(xdg-user-dir PICTURES 2>/dev/null || echo "$HOME/Pictures")/Screenshots"
mkdir -p "$dir"
region="$(slurp)" || exit 0          # Esc: cancelar sin error ni portapapeles vacío
file="$dir/screenshot-$(date +%Y%m%d-%H%M%S).png"
grim -g "$region" "$file" || exit 1
wl-copy < "$file"
notify-send "Screenshot" "Guardado en $file y copiado al portapapeles" -t 3000
