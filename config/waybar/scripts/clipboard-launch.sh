#!/usr/bin/env bash
# Historial del portapapeles (Mod+V): ventana centrada con tools/clipboard_tui.py
# (ver center-tui-launch.sh).
exec bash "$HOME/.config/waybar/scripts/center-tui-launch.sh" clipboard 'Clipboard' \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/clipboard_tui.py"
