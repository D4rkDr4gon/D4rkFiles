#!/usr/bin/env bash
# =============================================================================
# workspace-cycle.sh — siguiente/anterior workspace dando la vuelta en 1..N
# =============================================================================
# N = los workspaces habilitados (línea "# count: N" de
# ~/.config/dotfiles/hypr/workspaces.conf, que genera Settings → Workspaces;
# 9 si no existe). `workspace +1` de Hyprland seguiría de
# largo y crearía workspaces fuera de los atajos; esto vuelve al 1.
#
# Uso: workspace-cycle.sh next|prev   (Ctrl+Tab / Ctrl+Shift+Tab, rueda en waybar)
# =============================================================================

set -u
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/hypr/workspaces.conf"
N=$(sed -n 's/^# count: *\([0-9]\+\).*/\1/p' "$CONF" 2>/dev/null | head -1)
N=${N:-9}

cur=$(hyprctl activeworkspace -j | jq -r '.id')
case "$cur" in ''|*[!0-9-]*) cur=1 ;; esac

case "${1:-next}" in
    next) if [ "$cur" -lt 1 ] || [ "$cur" -ge "$N" ]; then n=1; else n=$((cur + 1)); fi ;;
    prev) if [ "$cur" -le 1 ] || [ "$cur" -gt "$N" ]; then n=$N; else n=$((cur - 1)); fi ;;
    *) echo "Uso: $0 next|prev" >&2; exit 1 ;;
esac

hyprctl dispatch workspace "$n" >/dev/null
