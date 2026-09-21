#!/usr/bin/env bash
# Modulo waybar: estado rapido de uso de la suscripcion de Claude.
# Lee el cache que escribe ~/.claude/statusline-command.sh en cada sesion.

CACHE="$HOME/.claude/usage-cache.json"
ICON="󰚩"

FIVE=""
SEVEN=""
UPDATED=""
if [ -f "$CACHE" ]; then
    FIVE=$(jq -r '.five_hour_pct // empty' "$CACHE" 2>/dev/null)
    SEVEN=$(jq -r '.seven_day_pct // empty' "$CACHE" 2>/dev/null)
    UPDATED=$(jq -r '.updated_at // empty' "$CACHE" 2>/dev/null)
fi

if [ -n "$FIVE" ]; then
    PCT=$(printf '%.0f' "$FIVE")
    TEXT="${ICON} ${PCT}%"
    if [ "$PCT" -ge 80 ] 2>/dev/null; then
        CLASS="critical"
    elif [ "$PCT" -ge 50 ] 2>/dev/null; then
        CLASS="warning"
    else
        CLASS="normal"
    fi
else
    TEXT="$ICON"
    CLASS="normal"
fi

SEVEN_FMT="${SEVEN:-—}"
[ -n "$SEVEN" ] && SEVEN_FMT="$(printf '%.0f' "$SEVEN")"
UPDATED_FMT="${UPDATED:-sin datos aun}"

TOOLTIP="Agentes IA\n5h: ${FIVE:-—}%  ·  7d: ${SEVEN_FMT}%\nActualizado: ${UPDATED_FMT}\nClick para gestionar agentes"

jq -nc --arg text "$TEXT" --arg tooltip "$TOOLTIP" --arg class "$CLASS" \
    '{text: $text, tooltip: $tooltip, class: $class}'
