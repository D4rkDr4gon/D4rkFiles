#!/usr/bin/env bash
# Workspace switcher (rofi, respaldo: lo reemplazó tools/launcher_tui.py workspaces)

# Los habilitados en Settings → Workspaces ("# count: N" de
# ~/.config/dotfiles/hypr/workspaces.conf, 9 si no existe)
N=$(sed -n 's/^# count: *\([0-9]\+\).*/\1/p' "${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/hypr/workspaces.conf" 2>/dev/null | head -1)
N=${N:-9}
LIST=""
for i in $(seq 1 "$N"); do LIST+=" Workspace $i\n"; done

CHOICE=$(printf "$LIST" | rofi -dmenu -p "Go to workspace")

[ -z "$CHOICE" ] && exit 0

WS=$(echo "$CHOICE" | awk '{print $NF}')

"$HOME/.config/hypr/scripts/hypr-dispatch" workspace "$WS"
