#!/usr/bin/env bash
# dmenu.sh — reemplazo de `rofi -dmenu` con la estética de las TUIs propias.
# Lee las opciones por stdin (una por línea), abre tools/launcher_tui.py
# en modo dmenu en una kitty centrada (clase launcher-dmenu) y escribe la
# elegida en stdout. Sale con 1 si se cerró sin elegir (como rofi).
#
# Uso: printf 'a\nb\n' | dmenu.sh [-p prompt] [--placeholder texto] [--no-custom] [--index]
#   -p             título del buscador
#   --placeholder  texto gris del buscador vacío
#   --no-custom    solo vale una opción de la lista (si no, enter devuelve lo escrito)
#   --index        devuelve el número de la opción (desde 0) en vez del texto
set -u
tmp="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/dmenu.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
cat > "$tmp/in"

args=(dmenu --input "$tmp/in" --output "$tmp/out")
title="Menu"
while [ $# -gt 0 ]; do
    case "$1" in
        -p|--prompt)   args+=(--prompt "$2"); title="$2"; shift 2 ;;
        --placeholder) args+=(--placeholder "$2"); shift 2 ;;
        --no-custom|-no-custom) args+=(--no-custom); shift ;;
        --index)       args+=(--index); shift ;;
        -i)            shift ;;                     # rofi: sin distinguir mayúsculas (acá siempre)
        *) echo "dmenu.sh: opción desconocida: $1" >&2; exit 2 ;;
    esac
done

kitty --class launcher-dmenu --title "$title" \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/launcher_tui.py" "${args[@]}" >/dev/null 2>&1
[ -s "$tmp/out" ] || exit 1
cat "$tmp/out"
