#!/bin/bash
# Status line: [modelo] - [esfuerzo] | ctx | 5h | 7d | carpeta actual
# + porcentaje de consumo de la suscripción (ventana de 5h y semanal de 7 días)
# + porcentaje de contexto usado en la sesión (mismo dato que /context)

input=$(cat)

MODEL=$(echo "$input" | jq -r '.model.display_name // .model.id // empty')
EFFORT=$(echo "$input" | jq -r '.effort.level // empty')
CWD=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // empty')
[ -z "$CWD" ] && CWD=$(pwd)
DIR=$(basename "$CWD")

PROMPT="[${MODEL:-?}]"
[ -n "$EFFORT" ] && PROMPT="${PROMPT} - [${EFFORT}]"

GREEN='@ansi_ok@'
YELLOW='@ansi_warn@'
RED='@ansi_error@'
USAGE_RED='@ansi_primary@'
DIM='\033[2m'
RESET='\033[0m'

color_for_pct() {
    local pct="${1%.*}"
    if [ "$pct" -ge 80 ] 2>/dev/null; then
        echo -e "$RED"
    elif [ "$pct" -ge 50 ] 2>/dev/null; then
        echo -e "$YELLOW"
    else
        echo -e "$GREEN"
    fi
}

fmt_reset() {
    # $1 = unix epoch seconds, $2 = "time_only" para omitir el día
    if [ "$2" = "time_only" ]; then
        date -d "@$1" '+%H:%M' 2>/dev/null
    else
        date -d "@$1" '+%a %H:%M' 2>/dev/null
    fi
}

make_bar() {
    # $1 = porcentaje, $2 = color de la barra (código ANSI)
    local pct_fmt filled empty bar_color="$2"
    pct_fmt=$(printf '%.0f' "$1")
    filled=$((pct_fmt / 10))
    [ "$filled" -gt 10 ] && filled=10
    local bar empty_bar
    bar=$(printf '▓%.0s' $(seq 1 "$filled" 2>/dev/null))
    empty_bar=$(printf '░%.0s' $(seq 1 $((10 - filled)) 2>/dev/null))
    echo -e "${bar_color}${bar}${RESET}${DIM}${empty_bar}${RESET}"
}

CTX_PCT=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
if [ -n "$CTX_PCT" ]; then
    C=$(color_for_pct "$CTX_PCT")
    PCT_FMT=$(printf '%.0f' "$CTX_PCT")
    BAR=$(make_bar "$CTX_PCT" "$C")
    CTX="${C}ctx${RESET} ${BAR} ${C}${PCT_FMT}%${RESET}"
fi

FIVE_H_PCT=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
FIVE_H_RESET=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
WEEK_PCT=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
WEEK_RESET=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')

LIMITS=""

if [ -n "$FIVE_H_PCT" ]; then
    C=$(color_for_pct "$FIVE_H_PCT")
    PCT_FMT=$(printf '%.0f' "$FIVE_H_PCT")
    BAR=$(make_bar "$FIVE_H_PCT" "$USAGE_RED")
    PART="${C}5h${RESET} ${BAR} ${C}${PCT_FMT}%${RESET}"
    if [ -n "$FIVE_H_RESET" ]; then
        PART="${PART} ${DIM}($(fmt_reset "$FIVE_H_RESET" time_only))${RESET}"
    fi
    LIMITS="$PART"
fi

if [ -n "$WEEK_PCT" ]; then
    C=$(color_for_pct "$WEEK_PCT")
    PCT_FMT=$(printf '%.0f' "$WEEK_PCT")
    BAR=$(make_bar "$WEEK_PCT" "$USAGE_RED")
    PART="${C}7d${RESET} ${BAR} ${C}${PCT_FMT}%${RESET}"
    if [ -n "$WEEK_RESET" ]; then
        PART="${PART} ${DIM}($(fmt_reset "$WEEK_RESET"))${RESET}"
    fi
    [ -n "$LIMITS" ] && LIMITS="${LIMITS} | ${PART}" || LIMITS="$PART"
fi

LINE="$PROMPT"
[ -n "$CTX" ] && LINE="${LINE} | ${CTX}"
[ -n "$LIMITS" ] && LINE="${LINE} | ${LIMITS}"
LINE="${LINE} | ${DIR}"

echo -e "$LINE"

