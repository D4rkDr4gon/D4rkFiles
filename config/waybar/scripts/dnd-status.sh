#!/usr/bin/env bash
# Modulo waybar: estado de No Molestar (regla dnd_global de dunst, que
# maneja rofi/scripts/dnd-menu.sh). No usa `dunstctl is-paused`: el DND de
# estos dotfiles es una regla skip_display, no la pausa de dunst.
# Se refresca por polling y al instante con `pkill -RTMIN+9 waybar`.

ICON_ON="󰂛"
ICON_OFF="󰂚"
TIMER_STATE="$HOME/.cache/dunst-dnd-until"

if dunstctl rules --json 2>/dev/null \
    | jq -e '.data[][] | select(.name.data=="dnd_global") | .enabled.data == true' &>/dev/null; then
    tooltip="No Molestar: activado"
    if [ -f "$TIMER_STATE" ]; then
        until=$(cat "$TIMER_STATE")
        [ "$until" -gt "$(date +%s)" ] 2>/dev/null \
            && tooltip="$tooltip (hasta las $(date -d "@$until" '+%H:%M'))"
    fi
    jq -cn --arg t "$ICON_ON" --arg tt "$tooltip" '{text: $t, tooltip: $tt, class: "active"}'
else
    jq -cn --arg t "$ICON_OFF" '{text: $t, tooltip: "No Molestar: desactivado", class: "inactive"}'
fi
