#!/usr/bin/env bash
# Dual-WM workspace switcher (Qtile / Hyprland)

# Hyprland: los habilitados en Settings → Workspaces ("# count: N" de
# ~/.config/dotfiles/hypr/workspaces.conf, 9 si no existe); Qtile: 6
N=6
if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    N=$(sed -n 's/^# count: *\([0-9]\+\).*/\1/p' "${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/hypr/workspaces.conf" 2>/dev/null | head -1)
    N=${N:-9}
fi
LIST=""
for i in $(seq 1 "$N"); do LIST+=" Workspace $i\n"; done

CHOICE=$(printf "$LIST" | rofi -dmenu -p "Go to workspace")

[ -z "$CHOICE" ] && exit 0

WS=$(echo "$CHOICE" | awk '{print $NF}')

if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    hyprctl dispatch workspace "$WS"
else
    qtile cmd-obj -o group "$WS" -f toscreen
fi
