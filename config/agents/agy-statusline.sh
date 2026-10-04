#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# agy-statusline.sh — statusLine de Antigravity CLI (agy)
# Igual que claude/statusline-command.sh para Claude Code: agy le pasa por
# stdin un JSON con el estado (context_window, quota por modelo, model,
# workspace…) cada vez que cambia el agente. Este script:
#   1) guarda ese JSON en ~/.cache/agents/agy/<conversation_id>.json junto
#      con el PID del proceso agy (lo lee tools/agents_tui.py), y
#   2) imprime una línea corta: modelo · contexto · cuota.
#
# Activarlo (cuando agy esté instalado), en ~/.gemini/antigravity-cli/settings.json:
#   "statusLine": { "type": "command",
#                   "command": "bash ~/.local/share/dotfiles/config/agents/agy-statusline.sh" }
# Referencia: https://antigravity.google/docs/cli/statusline/
# ──────────────────────────────────────────────────────────
input="$(cat)"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/agents/agy"
mkdir -p "$CACHE_DIR"

# PID del proceso agy dueño de la sesión ($PPID es un sh -c de vida corta)
AGY_PID="$PPID"
p=$$
while [ "${p:-0}" -gt 1 ]; do
    if [ "$(cat "/proc/$p/comm" 2>/dev/null)" = agy ]; then AGY_PID=$p; break; fi
    p=$(awk '/^PPid:/ {print $2}' "/proc/$p/status" 2>/dev/null)
done

id=$(jq -r '.conversation_id // .session_id // "default"' <<<"$input" 2>/dev/null)
jq -c --argjson pid "$AGY_PID" --argjson now "$(date +%s)" \
    '{pid: $pid, updated_epoch: $now, payload: .}' <<<"$input" > "$CACHE_DIR/${id//\//_}.json" 2>/dev/null

# Poda: conversaciones sin actualizar en más de 2 días
find "$CACHE_DIR" -name '*.json' -mtime +2 -delete 2>/dev/null

jq -r '
    [ (.model.display_name // empty),
      (if .context_window.used_percentage != null
         then "ctx \(.context_window.used_percentage | floor)%" else empty end),
      ((.quota // {}) | to_entries | map("\(.key) \(((1 - .value.remaining_fraction) * 100) | floor)%")
         | join(" · ") | select(length > 0)) ]
    | join(" | ")' <<<"$input" 2>/dev/null
