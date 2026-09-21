#!/usr/bin/env bash
# Historial de portapapeles (cliphist + rofi) — Mod+V en Hyprland.
#   Enter        copiar la entrada seleccionada (después pegás con Ctrl+V)
#   Supr         borrar la entrada seleccionada (y vuelve al menú)
#   Shift+Supr   vaciar todo el historial
# Las imágenes se muestran con miniatura (íconos de rofi).

CLIP="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/scripts/cliphist.sh"
THEME="$HOME/.config/rofi/theme-clipboard.rasi"
THUMBS="${XDG_RUNTIME_DIR:-/tmp}/cliphist-thumbs"   # tmpfs, igual que la base
LIST="${XDG_RUNTIME_DIR:-/tmp}/cliphist-menu.list"

umask 077
mkdir -p "$THUMBS"

# "id<TAB>preview" por línea; para imágenes agrega el ícono (miniatura).
build_list() {
    local id preview ext thumb
    local -A keep=()
    while IFS=$'\t' read -r id preview; do
        [[ -z "$id" ]] && continue
        if [[ "$preview" =~ ^\[\[\ binary\ data\ .*\ (png|jpg|jpeg|bmp|gif|webp)\  ]]; then
            ext="${BASH_REMATCH[1]}"
            thumb="$THUMBS/$id.$ext"
            [[ -f "$thumb" ]] || printf '%s\t' "$id" | "$CLIP" decode > "$thumb" 2>/dev/null
            keep["$id.$ext"]=1
            printf '%s\t%s\0icon\x1f%s\n' "$id" "$preview" "$thumb"
        else
            printf '%s\t%s\n' "$id" "$preview"
        fi
    done < <("$CLIP" list)

    # limpiar miniaturas de entradas que ya no existen
    local f
    for f in "$THUMBS"/*; do
        [[ -e "$f" && -z "${keep[${f##*/}]}" ]] && rm -f "$f"
    done
}

while true; do
    # archivo y no "$(...)": la sustitución de comandos descarta los bytes
    # nulos (\0icon\x1f...) y se perderían las miniaturas.
    build_list > "$LIST"
    if [[ ! -s "$LIST" ]]; then
        notify-send -t 1500 "Portapapeles" "El historial está vacío"
        exit 0
    fi

    choice=$(rofi -dmenu -i -p "" -no-custom \
        -display-columns 2 -show-icons \
        -kb-remove-char-forward "Control+d" -kb-delete-entry "" \
        -kb-custom-1 "Delete" -kb-custom-2 "Shift+Delete" \
        -mesg "Enter copiar   ·   Supr borrar   ·   Shift+Supr vaciar todo" \
        -theme "$THEME" < "$LIST")
    rc=$?

    case "$rc" in
        0)  # copiar
            [[ -z "$choice" ]] && break
            printf '%s' "$choice" | "$CLIP" decode | wl-copy
            command -v swayosd-client &>/dev/null \
                && swayosd-client --custom-message "Copiado" --custom-icon edit-copy-symbolic
            break
            ;;
        10) # borrar una entrada y volver al menú
            [[ -n "$choice" ]] && printf '%s' "$choice" | "$CLIP" delete
            ;;
        11) # vaciar todo
            "$CLIP" wipe
            rm -f "$THUMBS"/* "$LIST"
            notify-send -t 1500 "Portapapeles" "Historial vaciado"
            exit 0
            ;;
        *)  break ;;   # Esc
    esac
done
rm -f "$LIST"
