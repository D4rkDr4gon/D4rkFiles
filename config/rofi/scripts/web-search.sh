#!/usr/bin/env bash

query=$(rofi -dmenu -p "🌐 Search" -theme $HOME/.config/rofi/theme.rasi \
    -theme-str 'entry { placeholder: "Google search..."; }')

[ -z "$query" ] && exit 0

encoded=$(echo "$query" | sed 's/ /+/g')

"$HOME/.config/hypr/scripts/hypr-dispatch" workspace 5
xdg-open "https://www.google.com/search?q=$encoded" &
