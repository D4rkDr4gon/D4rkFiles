#!/usr/bin/env bash
# Cheatsheet de shortcuts (Hyprland/kitty/herdr/Qtile, ver + editar):
# delega en el lanzador genérico de TUIs flotantes (float-tui-launch.sh)
# con el tamaño que necesita la tabla de shortcuts_tui.py.
exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    shortcuts 'Shortcuts' 110 34 \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/shortcuts_tui.py"
