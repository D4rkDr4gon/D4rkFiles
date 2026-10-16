#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# theme-preview.sh — vista previa en vivo de un tema, sin escribir nada a disco.
# Cambia solo lo liviano y reversible: el borde de las ventanas de Hyprland
# (hyprctl keyword) y los colores de las kitty abiertas (kitty @ set-colors).
# El resto (waybar, rofi, GTK…) recién cambia al aplicar con theme-switch.sh.
#
# Uso: theme-preview.sh <tema>   previsualiza themes/<tema>/theme.json
#      theme-preview.sh --revert vuelve al tema aplicado (hyprctl reload + colors.conf)
# ──────────────────────────────────────────────────────────
set -uo pipefail

# shellcheck source=lib/env.sh
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"
ROOT="$DOTFILES_DIR"
KITTY_COLORS="$DOTFILES_CONFIG/kitty/colors.conf"

hypr() { [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && hyprctl "$@" &>/dev/null; }

revert() {
    hypr reload
    [[ -f "$KITTY_COLORS" ]] && kitty @ set-colors --all -c "$KITTY_COLORS" &>/dev/null
    return 0
}

if [[ "${1:-}" == "--revert" ]]; then
    revert
    exit 0
fi

theme="${1:-}"
tj="$DOTFILES_CONF_DIR/themes/$theme/theme.json"   # temas propios primero
[[ -f "$tj" ]] || tj="$ROOT/themes/$theme/theme.json"
[[ -n "$theme" && -f "$tj" ]] || { echo "Uso: $(basename "$0") <tema> | --revert" >&2; exit 2; }

f() { jq -r --arg k "$1" --arg d "${2:-}" 'if .[$k] == null then $d else .[$k] end' "$tj"; }
primary=$(f primary); secondary=$(f secondary); bg=$(f background); fg=$(f foreground)
inactive=$(f chip_battery); style=$(f border_style solid); angle=$(f border_angle 45)

active="rgb(${primary#\#})"
if [[ "$style" == gradient || "$style" == rotating ]]; then
    active="rgba(${primary#\#}ff) rgba(${secondary#\#}ff) ${angle}deg"
fi
hypr keyword general:col.active_border "$active"
hypr keyword general:col.inactive_border "rgb(${inactive#\#})"

kitty @ set-colors --all background="$bg" foreground="$fg" cursor="$primary" \
    selection_background="$primary" selection_foreground="$bg" url_color="$primary" \
    active_border_color="$primary" &>/dev/null
exit 0
