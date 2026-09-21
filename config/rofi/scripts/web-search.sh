#!/usr/bin/env bash

query=$(rofi -dmenu -p "🌐 Search" -theme $HOME/.config/rofi/theme.rasi \
    -theme-str 'entry { placeholder: "Google search..."; }')

[ -z "$query" ] && exit 0

encoded=$(echo "$query" | sed 's/ /+/g')

if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    hyprctl dispatch workspace 5
else
    qtile cmd-obj -o group "5" -f toscreen
fi
xdg-open "https://www.google.com/search?q=$encoded" &

if [ "$XDG_SESSION_TYPE" != "wayland" ]; then
    for _ in {1..10}; do
        wmctrl -a firefox 2>/dev/null && break
        sleep 0.1
    done
fi
