#!/usr/bin/env bash
# Lanza polybar en cada monitor conectado (X11/Qtile).
# Autodetecta batería, adaptador de corriente e interfaz Wi-Fi, y los pasa a
# los módulos por variables de entorno (ver modules/battery.ini y wlan.ini).

pkill -x polybar 2>/dev/null
while pgrep -u "$UID" -x polybar >/dev/null; do sleep 0.2; done

ps=/sys/class/power_supply
for d in "$ps"/BAT*; do [ -e "$d" ] && { POLYBAR_BAT=$(basename "$d"); break; }; done
for d in "$ps"/*; do
    [ "$(cat "$d/type" 2>/dev/null)" = "Mains" ] && { POLYBAR_AC=$(basename "$d"); break; }
done
for d in /sys/class/net/*/wireless; do
    [ -e "$d" ] && { POLYBAR_WLAN=$(basename "$(dirname "$d")"); break; }
done
export POLYBAR_BAT POLYBAR_AC POLYBAR_WLAN

if command -v xrandr >/dev/null 2>&1; then
    for m in $(xrandr --query | awk '/ connected/{print $1}'); do
        MONITOR=$m setsid -f polybar --reload example >/dev/null 2>&1
    done
else
    setsid -f polybar --reload example >/dev/null 2>&1
fi
