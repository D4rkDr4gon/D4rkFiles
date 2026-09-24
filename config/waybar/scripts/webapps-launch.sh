#!/usr/bin/env bash
# Gestor de webapps (Settings → WEBAPPS): delega en el lanzador genérico de
# TUIs flotantes (float-tui-launch.sh) con scripts/webapp-manager.sh.
exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    webapps 'Webapps' 90 24 \
    bash "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/scripts/webapp-manager.sh"
