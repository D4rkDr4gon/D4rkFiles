#!/usr/bin/env bash
# Rueda sobre los workspaces de waybar: da la vuelta dentro de los habilitados
# (Settings → Workspaces). Uso: workspace-switch.sh next|prev
exec bash "$HOME/.config/hypr/scripts/workspace-cycle.sh" "${1:-}"
