#!/usr/bin/env bash

DOTFILES="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/lock-screen.log"
echo "--- $(date) ---" >> "$LOG"

# Read active wallpaper from current theme
THEME_FILE="$LOG_DIR/current_theme.json"
WALLPAPER=""
if command -v jq &>/dev/null && [[ -f "$THEME_FILE" ]]; then
  WALLPAPER=$(jq -r '.wallpaper' "$THEME_FILE")
fi

if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
  # Fondo negro + banner ASCII en el color primary del tema: todo vive en
  # gtklock/layout.ui + style.css (theme-switch.sh escribe @banner_color).
  # Ya no hay screenshot/blur previo, así que no depende de grim/ImageMagick.
  gtklock >> "$LOG" 2>&1
  status=$?
else
  if command -v betterlockscreen &>/dev/null; then
    if [[ -n "$WALLPAPER" && -f "$WALLPAPER" ]]; then
      betterlockscreen -u "$WALLPAPER" >> "$LOG" 2>&1
    fi
    betterlockscreen -l dim >> "$LOG" 2>&1
  elif [[ -n "$WALLPAPER" && -f "$WALLPAPER" ]]; then
    i3lock -i "$WALLPAPER" -t >> "$LOG" 2>&1
  else
    i3lock -c 000000 >> "$LOG" 2>&1
  fi
  status=$?
fi

echo "exit: $status" >> "$LOG"

# Al desbloquear: saludo (mismo que el de inicio de sesión).
[ "${status:-1}" -eq 0 ] && bash "$DOTFILES/scripts/welcome.sh"
exit 0
