#!/usr/bin/env bash
# Notificación con el estado de la batería (on-click del módulo de waybar).
# Autodetecta la batería: no asume que se llame BAT0.
bat=$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -n1)
[ -n "$bat" ] || { notify-send -u low "Batería" "No se detectó batería"; exit 0; }
notify-send -u low "Batería" "$(cat "$bat/capacity")% - $(cat "$bat/status")"
