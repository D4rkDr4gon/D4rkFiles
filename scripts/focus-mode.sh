#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# focus-mode.sh — Modo Focus: No Molestar + sin distracciones en el escritorio.
# Prende la regla dnd_global de dunst (en memoria: no toca el dunstrc, así que un
# reinicio la deja como estaba) y oculta los widgets de los workspaces vacíos
# que distraen (música, clima, teléfono, dinero: dwlib.FOCUS_HIDDEN). Al salir
# devuelve DND a como estaba antes (si ya lo tenías prendido, sigue prendido).
# El estado vive en $XDG_RUNTIME_DIR/focus-mode: el daemon de widgets lo vigila.
#
# Uso: focus-mode.sh [toggle | on | off | status]
# ──────────────────────────────────────────────────────────
set -uo pipefail

STATE="${XDG_RUNTIME_DIR:-/tmp}/focus-mode"

dnd_active() {
    dunstctl rules --json 2>/dev/null \
        | jq -e '.data[][] | select(.name.data=="dnd_global") | .enabled.data == true' &>/dev/null
}

osd() {   # swayosd, no dunst: con DND prendido una notificación no se vería
    command -v swayosd-client &>/dev/null \
        && swayosd-client --custom-message "$1" --custom-icon "$2" &>/dev/null &
}

focus_on() {
    [[ -e "$STATE" ]] && return 0
    local before=false
    dnd_active && before=true
    dunstctl rule dnd_global enable &>/dev/null
    pkill -RTMIN+9 -x waybar 2>/dev/null   # módulo custom/dnd
    printf '{"dnd_before": %s}\n' "$before" > "$STATE.tmp" && mv "$STATE.tmp" "$STATE"
    osd "Focus on" "weather-clear-night-symbolic"
}

focus_off() {
    [[ -e "$STATE" ]] || return 0
    local before
    before="$(jq -r '.dnd_before // false' "$STATE" 2>/dev/null)"
    [[ "$before" == "true" ]] || dunstctl rule dnd_global disable &>/dev/null
    rm -f "$STATE"
    pkill -RTMIN+9 -x waybar 2>/dev/null
    osd "Focus off" "weather-clear-symbolic"
}

case "${1:-toggle}" in
    toggle) if [[ -e "$STATE" ]]; then focus_off; else focus_on; fi ;;
    on)     focus_on ;;
    off)    focus_off ;;
    status) if [[ -e "$STATE" ]]; then echo on; else echo off; exit 1; fi ;;
    *) echo "Uso: $(basename "$0") [toggle|on|off|status]" >&2; exit 2 ;;
esac
