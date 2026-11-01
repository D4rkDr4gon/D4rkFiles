#!/usr/bin/env bash
# Spotify (Super+Y, Settings → Spotify `o`): ventana centrada con
# tools/spotify_tui.py, que habla con la Web API y usa spotify_player como
# daemon (ver center-tui-launch.sh).
exec bash "$HOME/.config/waybar/scripts/center-tui-launch.sh" spotify-tui 'Spotify' \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/spotify_tui.py"
