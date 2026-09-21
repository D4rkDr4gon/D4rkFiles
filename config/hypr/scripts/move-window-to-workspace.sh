#!/bin/bash
# =============================================================================
# move-window-to-workspace.sh
# =============================================================================
# Mueve la ventana enfocada al workspace N, trae ese workspace al monitor
# actual, y lo enfoca.
#
# Comportamiento tipo Qtile: mod+shift+1 mueve la ventana al workspace 1
# y trae workspace 1 al monitor actual (no se queda en el otro monitor).
#
# Uso: move-window-to-workspace.sh <workspace_number>
# =============================================================================

set -Euo pipefail

# --- Config ---
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland"
mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/workspace.log"

# --- Logging ---
log() {
    echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"
}

# --- Validación ---
TARGET_WS="${1:-}"
if [[ -z "$TARGET_WS" ]]; then
    log "ERROR: No se especificó workspace"
    echo "Uso: $0 <workspace_number>"
    exit 1
fi

# --- Obtener monitor enfocado ---
FOCUSED_MONITOR=$(hyprctl monitors -j | jq -r '.[] | select(.focused == true) | .name')

if [[ -z "$FOCUSED_MONITOR" ]]; then
    log "ERROR: No se pudo detectar el monitor enfocado"
    exit 1
fi

log "move-window: target=$TARGET_WS | monitor=$FOCUSED_MONITOR"

# 1. Mover ventana al workspace en silencio (sin cambiar foco)
hyprctl dispatch movetoworkspacesilent "$TARGET_WS"
log "Window moved to workspace $TARGET_WS (silent)"

# 2. Traer workspace al monitor actual
hyprctl dispatch moveworkspacetomonitor "$TARGET_WS" "$FOCUSED_MONITOR"
log "Workspace $TARGET_WS moved to $FOCUSED_MONITOR"

# 3. Enfocar workspace
hyprctl dispatch workspace "$TARGET_WS"
log "Focused workspace $TARGET_WS"

exit 0
