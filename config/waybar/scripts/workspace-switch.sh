#!/usr/bin/env bash
# Dual-WM workspace switch para Waybar on-scroll
# Usage: workspace-switch.sh next|prev

ACTION="${1:-}"

if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
    # Hyprland
    case "$ACTION" in
        next) hyprctl dispatch workspace +1 ;;
        prev) hyprctl dispatch workspace -1 ;;
    esac
else
    # Qtile
    bash "$HOME/.config/waybar/scripts/qtile-workspace-switch.sh" "$ACTION"
fi
