#!/usr/bin/env bash
# Lanzador genérico de TUIs como ventana flotante CENTRADA (tipo diálogo),
# a diferencia de float-tui-launch.sh, que ancla los popups de waybar arriba
# a la derecha. Tamaño y centrado los pone el windowrule de la clase en
# config/hypr/hyprland.conf (float on, center on, size W H, opacity 0.97).
#
# Uso: center-tui-launch.sh <class> <titulo> <comando...>
#
# Toggle: si la ventana ya está abierta y enfocada la cierra, si está abierta
# sin foco la trae al frente, si no la abre. En Qtile/X11 abre la kitty y
# config/qtile/modules/hooks.py (FLOAT_GEOMETRY con márgenes None) la centra.
CLASS="$1"; shift
TITLE="$1"; shift

if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
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
fi
exec kitty --class "$CLASS" --title "$TITLE" "$@"
