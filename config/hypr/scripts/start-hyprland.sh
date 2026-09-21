#!/usr/bin/env bash
# =============================================================================
# start-hyprland.sh — Wrapper de arranque para Hyprland (v3)
# =============================================================================
# Propósito:
#   - Limpiar variables X11 heredadas del display manager (DISPLAY)
#   - Forzar variables de entorno Wayland
#   - Activar sesión en logind (evita "session inactive")
#   - Capturar logs ante crashes
# =============================================================================
# NOTA: NO usar set -e. Script debe continuar aunque hyprctl logind etc falle.
set -E

# ── Logging simple (sin process substitution que pueda fallar con el display manager) ───
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/session.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

log "=== Hyprland session start (v3) ==="

# ── Capturar info básica ──────────────────────────────────────────────────────
log "User: $(whoami 2>&1)"
log "Groups: $(groups 2>&1)"
log "DISPLAY before cleanup: '${DISPLAY:-unset}'"
log "XAUTHORITY before cleanup: '${XAUTHORITY:-unset}'"
log "XDG_SESSION_TYPE before: '${XDG_SESSION_TYPE:-unset}'"
log "WAYLAND_DISPLAY before: '${WAYLAND_DISPLAY:-unset}'"

# ── Limpiar variables X11 heredadas del display manager ──────────────────────────────
log "[INFO] Limpiando variables X11 heredadas..."
unset DISPLAY
unset XAUTHORITY
log "  DISPLAY after unset: '${DISPLAY:-unset}'"

# ── Forzar Wayland ──────────────────────────────────────────────────────────
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=Hyprland
export XDG_SESSION_DESKTOP=Hyprland

# ── AMD GPU fix ─────────────────────────────────────────────────────────────
export WLR_NO_HARDWARE_CURSORS=1
log "  WLR_NO_HARDWARE_CURSORS=1"

# ── Activar sesión en logind ────────────────────────────────────────────────
if [ -n "$XDG_SESSION_ID" ]; then
    log "[INFO] Activando sesión logind: $XDG_SESSION_ID"
    loginctl activate-session "$XDG_SESSION_ID" >> "$LOG_FILE" 2>&1 || log "[WARN] No se pudo activar sesión logind"
else
    log "[WARN] XDG_SESSION_ID no está definida - saltando logind activation"
fi

# ── Información del sistema ─────────────────────────────────────────────────
log "Kernel: $(uname -r 2>&1)"
log "GPU: $(lspci -k 2>/dev/null | grep -A2 -E '(VGA|3D)' | head -3 | tr '\n' ' ')"
log "Hyprland version: $(/usr/bin/Hyprland --version 2>&1 | head -1)"

# ── Verificar que el binario existe ─────────────────────────────────────────
if [ ! -x /usr/bin/Hyprland ]; then
    log "[CRITICAL] /usr/bin/Hyprland no encontrado o no ejecutable"
    exit 1
fi

# ── Sincronizar log antes de lanzar Hyprland ────────────────────────────────
sync

# ── Lanzar Hyprland ─────────────────────────────────────────────────────────
log "[INFO] Lanzando /usr/bin/Hyprland..."
exec /usr/bin/Hyprland
