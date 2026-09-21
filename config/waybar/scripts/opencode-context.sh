#!/usr/bin/env bash
# Detecta las TUIs de opencode abiertas ahora mismo y calcula el % de
# contexto usado en la sesion activa de cada una, leyendo directamente el
# storage local de opencode (no hay hook de statusline como en Claude Code).
#
# Salida: un array JSON en stdout, uno por agente detectado:
#   [{"label": "...", "pct": 12, "detail": "..."}, ...]
# "label" es el nombre real de la sesion (el mismo que se ve en el selector
# de sesiones de opencode: .title, o .slug si todavia no tiene titulo).
# "detail" es la carpeta del proyecto (+ el modelo, si se pudo calcular el %).
# Si no hay ninguna TUI de opencode corriendo, imprime "[]".
#
# Heuristica de deteccion (no hay una API "que sesion esta abierta ahora"):
#   1) Se buscan procesos `opencode` sin subcomando (TUI interactiva), no
#      `opencode serve|run|mcp|...` que son modos no interactivos.
#   2) Para cada proceso se lee su cwd via /proc/<pid>/cwd.
#   3) De todas las sesiones guardadas en storage/session, se toma la mas
#      reciente cuyo campo "directory" matchee ese cwd -> es, con altisima
#      probabilidad, la sesion abierta en esa TUI (solo ese proceso la toca).
#   4) Del ultimo mensaje "assistant" de esa sesion se leen los tokens
#      (input + output + cache.read + cache.write) y se comparan contra el
#      limite de contexto del modelo (cache local de models.dev).
#
# Usado por waybar/scripts/claude-agents-tui.sh.

STORAGE="$HOME/.local/share/opencode/storage"
MODELS_CACHE="$HOME/.cache/opencode/models.json"

# Subcomandos no interactivos de `opencode` a ignorar (solo nos interesa la
# TUI: `opencode` o `opencode <path>`).
NON_TUI_RE='(^| )(serve|run|mcp|acp|web|session|stats|export|import|github|pr|models|providers|auth|agent|plugin|plug|db|upgrade|uninstall|completion|debug|attach)( |$)'

command -v jq >/dev/null 2>&1 || { echo '[]'; exit 0; }
[ -d "$STORAGE/session" ] || { echo '[]'; exit 0; }

entries=()

for pid in $(pgrep -x opencode 2>/dev/null); do
    [ -r "/proc/$pid/cmdline" ] || continue
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
    # cmdline[0] es el binario; miramos el resto de argv en busca de un subcomando.
    args="${cmdline#* }"
    [ "$args" = "$cmdline" ] && args=""
    if printf '%s' " $args " | grep -qE "$NON_TUI_RE"; then
        continue
    fi

    cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null)
    [ -z "$cwd" ] && continue

    session=$(jq -s --arg cwd "$cwd" '
        map(select(.directory == $cwd))
        | sort_by(.time.updated)
        | last // empty
    ' "$STORAGE"/session/*/*.json 2>/dev/null)
    [ -z "$session" ] || [ "$session" = "null" ] && continue

    sid=$(echo "$session" | jq -r '.id')
    dirname=$(echo "$session" | jq -r '(.directory | split("/") | last) // "opencode"')
    # Titulo real de la sesion (igual al que se ve en el selector de
    # sesiones de opencode); si todavia no tiene uno se cae al slug y
    # despues al nombre de carpeta.
    label=$(echo "$session" | jq -r '.title // .slug // empty')
    [ -z "$label" ] || [ "$label" = "null" ] && label="$dirname"

    msg_dir="$STORAGE/message/$sid"
    pct=""
    detail="$dirname"
    if [ -d "$msg_dir" ] && [ -n "$(ls -A "$msg_dir" 2>/dev/null)" ]; then
        lastmsg=$(jq -s '
            map(select(.role == "assistant" and .tokens != null))
            | sort_by(.time.completed // .time.created // 0)
            | last // empty
        ' "$msg_dir"/*.json 2>/dev/null)
        if [ -n "$lastmsg" ] && [ "$lastmsg" != "null" ]; then
            provider=$(echo "$lastmsg" | jq -r '.providerID // empty')
            model=$(echo "$lastmsg" | jq -r '.modelID // empty')
            total=$(echo "$lastmsg" | jq -r '
                (.tokens.input // 0) + (.tokens.output // 0)
                + (.tokens.cache.read // 0) + (.tokens.cache.write // 0)
            ')
            limit=""
            if [ -f "$MODELS_CACHE" ] && [ -n "$provider" ] && [ -n "$model" ]; then
                limit=$(jq -r --arg p "$provider" --arg m "$model" \
                    '.[$p].models[$m].limit.context // empty' "$MODELS_CACHE" 2>/dev/null)
            fi
            if [ -n "$limit" ] && [ "$limit" -gt 0 ] 2>/dev/null; then
                pct=$(awk -v t="$total" -v l="$limit" 'BEGIN{p=(t/l)*100; if (p>100) p=100; printf "%.0f", p}')
                [ -n "$model" ] && detail="$dirname · $model"
            fi
        fi
    fi

    entries+=("$(jq -n --arg label "$label" \
        --arg pct "$pct" --arg detail "$detail" \
        '{label: $label,
          pct: (if $pct == "" then null else ($pct | tonumber) end),
          detail: (if $detail == "" then null else $detail end)}')")
done

if [ "${#entries[@]}" -eq 0 ]; then
    echo '[]'
else
    printf '%s\n' "${entries[@]}" | jq -s '.'
fi
