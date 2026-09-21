#!/bin/bash
# ──────────────────────────────────────────────────────────
# battery-watch.sh — Monitoreo de batería con notificaciones
# Notifica al usuario cuando la batería alcanza thresholds
# críticos (15%, 10%, 5%) mientras está en descarga.
# ──────────────────────────────────────────────────────────
set -euo pipefail

STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/battery-watch"
STATE_FILE="${STATE_DIR}/notified"
LOGFILE="${STATE_DIR}/battery-watch.log"

THRESHOLDS=(15 10 5)
# Autodetecta la primera batería (BAT0, BAT1, ...); BATTERY_PATH la fuerza.
BATTERY="${BATTERY_PATH:-}"
if [[ -z "$BATTERY" ]]; then
    for _b in /sys/class/power_supply/BAT*; do
        [[ -e "$_b" ]] && { BATTERY="$_b"; break; }
    done
fi
[[ -n "$BATTERY" ]] || exit 0   # sin batería (desktop): nada que vigilar

mkdir -p "$STATE_DIR"

log() {
    local level="$1" msg="$2"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${level}] ${msg}" >> "$LOGFILE"
}

notify() {
    local level="$1" capacity="$2"
    local urgency="critical"
    local title="Bateria baja: ${capacity}%"
    local body="Conecta el cargador. La bateria esta al ${capacity}%."

    if [[ "$capacity" -le 5 ]]; then
        body="CRITICO: ${capacity}% — la bateria esta por agotarse. Conecta el cargador YA."
    elif [[ "$capacity" -le 10 ]]; then
        body="Bateria al ${capacity}% — conecta el cargador pronto."
    fi

    notify-send -u "$urgency" -t 10000 "$title" "$body"
    log "NOTIFY" "Notificación enviada: ${capacity}%"
}

# Leer estado actual de la batería
CAPACITY_FILE="${BATTERY}/capacity"
STATUS_FILE="${BATTERY}/status"

if [[ ! -f "$CAPACITY_FILE" ]]; then
    log "ERROR" "Batería no encontrada en ${BATTERY}"
    exit 1
fi

CAPACITY=$(cat "$CAPACITY_FILE" 2>/dev/null || echo "100")
STATUS=$(cat "$STATUS_FILE" 2>/dev/null || echo "Unknown")

log "DEBUG" "Capacidad=${CAPACITY}% | Estado=${STATUS}"

# Solo notificar si está descargando (discharging)
if [[ "$STATUS" != "Discharging" ]]; then
    log "DEBUG" "No está descargando (${STATUS}), se omite"
    exit 0
fi

# Cargar thresholds ya notificados
declare -A NOTIFIED
if [[ -f "$STATE_FILE" ]]; then
    while IFS='=' read -r key val; do
        NOTIFIED["$key"]="$val"
    done < "$STATE_FILE"
fi

# Verificar cada threshold
for threshold in "${THRESHOLDS[@]}"; do
    if [[ "$CAPACITY" -le "$threshold" ]]; then
        if [[ "${NOTIFIED[$threshold]:-0}" -ne 1 ]]; then
            notify "$threshold" "$CAPACITY"
            NOTIFIED["$threshold"]=1
        else
            log "DEBUG" "Threshold ${threshold}% ya notificado, se omite"
        fi
    else
        # Si la capacidad subió del threshold (ej: conectaron el cargador), resetear
        if [[ "${NOTIFIED[$threshold]:-0}" -eq 1 ]]; then
            log "INFO" "Capacidad (${CAPACITY}%) superó threshold ${threshold}% — reseteando"
            unset "NOTIFIED[$threshold]"
        fi
    fi
done

# Persistir estado
: > "$STATE_FILE"
for k in "${!NOTIFIED[@]}"; do
    echo "${k}=${NOTIFIED[$k]}" >> "$STATE_FILE"
done

log "INFO" "Chequeo completado — ${CAPACITY}% | Estado: ${STATUS}"
exit 0
