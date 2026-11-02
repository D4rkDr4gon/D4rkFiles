#!/usr/bin/env bash
# Lanzador y menús rápidos (reemplazo de rofi): ventana centrada con
# tools/launcher_tui.py (ver center-tui-launch.sh). Una clase por modo, así cada
# uno tiene su tamaño (hl.window_rule en config/hypr/hyprland.lua) y el toggle
# no cierra otro modo.
#
# Uso: launcher-launch.sh [apps|emoji|power|workspaces]
MODE="${1:-apps}"
case "$MODE" in
    apps)       CLASS=launcher;       TITLE='Launcher' ;;
    emoji)      CLASS=launcher-emoji; TITLE='Emoji' ;;
    power)      CLASS=launcher-power; TITLE='Session' ;;
    workspaces) CLASS=launcher-ws;    TITLE='Workspaces' ;;
    *) echo "uso: $(basename "$0") [apps|emoji|power|workspaces]" >&2; exit 2 ;;
esac
exec bash "$HOME/.config/waybar/scripts/center-tui-launch.sh" "$CLASS" "$TITLE" \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/launcher_tui.py" "$MODE"
