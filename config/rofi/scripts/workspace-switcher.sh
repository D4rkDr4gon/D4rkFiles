#!/usr/bin/env bash
# Dual-WM workspace switcher (Qtile / Hyprland)

LIST=" Workspace 1\n Workspace 2\n Workspace 3\n Workspace 4\n Workspace 5\n Workspace 6\n"
# Hyprland tiene 9 workspaces; Qtile solo 6
[ -n "$HYPRLAND_INSTANCE_SIGNATURE" ] && LIST+=" Workspace 7\n Workspace 8\n Workspace 9\n"

CHOICE=$(printf "$LIST" | rofi -dmenu -p "Go to workspace")

[ -z "$CHOICE" ] && exit 0

WS=$(echo "$CHOICE" | awk '{print $NF}')

if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    hyprctl dispatch workspace "$WS"
else
    qtile cmd-obj -o group "$WS" -f toscreen
fi
