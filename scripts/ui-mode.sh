#!/usr/bin/env bash
# ui-mode.sh — imprime el modo de sesión: "tui" o "gui".
# Lee ~/.config/dotfiles/ui.conf (UI_CONF apunta a una copia en las pruebas). Si falta el
# archivo, falta la clave o el valor es inválido, imprime "tui" (el de siempre).
conf="${UI_CONF:-${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/ui.conf}"
mode=""
[ -r "$conf" ] && mode=$(sed -n 's/^[[:space:]]*mode[[:space:]]*=[[:space:]]*\([A-Za-z]*\).*/\1/p' "$conf" | tail -n1)
case "$mode" in
    gui) echo gui ;;
    *)   echo tui ;;
esac
