#!/usr/bin/env bash
# Action Menu — Dual-WM (Qtile + Hyprland)

DOTFILES="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}"

CHOICE=$(printf "Lock\0icon\x1fsystem-lock-screen\nSuspend\0icon\x1fsystem-suspend\nReboot\0icon\x1fsystem-reboot\nPoweroff\0icon\x1fsystem-shutdown\nLogout\0icon\x1fapplication-exit" |
  rofi -dmenu -p "Actions" -show-icons -theme "$HOME/.config/rofi/theme-action.rasi")

[ -z "$CHOICE" ] && exit 0

case "$CHOICE" in
"Lock")
  bash "$DOTFILES/scripts/lock-screen.sh"
  ;;
"Suspend")
  systemctl suspend
  ;;
"Reboot")
  systemctl reboot
  ;;
"Poweroff")
  systemctl poweroff
  ;;
"Logout")
  if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    hyprctl dispatch exit
  else
    qtile cmd-obj -o cmd -f shutdown
  fi
  ;;
esac
