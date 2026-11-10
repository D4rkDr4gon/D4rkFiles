#!/usr/bin/env bash
# gui-dispatch.sh <clase> — ¿esta herramienta se abre como GUI?
# Lo llaman los lanzadores de TUIs antes de abrir kitty:
#     gui-dispatch.sh "$CLASS" && exit 0
# Sale 0 si la abrió (o la cerró: toggle) en la GUI de Quickshell, y 1 si el
# lanzador tiene que seguir con la TUI de siempre. Cae a la TUI si:
#   - el modo no es gui (scripts/ui-mode.sh),
#   - la clase no está en tools/gui/registry.conf (todavía no tiene GUI),
#   - Quickshell no está instalado o el daemon no responde.
# Así un atajo nunca queda muerto. Con GUI_DISPATCH_DRY=1 imprime el comando y
# no ejecuta nada (pruebas).
class="${1:-}"; shift
# Settings con --section <id> en la línea de comandos: abre esa sección en la GUI
# --drawer: lo abrió un clic en waybar (float-tui-launch.sh) → cajón que sale de la barra
section=""; drawer=""
while [ $# -gt 0 ]; do
    case "$1" in --section) section="${2:-}" ;; --drawer) drawer=1 ;; esac
    shift
done
[ -n "$class" ] || exit 1
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# GUI_FORCE_TUI=1: la GUI abre la versión TUI de una sección (si no, sería un bucle)
[ -z "${GUI_FORCE_TUI:-}" ] || exit 1
[ "$("$here/ui-mode.sh")" = gui ] || exit 1

registry="${GUI_REGISTRY:-$here/../tools/gui/registry.conf}"
[ -r "$registry" ] || exit 1
target=$(awk -F'|' -v c="$class" '$0 !~ /^[[:space:]]*(#|$)/ && $1 == c { print $2; exit }' "$registry")
[ -n "$target" ] || exit 1

# target "exec:<comando>": en modo gui la clase abre una app externa (ej. Spotify oficial)
if [[ "$target" == exec:* ]]; then
    cmd="${target#exec:}"
    if [ -n "${GUI_DISPATCH_DRY:-}" ]; then echo "$cmd"; exit 0; fi
    command -v "${cmd%% *}" >/dev/null 2>&1 || exit 1
    setsid -f $cmd >/dev/null 2>&1
    exit 0
fi

cfg="${GUI_QS_PATH:-$here/../config/quickshell}"

# Cajón: x del cursor en el monitor con foco si el clic fue sobre la barra (zona reservada
# de arriba); si vino de un atajo de teclado, "right" (contra el borde derecho, como los popups TUI).
# Llamada IPC: drop <x|right> <alto de la barra>
drop_args() {
    local cur mon
    cur=$(hyprctl cursorpos -j 2>/dev/null) || cur=""
    mon=$(hyprctl monitors -j 2>/dev/null | jq -c '[.[] | select(.focused)][0] // empty' 2>/dev/null)
    if [ -z "$cur" ] || [ -z "$mon" ]; then echo "right 28"; return; fi
    jq -rn --argjson c "$cur" --argjson m "$mon" '
        ($m.reserved[1] // 28) as $bar
        | (($c.x - $m.x) / ($m.scale // 1) | floor) as $x
        | (($c.y - $m.y) / ($m.scale // 1)) as $y
        | (if $bar > 0 and $y >= 0 and $y <= $bar + 4 then ($x | tostring) else "right" end) + " " + (($bar | if . > 0 then . else 28 end) | tostring)'
}
if [ -n "${GUI_DISPATCH_DRY:-}" ]; then
    if [ -n "$section" ] && [ "$class" = settings ]; then echo "qs -p $cfg ipc call settings open $section"
    elif [ -n "$drawer" ]; then echo "qs -p $cfg ipc call $target drop $(drop_args)"
    else echo "qs -p $cfg ipc call $target toggle"; fi
    exit 0
fi
command -v qs >/dev/null 2>&1 || exit 1
# qs sale 0 aunque el daemon no haya atendido el pedido ("Not ready to accept queries yet." si
# quedó trabado tras recargar la config, o sin instancia): en esos casos, a la TUI.
qs_call() {
    local out
    out=$(qs -p "$cfg" ipc call "$@" 2>&1) || return 1
    case "$out" in *"Not ready"*|*"No running instances"*|*"not found"*|*"rror"*) return 1 ;; esac
    return 0
}
if [ -n "$section" ] && [ "$class" = settings ]; then
    qs_call settings open "$section"
elif [ -n "$drawer" ]; then
    # shellcheck disable=SC2046  # x y alto van como dos argumentos
    qs_call "$target" drop $(drop_args)
else
    qs_call "$target" toggle
fi
