#!/usr/bin/env bash
# Dual-WM workspace switch para Waybar on-scroll
# Usage: workspace-switch.sh next|prev

ACTION="${1:-}"

if [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
    # Hyprland
    # da la vuelta dentro de los workspaces habilitados (Settings → Workspaces)
    bash "$HOME/.config/hypr/scripts/workspace-cycle.sh" "$ACTION"
else
    # Qtile
    bash "$HOME/.config/waybar/scripts/qtile-workspace-switch.sh" "$ACTION"
fi
