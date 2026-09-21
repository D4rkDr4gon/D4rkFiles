#!/usr/bin/env bash
# Módulo waybar: estado de VPN (perfiles de NetworkManager).
# Delega en tools/vpn_tui.py --waybar-status (modo liviano, sin Textual, pensado
# para no colgar el polling de waybar). Sin perfiles configurados queda en "disabled".

exec python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/vpn_tui.py" --waybar-status
