#!/usr/bin/env bash
# Gestor de modos de escritorio (Settings → MODES → Gestionar modos): delega
# en el lanzador genérico de TUIs flotantes con tools/modes_tui.py.
exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    modes 'Modos' 110 28 \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/modes_tui.py"
