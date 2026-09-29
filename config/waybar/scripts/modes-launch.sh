#!/usr/bin/env bash
# Gestor de modos de escritorio (Settings → MODES → Gestionar modos): delega
# en el lanzador genérico de TUIs flotantes con scripts/mode-manager.sh.
exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    modes 'Modos' 90 24 \
    bash "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/scripts/mode-manager.sh"
