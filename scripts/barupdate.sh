#!/usr/bin/env bash

if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    exec "$HOME/.config/waybar/launch.sh"
else
    exec "$HOME/.config/polybar/launch.sh"
fi
