#!/usr/bin/env bash
# TUI de gestion de agentes IA (Claude Code / opencode) — dashboard con
# medidores de barras (estilo btop).
#
# Se lanza desde el modulo waybar "custom/claude-agents" dentro de una
# ventanita flotante de Kitty, anclada arriba a la derecha
# (ver qtile/modules/hooks.py: float_widgets).
#
# Regla "Flat Minimal" (ver docs/design-system.md): sin cajas ni marcos.
# Antes este panel se dibujaba entero a mano con box-drawing (┌─┐│└─┘) —
# ahora es texto plano jerárquico (título en negrita, filas ícono/label,
# un separador sutil de 1 línea) igual que el resto del sistema.

CACHE="$HOME/.claude/usage-cache.json"
CACHE_DIR="$HOME/.claude/usage-cache.d"          # una entrada por sesion de Claude Code
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCODE_SCRIPT="$SCRIPT_DIR/opencode-context.sh"
THEME_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/current_theme.json"
CW=88            # ancho de referencia para el separador y el padding de filas
BAR_BLOCKS=14    # largo de la barra de bloques (mas corta para dejarle sitio al nombre)
AGENT_LABEL_W=40 # ancho de la columna de nombre en las filas de agente
MAX_AGENTS=3      # filas maximas por seccion (claude code / opencode)
FRESH_SECONDS=1800 # una sesion de Claude Code sin refrescos en 30min se da por cerrada

# --- Colores del tema activo -----------------------------------------------
# Antes solo se leía .primary; ahora se lee la paleta completa para que
# estados/superficies también sigan al tema (no solo el acento).
PRIMARY="#c62828"; FOREGROUND="#c5c8c6"; CHIP_BATTERY="#1a1515"
STATUS_OK="#5cb85c"; STATUS_WARN="#f9a825"; STATUS_ERROR="#ff1744"
if [ -f "$THEME_FILE" ]; then
    P=$(jq -r '.primary // empty' "$THEME_FILE" 2>/dev/null); [ -n "$P" ] && PRIMARY="$P"
    F=$(jq -r '.foreground // empty' "$THEME_FILE" 2>/dev/null); [ -n "$F" ] && FOREGROUND="$F"
    CB=$(jq -r '.chip_battery // empty' "$THEME_FILE" 2>/dev/null); [ -n "$CB" ] && CHIP_BATTERY="$CB"
    SO=$(jq -r '.status_ok // empty' "$THEME_FILE" 2>/dev/null); [ -n "$SO" ] && STATUS_OK="$SO"
    SW=$(jq -r '.status_warn // empty' "$THEME_FILE" 2>/dev/null); [ -n "$SW" ] && STATUS_WARN="$SW"
    SE=$(jq -r '.status_error // empty' "$THEME_FILE" 2>/dev/null); [ -n "$SE" ] && STATUS_ERROR="$SE"
fi

