#!/bin/bash
# =============================================================================
# move-and-focus-workspace.sh
# =============================================================================
# Comportamiento tipo Qtile para workspaces multi-monitor.
#
# En Qtile: mod+1 en el monitor externo trae workspace 1 al monitor actual.
# En Hyprland nativo: mod+1 solo enfoca workspace 1 donde esté (no lo mueve).
#
# Este script:
#   1. Detecta el monitor actualmente enfocado
#   2. Mueve el workspace objetivo a ese monitor
#   3. Enfoca el workspace objetivo
#
# Uso: move-and-focus-workspace.sh <workspace_number>
# Ejemplo: move-and-focus-workspace.sh 1
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
# Usar hyprctl monitors -j para JSON, más robusto que parsear texto
FOCUSED_MONITOR=$(hyprctl monitors -j | jq -r '.[] | select(.focused == true) | .name')

if [[ -z "$FOCUSED_MONITOR" ]]; then
    log "ERROR: No se pudo detectar el monitor enfocado"
    exit 1
fi

log "Target: ws=$TARGET_WS | Monitor=$FOCUSED_MONITOR"

# --- Mover workspace al monitor actual ---
# Si el workspace ya está en este monitor, moveworkspacetomonitor es no-op
hyprctl dispatch moveworkspacetomonitor "$TARGET_WS" "$FOCUSED_MONITOR"
log "Moved workspace $TARGET_WS to $FOCUSED_MONITOR"

# --- Enfocar workspace ---
hyprctl dispatch workspace "$TARGET_WS"
log "Focused workspace $TARGET_WS"

exit 0
