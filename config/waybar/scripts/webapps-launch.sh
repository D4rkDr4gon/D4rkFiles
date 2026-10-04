#!/usr/bin/env bash
# Gestor de webapps (Settings → WEBAPPS): delega en el lanzador genérico de
# TUIs flotantes (float-tui-launch.sh) con tools/webapps_tui.py.
exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    webapps 'Webapps' 100 26 \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/webapps_tui.py"