hex_to_ansi() {
    local hex="${1#\#}"
    local r=$((16#${hex:0:2})) g=$((16#${hex:2:2})) b=$((16#${hex:4:2}))
    printf '\033[38;2;%d;%d;%dm' "$r" "$g" "$b"
}

# Nota: estas variables deben quedar con el byte ESC real (comillas $'...'),
# no con el texto literal "\033[..." — de lo contrario se ven como texto.
C_PRIMARY=$(hex_to_ansi "$PRIMARY")
C_FOREGROUND=$(hex_to_ansi "$FOREGROUND")
C_SURFACE=$(hex_to_ansi "$CHIP_BATTERY")
GREEN=$(hex_to_ansi "$STATUS_OK")
YELLOW=$(hex_to_ansi "$STATUS_WARN")
RED=$(hex_to_ansi "$STATUS_ERROR")
RESET=$'\033[0m'
BOLD=$'\033[1m'
DIM=$'\033[2m'

# Envuelve texto en un color y lo cierra con reset.
paint() { printf '%s%s%s' "$1" "$2" "$RESET"; }

color_for_pct() {
    local pct="$1"
    if [ -z "$pct" ]; then
        printf '%s' "$DIM"
    elif [ "$pct" -ge 80 ] 2>/dev/null; then
        printf '%s' "$RED"
    elif [ "$pct" -ge 50 ] 2>/dev/null; then
        printf '%s' "$YELLOW"
    else
        printf '%s' "$GREEN"
    fi
}

# Repite un caracter (soporta multibyte, a diferencia de `tr`).
repeat() { printf '%*s' "$1" '' | sed "s/ /$2/g"; }

# Fila de contenido con margen izquierdo fijo (sin bordes laterales).
row() { printf '  %s\n' "$1"; }

blank_row() { row ""; }

header() {
    printf '\n  %s\n\n' "$(paint "$BOLD$C_PRIMARY" "AGENTES IA")"
}

# Separador sutil de 1 línea — superficie tenue, no el acento del tema
# (regla Flat Minimal: el acento nunca es una línea decorativa suelta).
divider() {
    printf '  %s\n' "$(paint "$C_SURFACE" "$(repeat "$CW" '─')")"
}

# Medidor tipo btop: etiqueta + barra de bloques + porcentaje + detalle.
# $4 (opcional) = ancho de la columna de etiqueta, default 10 (para "5h"/"7d").
meter() {
    local label="$1" pct="$2" detail="$3"
    local blocks="$BAR_BLOCKS" filled empty pctfmt c bar lw="${4:-10}"

    # Las etiquetas mas largas que la columna se truncan para no romper el layout.
    if [ "${#label}" -gt "$lw" ]; then
        label="${label:0:$((lw - 1))}…"
    fi

    if [ -z "$pct" ]; then
        bar="$(paint "$DIM" "$(repeat "$blocks" '·')")"
        printf '%-*s %s   %s' "$lw" "$label" "$bar" "$(paint "$DIM" "sin datos")"
        return
    fi

    pctfmt=$(printf '%.0f' "$pct")
    filled=$((pctfmt * blocks / 100))
    [ "$filled" -gt "$blocks" ] && filled=$blocks
    empty=$((blocks - filled))
    c=$(color_for_pct "$pctfmt")
    bar="$(paint "$c" "$(repeat "$filled" '█')")$(paint "$DIM" "$(repeat "$empty" '░')")"

    printf '%-*s %s %s' "$lw" "$label" "$bar" "$(paint "$c" "$(printf '%3s%%' "$pctfmt")")"
    [ -n "$detail" ] && printf '  %s' "$(paint "$DIM" "$detail")"
}

# Cuanto hace de un timestamp unix, en formato corto ("hace 2m").
human_ago() {
    local delta="$1"
    if [ "$delta" -lt 60 ]; then
        printf 'hace %ss' "$delta"
    elif [ "$delta" -lt 3600 ]; then
        printf 'hace %sm' $((delta / 60))
    else
        printf 'hace %sh' $((delta / 3600))
    fi
}

# Lista las sesiones de Claude Code con actividad reciente (una TUI/panel
# por sesion, no solo la ultima con la que se interactuo). Cada linea
# escrita por statusline-command.sh en $CACHE_DIR se toma como "abierta" si:
#   1) el proceso $pid que la escribio sigue vivo (si se cerro la terminal,
#      la entrada desaparece al toque en vez de esperar $FRESH_SECONDS), y
#   2) es la entrada MAS RECIENTE de ese pid (un mismo proceso puede dejar
#      mas de un archivo si hizo /clear y arranco otra sesion — session_id
#      nuevo, mismo pid — asi que la vieja no se muestra como una charla
#      fantasma aparte), y
#   3) se actualizo hace menos de $FRESH_SECONDS.
# Salida: "titulo<TAB>pct<TAB>subtitulo" una por sesion, mas nueva primero.
# El "titulo" es el mismo nombre autogenerado que se ve en `claude --resume`
# (o el nombre de carpeta mientras Claude todavia no le puso titulo).
claude_code_agents() {
    [ -d "$CACHE_DIR" ] || return
    local now; now=$(date '+%s')
    local f raw deduped pid upd title pct dir

    raw=""
    for f in "$CACHE_DIR"/*.json; do
        [ -e "$f" ] || continue
        raw+=$(jq -r '
            select(.pid != null and .updated_epoch != null)
            | [.pid, .updated_epoch, (.title // .session_dir // "?"), (.context_pct // -1), (.session_dir // "?")] | @tsv
        ' "$f" 2>/dev/null)
        raw+=$'\n'
    done

    # pid asc, updated_epoch desc -> con "!seen[pid]++" nos quedamos con la
    # entrada mas nueva de cada pid y se descartan las demas.
    deduped=$(printf '%s' "$raw" | sort -t $'\t' -k1,1n -k2,2rn | awk -F'\t' 'NF && !seen[$1]++')

    printf '%s\n' "$deduped" | while IFS=$'\t' read -r pid upd title pct dir; do
        [ -z "$pid" ] && continue
        [ -d "/proc/$pid" ] || continue                       # proceso muerto -> afuera
        [ $((now - upd)) -le "$FRESH_SECONDS" ] || continue   # sin refrescos hace rato -> afuera
        printf '%s\t%s\t%s\t%s\n' "$upd" "$title" "$pct" "$dir"
    done | sort -t $'\t' -k1,1rn | while IFS=$'\t' read -r upd title pct dir; do
        # OJO: no convertir pct="-1" a "" aca. Un campo vacio entre dos tabs
        # se "come" al leerlo despues con `IFS=$'\t' read` (bash trata el
        # tab como IFS whitespace y colapsa campos vacios aunque IFS solo
        # tenga ese caracter) -> todo se corre una columna y pct termina
        # con el contenido de detail. Se resuelve a "" recien en agents_section.
        printf '%s\t%s\t%s · %s\n' "$title" "$pct" "$dir" "$(human_ago $((now - upd)))"
    done
}

# Lista las TUIs de opencode detectadas ahora mismo (ver opencode-context.sh).
# Salida: "titulo<TAB>pct<TAB>subtitulo" una por sesion.
opencode_agents() {
    [ -x "$OPENCODE_SCRIPT" ] || return
    "$OPENCODE_SCRIPT" 2>/dev/null | jq -r '
        .[] | [.label, (.pct // -1), (.detail // "")] | @tsv
    ' 2>/dev/null | while IFS=$'\t' read -r title pct detail; do
        # ver nota en claude_code_agents(): no vaciar pct aca, se resuelve
        # recien en agents_section() para no perder el campo al leerlo.
        printf '%s\t%s\t%s\n' "$title" "$pct" "$detail"
    done
}

# Dibuja una seccion de agentes: titulo + hasta $MAX_AGENTS medidores (una
# linea por agente: nombre de sesion + barra + %% + detalle) + "sin agentes
# abiertos" si no hay nada, o "+N mas" si se recorto la lista.
agents_section() {
    local title="$1" lines="$2"
    row "$(paint "$BOLD$C_FOREGROUND" "$title")"
    local total shown=0
    total=$(printf '%s\n' "$lines" | grep -c . || true)
    if [ "$total" -eq 0 ]; then
        row "$(paint "$DIM" "sin agentes abiertos")"
        return
    fi
    printf '%s\n' "$lines" | head -n "$MAX_AGENTS" | while IFS=$'\t' read -r label pct detail; do
        [ "$pct" = "-1" ] && pct=""
        row "$(meter "$label" "$pct" "$detail" "$AGENT_LABEL_W")"
    done
    shown=$((total < MAX_AGENTS ? total : MAX_AGENTS))
    [ "$total" -gt "$shown" ] && row "$(paint "$DIM" "+ $((total - shown)) mas")"
}

# $2 = "day" para agregar el dia (util para el reset semanal de 7d; el de
# 5h siempre cae en menos de un dia, no hace falta).
fmt_reset() {
    if [ "$2" = "day" ]; then
        date -d "@$1" '+%H:%M %a' 2>/dev/null
    else
        date -d "@$1" '+%H:%M' 2>/dev/null
    fi
}

# Boton estilo "chip" para el footer, ej: [c] claude code
button() {
    local key="$1" label="$2"
    printf '%s[%s]%s %s' "$DIM" "$(paint "$BOLD$C_PRIMARY" "$key")" "$DIM$RESET" "$label"
}

render() {
    local five seven five_reset seven_reset updated
    five=""; seven=""; five_reset=""; seven_reset=""; updated=""
    if [ -f "$CACHE" ]; then
        five=$(jq -r '.five_hour_pct // empty' "$CACHE" 2>/dev/null)
        seven=$(jq -r '.seven_day_pct // empty' "$CACHE" 2>/dev/null)
        five_reset=$(jq -r '.five_hour_reset // empty' "$CACHE" 2>/dev/null)
        seven_reset=$(jq -r '.seven_day_reset // empty' "$CACHE" 2>/dev/null)
        updated=$(jq -r '.updated_at // empty' "$CACHE" 2>/dev/null)
    fi

    local five_detail="" seven_detail=""
    [ -n "$five_reset" ] && five_detail="renueva $(fmt_reset "$five_reset")"
    [ -n "$seven_reset" ] && seven_detail="renueva $(fmt_reset "$seven_reset" day)"

    # Se resuelven antes de dibujar (evita golpear disco/procesos entre fila y fila).
    local cc_lines oc_lines
    cc_lines=$(claude_code_agents)
    oc_lines=$(opencode_agents)

    header
    row "$(paint "$BOLD$C_FOREGROUND" "suscripcion claude code")"
    row "$(meter "5h" "$five" "$five_detail" "$AGENT_LABEL_W")"
    row "$(meter "7d" "$seven" "$seven_detail" "$AGENT_LABEL_W")"
    blank_row
    agents_section "contexto · claude code" "$cc_lines"
    blank_row
    agents_section "contexto · opencode" "$oc_lines"
    blank_row
    if [ -n "$updated" ]; then
        row "$(paint "$DIM" "act. $updated")"
    else
        row "$(paint "$DIM" "sin datos aun — se registra al usar Claude Code")"
    fi
    divider
    row "$(button c 'claude code')  $(button o 'opencode')  $(button r 'refrescar')"
}

# Modo "medicion": imprime cuantas filas ocupa el contenido AHORA (segun
# cuantos agentes estan abiertos) sin dibujar nada — lo usa
# claude-agents-launch.sh para abrir la ventana del tamaño justo en vez de
# uno fijo pensado para el peor caso (que deja espacio vacio de mas cuando
# hay pocos agentes).
if [ "$1" = "--rows" ]; then
    render | wc -l
    exit 0
fi

cleanup() { printf '%s' "$RESET"; clear; }
trap cleanup EXIT

while true; do
    clear
    render
    IFS= read -rsn1 key
    case "$key" in
        c|C) exec claude ;;
        o|O) exec opencode ;;
        r|R) continue ;;
        q|Q|$'\e') exit 0 ;;
        *) continue ;;
    esac
done
