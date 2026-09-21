#!/usr/bin/env bash
# Notificación de bienvenida (inicio de sesión y al desbloquear la pantalla).
# El nombre sale de ~/.config/dotfiles/user.conf (USER_DISPLAY_NAME).

# shellcheck source=lib/env.sh
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"

notify-send -u normal -t 3000 \
    "Bienvenido de nuevo, ${USER_DISPLAY_NAME}" \
    "${USER_TITLE:-Todos los sistemas en línea.}"
