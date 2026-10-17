#!/usr/bin/env bash
# Backup en Proton Drive (Settings → Backup): delega en el lanzador genérico
# de TUIs flotantes con tools/backup_tui.py. Sin Hyprland abre una kitty común.
TUI="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/backup_tui.py"
if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
        proton-backup 'Backup' 120 28 \
        python3 "$TUI"
fi
exec kitty --class proton-backup --title 'Backup' python3 "$TUI"