# Cache para el widget de waybar "Agentes IA" (waybar/scripts/claude-agents-*.sh).
# Se escriben dos cosas:
#   1) usage-cache.json          -> snapshot de la ULTIMA sesion (compat, lo usa el pill de waybar)
#   2) usage-cache.d/<session>.json -> una entrada POR sesion, para que la TUI
#      (claude-agents-tui.sh) pueda listar todos los agentes de Claude Code
#      abiertos a la vez y no solo el ultimo con el que se interactuo.
SESSION_ID=$(echo "$input" | jq -r '.session_id // empty')
NOW_EPOCH=$(date '+%s')

CACHE_FILE="$HOME/.claude/usage-cache.json"
jq -n \
    --arg five "$FIVE_H_PCT" \
    --arg seven "$WEEK_PCT" \
    --arg five_reset "$FIVE_H_RESET" \
    --arg seven_reset "$WEEK_RESET" \
    --arg ctx "$CTX_PCT" \
    --arg session_dir "$(basename "$(pwd)")" \
    --arg updated "$(date '+%Y-%m-%d %H:%M')" \
    '{
        five_hour_pct: (if $five == "" then null else ($five | tonumber) end),
        seven_day_pct: (if $seven == "" then null else ($seven | tonumber) end),
        five_hour_reset: (if $five_reset == "" then null else ($five_reset | tonumber) end),
        seven_day_reset: (if $seven_reset == "" then null else ($seven_reset | tonumber) end),
        context_pct: (if $ctx == "" then null else ($ctx | tonumber) end),
        session_dir: $session_dir,
        updated_at: $updated
    }' > "$CACHE_FILE" 2>/dev/null

if [ -n "$SESSION_ID" ]; then
    CACHE_DIR="$HOME/.claude/usage-cache.d"
    mkdir -p "$CACHE_DIR" 2>/dev/null

    # Nombre de la sesion. Prioridad:
    #   1) el nombre puesto a mano con /rename -> vive en
    #      <carpeta del transcript>/<session_id>/custom-title.json
    #      ({"customTitle": "..."})
    #   2) el titulo autogenerado que se ve al hacer `claude --resume`
    #      (ultima linea {"type":"ai-title","aiTitle": "..."} del transcript;
    #      se puede regenerar a medida que avanza la conversacion, por eso
    #      se toma la ultima ocurrencia)
    TRANSCRIPT_PATH=$(echo "$input" | jq -r '.transcript_path // empty')
    TITLE=""
    if [ -n "$TRANSCRIPT_PATH" ]; then
        CUSTOM_TITLE_FILE="$(dirname "$TRANSCRIPT_PATH")/$SESSION_ID/custom-title.json"
        if [ -f "$CUSTOM_TITLE_FILE" ]; then
            TITLE=$(jq -r '.customTitle // empty' "$CUSTOM_TITLE_FILE" 2>/dev/null)
        fi
        if [ -z "$TITLE" ] && [ -f "$TRANSCRIPT_PATH" ]; then
            TITLE=$(grep -a '"type":"ai-title"' "$TRANSCRIPT_PATH" 2>/dev/null | tail -1 | jq -r '.aiTitle // empty' 2>/dev/null)
        fi
    fi

    # PID del proceso `claude` que nos invoco (statusline-command.sh corre
    # como hijo directo suyo). Sirve para que la TUI pueda: 1) descartar la
    # entrada si el proceso ya murio (terminal cerrada) y 2) si un mismo
    # proceso tiene mas de una entrada (por ej. hizo /clear y arranco una
    # sesion nueva, con otro session_id, en la misma terminal) quedarse solo
    # con la mas reciente y no mostrar la vieja como una "sesion fantasma".
    jq -n \
        --arg session_id "$SESSION_ID" \
        --arg ctx "$CTX_PCT" \
        --arg session_dir "$(basename "$(pwd)")" \
        --arg cwd "$(pwd)" \
        --arg title "$TITLE" \
        --arg updated "$(date '+%Y-%m-%d %H:%M')" \
        --argjson updated_epoch "$NOW_EPOCH" \
        --argjson pid "$PPID" \
        '{
            session_id: $session_id,
            context_pct: (if $ctx == "" then null else ($ctx | tonumber) end),
            session_dir: $session_dir,
            cwd: $cwd,
            title: (if $title == "" then null else $title end),
            updated_at: $updated,
            updated_epoch: $updated_epoch,
            pid: $pid
        }' > "$CACHE_DIR/$SESSION_ID.json" 2>/dev/null

    # Poda entradas viejas (sesiones cerradas hace mas de 2 dias) para que el
    # directorio no crezca sin limite.
    find "$CACHE_DIR" -name '*.json' -mtime +2 -delete 2>/dev/null
fi
