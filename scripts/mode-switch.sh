#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# mode-switch.sh — Modos de escritorio (ej: TRABAJO, ESTUDIO, JUGAR)
# Lee ~/.config/dotfiles/modes.conf y ubica cada app en su workspace:
# si ya está abierta la mueve, si no la abre ahí en silencio. No cierra
# nada. Sin argumentos muestra un menú rofi con los modos y la entrada
# para gestionarlos (scripts/mode-manager.sh). Requiere Hyprland y jq.
#
# El modo activo vive en $XDG_RUNTIME_DIR (se borra al reiniciar): al arrancar no hay
# ninguno. `--none` (o "Sin modo" en el menú) lo desactiva sin tocar las ventanas.
#
# Uso: mode-switch.sh [modo | --none]
# ──────────────────────────────────────────────────────────
set -uo pipefail

# shellcheck source=/dev/null
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"
CONF="$DOTFILES_CONF_DIR/modes.conf"
STATE="${XDG_RUNTIME_DIR:-/tmp}/desktop-mode"
NONE="󰜺  Sin modo"
MANAGER_LAUNCH="$HOME/.config/waybar/scripts/modes-launch.sh"
ROFI_THEME="$HOME/.config/rofi/theme.rasi"
MANAGE="󰒓  Gestionar modos..."
WAIT_SECS=30   # cuánto esperar a que aparezca una app recién lanzada

[[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || { echo "Requiere Hyprland" >&2; exit 1; }

# Formato: modo|ícono|workspace|match|comando|nombre (ver modes.conf.example)
entries() { [[ -r "$CONF" ]] && grep -vE '^\s*(#|$)' "$CONF"; }

# Dirección de la primera ventana que matchea "class:<re>" o "title:<re>"
find_window() {
    local field="${1%%:*}" re="${1#*:}"
    hyprctl clients -j | jq -r --arg f "$field" --arg re "$re" \
        'first(.[] | select(.[$f] | test($re))) | .address // empty'
}

choose_mode() {
    local current menu none
    current="$(cat "$STATE" 2>/dev/null)"
    menu="$(entries | awk -F'|' -v cur="$current" '
        !($1 in icon) { order[++n] = $1; icon[$1] = "" }
        $2 != "" && icon[$1] == "" { icon[$1] = $2 }
        END { for (i = 1; i <= n; i++) { m = order[i]
            printf "%s  %s%s\n", (icon[m] == "" ? "󰕮" : icon[m]), m, (m == cur ? "  (activo)" : "") } }')"
    none="$NONE"
    [[ -z "$current" ]] && none+="  (activo)"
    menu="$none${menu:+$'\n'$menu}"$'\n'"$MANAGE"
    printf '%s\n' "$menu" \
        | rofi -dmenu -i -p "Modo" -theme "$ROFI_THEME" \
            -theme-str "listview { lines: $(wc -l <<<"$menu"); }" \
            -theme-str 'entry { placeholder: "Elegí un modo..."; }'
}

clear_mode() {
    rm -f "$STATE"
    notify-send "Sin modo" "Ningún modo activo (las ventanas quedan como están)" -t 2500
    exit 0
}

place() {
    local ws="$1" match="$2" cmd="$3" addr
    addr="$(find_window "$match")"
    if [[ -n "$addr" ]]; then
        "$HOME/.config/hypr/scripts/hypr-dispatch" movetoworkspacesilent "$ws,address:$addr" >/dev/null
        return
    fi
    "$HOME/.config/hypr/scripts/hypr-dispatch" exec "[workspace $ws silent] $cmd" >/dev/null
    # La regla de exec va por PID: apps que se relanzan a sí mismas (steam,
    # firefoxpwa, electron) abren en otro workspace. Esperar la ventana y moverla.
    (
        for _ in $(seq $((WAIT_SECS * 2))); do
            sleep 0.5
            addr="$(find_window "$match")"
            [[ -n "$addr" ]] || continue
            "$HOME/.config/hypr/scripts/hypr-dispatch" movetoworkspacesilent "$ws,address:$addr" >/dev/null
            exit 0
        done
    ) &
}

if [[ "${1:-}" == "--none" ]]; then
    clear_mode
elif [[ $# -gt 0 ]]; then
    MODE="$1"
else
    choice="$(choose_mode)"
    [[ -n "$choice" ]] || exit 0
    [[ "$choice" == "$MANAGE" ]] && exec bash "$MANAGER_LAUNCH"
    [[ "$choice" == "$NONE"* ]] && clear_mode
    MODE="$(sed -E 's/^[^ ]+  //; s/  \(activo\)$//' <<<"$choice")"
fi

found=0
while IFS='|' read -r mode _icon ws match cmd _name; do
    [[ "$mode" == "$MODE" ]] || continue
    found=1
    [[ -n "$ws" && -n "$match" && -n "$cmd" ]] || continue   # cabecera del modo
    place "$ws" "$match" "$cmd"
done < <(entries)

[[ "$found" -eq 1 ]] || { notify-send "Modos" "No existe el modo $MODE" -t 3000; exit 1; }

rm -f "$DOTFILES_STATE_DIR/desktop-mode"   # estado viejo (persistía entre reinicios)
echo "$MODE" > "$STATE"
"$HOME/.config/hypr/scripts/hypr-dispatch" workspace 1 >/dev/null
notify-send "Modo $MODE" "Apps ubicadas en sus workspaces" -t 2500
wait
