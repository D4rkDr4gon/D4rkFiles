#!/usr/bin/env bash
# =============================================================================
# start-hyprpaper.sh — Wrapper para hyprpaper con reintento (v2 dinámico)
# =============================================================================
# Ya no lee hyprpaper.conf fijo. Genera el config dinámicamente desde
# la fuente de verdad única: ~/.local/state/dotfiles/current_theme.json
#
# Así funciona con ambos flujos:
#   - theme-switch.sh → actualiza current_theme.json → wrapper lo lee
#   - settings-menu.sh (backgrounds) → actualiza current_theme.json → wrapper lo lee
# =============================================================================

MAX_RETRIES=5
RETRY_DELAY=1

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland"
mkdir -p "$LOG_DIR" 2>/dev/null
LOG_FILE="$LOG_DIR/hyprpaper.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

log "=== hyprpaper wrapper start (v2 dinámico) ==="

# ── Obtener wallpaper desde current_theme.json ────────────────────────────────
CURRENT_THEME="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/current_theme.json"
WALLPAPER=""

if [ -f "$CURRENT_THEME" ]; then
    WALLPAPER=$(jq -r '.wallpaper // empty' "$CURRENT_THEME" 2>/dev/null)
fi

# Validar que el archivo existe
if [ -z "$WALLPAPER" ] || [ ! -f "$WALLPAPER" ]; then
    log "[WARN] current_theme.json no tiene wallpaper válido, usando fallback"
    # Fallback: cualquier imagen de los directorios de wallpapers (env.sh)
    # shellcheck source=/dev/null
    source "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/scripts/lib/env.sh"
    IFS=: read -ra _wp_dirs <<<"$WALLPAPER_DIRS"
    for d in "${_wp_dirs[@]}"; do
        WALLPAPER=$(find "$d" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.jpeg' -o -name '*.webp' \) 2>/dev/null | head -1)
        [ -n "$WALLPAPER" ] && break
    done
fi

log "Wallpaper: ${WALLPAPER:-NINGUNO}"

# ── Generar hyprpaper.conf dinámico ───────────────────────────────────────────
HYPRPAPER_CONF="/tmp/hyprpaper-$$.conf"

if [ -n "$WALLPAPER" ] && [ -f "$WALLPAPER" ]; then
    cat > "$HYPRPAPER_CONF" << EOF
# Generado dinámicamente por start-hyprpaper.sh
preload = "$WALLPAPER"
wallpaper = ,"$WALLPAPER"
ipc = on
splash = false
EOF
    log "Config generado en $HYPRPAPER_CONF"
else
    log "[WARN] Sin wallpaper válido, iniciando hyprpaper sin config"
    HYPRPAPER_CONF=""
fi

# ── Iniciar hyprpaper con reintentos ──────────────────────────────────────────
for ((i=1; i<=MAX_RETRIES; i++)); do
    log "Intento $i/$MAX_RETRIES..."

    if [ -n "$HYPRPAPER_CONF" ]; then
        /usr/bin/hyprpaper -c "$HYPRPAPER_CONF" &
    else
        /usr/bin/hyprpaper &
    fi
    HPID=$!

    # Esperar a que hyprpaper se inicie o falle
    sleep 2

    if kill -0 $HPID 2>/dev/null; then
        log "hyprpaper iniciado correctamente (PID: $HPID)"

        # ── Aplicar wallpaper post-arranque (por si el preload no bastó) ─────────
        if [ -n "$WALLPAPER" ] && [ -f "$WALLPAPER" ]; then
            sleep 0.5
            hyprctl hyprpaper wallpaper ",$WALLPAPER" >> "$LOG_FILE" 2>&1 || true
            log "Wallpaper aplicado via hyprctl"
        fi

        # Mantener el proceso en foreground
        wait $HPID
        EXIT_CODE=$?
        log "hyprpaper terminó con código $EXIT_CODE"

        # Limpiar temp
        rm -f "$HYPRPAPER_CONF"
        exit $EXIT_CODE
    else
        log "hyprpaper falló en intento $i"
        sleep "$RETRY_DELAY"
    fi
done

log "[ERROR] hyprpaper no pudo iniciarse después de $MAX_RETRIES intentos"
rm -f "$HYPRPAPER_CONF"
exit 1
