#!/usr/bin/env bash
# Settings (Mod+Shift+Space, logo de waybar/polybar): ventana centrada con
# tools/settings/settings_tui.py (ver center-tui-launch.sh).
exec bash "$HOME/.config/waybar/scripts/center-tui-launch.sh" settings 'Settings' \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/settings/settings_tui.py"
