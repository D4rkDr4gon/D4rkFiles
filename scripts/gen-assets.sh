#!/usr/bin/env bash
# gen-assets.sh — genera los wallpapers y las previews de cada tema desde su theme.json.
# (El logo de waybar, config/waybar/logo.png, es el logo oficial del proyecto y no se genera.)
#
# Son imágenes originales (degradado + resplandor con la paleta del tema): no
# hay material con copyright ni licencias que revisar. Salida:
#   assets/wallpapers/<tema>.jpg      1920x1080
#   themes/<tema>/preview.png         800x400 (paleta; la usa Settings → THEMES)
#
# Uso: scripts/gen-assets.sh [tema ...]     (sin argumentos: todos)
# Requiere: imagemagick, jq.
# shellcheck disable=SC2178,SC2128  # TOK es un array asociativo declarado en lib/theme.sh
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT="$(cd -P "$(dirname "$SELF")/.." && pwd)"
# shellcheck source=lib/theme.sh
DOTFILES_DIR="$ROOT"; export DOTFILES_DIR
source "$ROOT/scripts/lib/env.sh"
source "$ROOT/scripts/lib/theme.sh"

command -v magick >/dev/null 2>&1 || { echo "Falta imagemagick (magick)" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "Falta jq" >&2; exit 1; }

mkdir -p "$ROOT/assets/wallpapers"

gen_wallpaper() {
    local id="$1" out="$ROOT/assets/wallpapers/$1.jpg"
    local wbg="${TOK[background]}" wpri="${TOK[primary]}" wsec="${TOK[secondary]}"
    local low glow soft
    low="$(hex_blend "$wpri" "$wbg" 9)"    # borde inferior: fondo con un toque del primario
    glow="$(hex_blend "$wpri" "#000000" 24)"
    soft="$(hex_blend "$wsec" "#000000" 14)"

    # 1) degradado vertical  2) resplandor principal (arriba a la derecha)
    # 3) resplandor secundario (abajo a la izquierda)  4) viñeta  5) grano fino
    magick -size 1920x1080 "gradient:$wbg-$low" \
        \( -size 1920x1080 radial-gradient:"$glow"-black -roll +560-260 \) -compose screen -composite \
        \( -size 1920x1080 radial-gradient:"$soft"-black -roll -640+340 \) -compose screen -composite \
        \( -size 1920x1080 radial-gradient:white-gray45 \) -compose multiply -composite \
        -attenuate 0.06 +noise Gaussian -colorspace sRGB -quality 88 "$out"
}

gen_preview() {
    local id="$1" out="$ROOT/themes/$1/preview.png"
    local bg="${TOK[background]}" fg="${TOK[foreground]}"
    local -a chips=("${TOK[primary]}" "${TOK[secondary]}" "${TOK[chip_battery]}" "${TOK[chip_bluetooth]}"
                    "${TOK[chip_wlan]}" "${TOK[chip_audio]}")
    local -a states=("${TOK[status_ok]}" "${TOK[status_warn]}" "${TOK[status_error]}")
    local -a cmd=(magick -size 800x400 "xc:$bg")
    local i x

    # Barra superior con el color primario y una "ventana" con el fondo del tema.
    cmd+=(-fill "${TOK[chip_battery]}" -draw "roundrectangle 24,24 776,60 10,10")
    cmd+=(-fill "${TOK[primary]}" -draw "roundrectangle 34,34 154,50 6,6")
    for i in "${!chips[@]}"; do
        x=$((40 + i * 120))
        cmd+=(-fill "${chips[$i]}" -draw "roundrectangle $x,100 $((x + 100)),180 12,12")
    done
    for i in "${!states[@]}"; do
        x=$((40 + i * 120))
        cmd+=(-fill "${states[$i]}" -draw "roundrectangle $x,210 $((x + 100)),250 10,10")
    done
    # "Texto": líneas del color de primer plano con distinta opacidad.
    for i in 0 1 2 3; do
        cmd+=(-fill "$(hex_blend "$fg" "$bg" $((100 - i * 22)))" -draw "roundrectangle 40,$((290 + i * 24)) $((600 - i * 90)),$((302 + i * 24)) 5,5")
    done
    "${cmd[@]}" "$out"
}

main() {
    local -a ids=("$@")
    local id json
    if ((${#ids[@]} == 0)); then
        for json in "$ROOT"/themes/*/theme.json; do ids+=("$(basename "$(dirname "$json")")"); done
    fi
    for id in "${ids[@]}"; do
        json="$ROOT/themes/$id/theme.json"
        [[ -f "$json" ]] || { echo "Tema inexistente: $id" >&2; continue; }
        theme_load_tokens "$json"
        gen_wallpaper "$id"
        gen_preview "$id"
        echo "  → $id"
    done
}

main "$@"
