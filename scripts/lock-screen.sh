#!/usr/bin/env bash
# Bloqueo de pantalla (Super+L → Lock, hypridle): gtklock con fondo negro y el
# banner ASCII en el color primary del tema. Todo vive en gtklock/layout.ui +
# style.css (theme-switch.sh escribe @banner_color); no depende de grim/ImageMagick.

DOTFILES="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/lock-screen.log"
echo "--- $(date) ---" >> "$LOG"

gtklock >> "$LOG" 2>&1
status=$?
echo "exit: $status" >> "$LOG"

# Al desbloquear: saludo (mismo que el de inicio de sesión).
[ "$status" -eq 0 ] && bash "$DOTFILES/scripts/welcome.sh"
exit 0
