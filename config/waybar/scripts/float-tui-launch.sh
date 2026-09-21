#!/usr/bin/env bash
# Lanzador generico de TUIs como ventana flotante "popup", anclada arriba a
# la derecha del monitor con foco (float + pin + opacidad, posicionamiento
# dinamico multi-monitor, toggle abrir/enfocar/cerrar).
#
# Uso: float-tui-launch.sh <class> <titulo> <cols> <rows> <comando...>
#
# <class>   wm_class que se le pone a la ventana de Kitty (tiene que
#           coincidir con el windowrule en hypr/hyprland.conf: float on,
#           pin on, opacity ... para esa clase).
# <cols>/<rows>  tamaño del panel EN CELDAS (no en pixeles), para que kitty
#           calce con el contenido sin importar la fuente/DPI.
#
# Comportamiento (toggle, igual para todos los widgets que usan este script):
#   - no existe la ventana      -> la abre y la posiciona
#   - existe y esta enfocada    -> la cierra
#   - existe pero sin foco      -> la trae al frente

CLASS="$1"; shift
TITLE="$1"; shift
COLS="$1"; shift
ROWS="$1"; shift

MARGIN_RIGHT=16
MARGIN_TOP=44

EXISTING=$(hyprctl clients -j 2>/dev/null | jq -r --arg c "$CLASS" '[.[] | select(.class==$c)][0].address // empty')

if [ -n "$EXISTING" ]; then
    ACTIVE=$(hyprctl activewindow -j 2>/dev/null | jq -r '.address // empty')
    if [ "$EXISTING" = "$ACTIVE" ]; then
        hyprctl dispatch closewindow "address:$EXISTING" >/dev/null 2>&1
    else
        hyprctl dispatch focuswindow "address:$EXISTING" >/dev/null 2>&1
    fi
    exit 0
fi

kitty --class "$CLASS" --title "$TITLE" \
    -o "initial_window_width=${COLS}c" \
    -o "initial_window_height=${ROWS}c" \
    -o "remember_window_size=no" \
    -e "$@" &

# Hyprland aplica sus reglas (float/pin) y su centrado por defecto de forma
# asincrona al mapear la ventana; si posicionamos apenas la detectamos ese
# centrado puede pisar nuestro movimiento, asi que se reintenta un par de
# veces mas para ganarle esa carrera.
place_top_right() {
    local info win_w mon_id mon mon_x mon_y mon_w x y
    info=$(hyprctl clients -j 2>/dev/null | jq -c --arg c "$CLASS" '[.[] | select(.class==$c)][0] // empty')
    [ -z "$info" ] && return 1

    win_w=$(echo "$info" | jq -r '.size[0]')
    mon_id=$(echo "$info" | jq -r '.monitor')
    mon=$(hyprctl monitors -j 2>/dev/null | jq -c --argjson id "$mon_id" '.[] | select(.id == $id)')
    mon_x=$(echo "$mon" | jq -r '.x')
    mon_y=$(echo "$mon" | jq -r '.y')
    mon_w=$(echo "$mon" | jq -r '(.width / .scale) | floor')

    x=$((mon_x + mon_w - win_w - MARGIN_RIGHT))
    y=$((mon_y + MARGIN_TOP))

    hyprctl dispatch movewindowpixel "exact $x $y,class:^($CLASS)\$" >/dev/null 2>&1
}

FOUND=""
for _ in $(seq 1 40); do
    sleep 0.05
    if hyprctl clients -j 2>/dev/null | jq -e --arg c "$CLASS" '[.[] | select(.class==$c)] | length > 0' >/dev/null 2>&1; then
        FOUND=1
        break
    fi
done
[ -z "$FOUND" ] && exit 0

place_top_right
sleep 0.12
place_top_right
sleep 0.12
place_top_right
