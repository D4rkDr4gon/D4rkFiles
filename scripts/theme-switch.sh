#!/usr/bin/env bash
# theme-switch.sh — aplica un tema a todo el escritorio.
#
# Lee themes/<tema>/theme.json, calcula los tokens y renderiza las plantillas
# *.tpl del repo (ver scripts/lib/theme.sh). No edita archivos versionados.

set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
DOTFILES_DIR="$(cd -P "$(dirname "$SELF")/.." && pwd)"
export DOTFILES_DIR
# shellcheck source=lib/env.sh
source "$DOTFILES_DIR/scripts/lib/env.sh"
# shellcheck source=lib/theme.sh
source "$DOTFILES_DIR/scripts/lib/theme.sh"

usage() {
    cat <<EOF
Uso: theme [opciones] [tema]

  theme                     Lista los temas disponibles
  theme <nombre>            Aplica un tema (ej.: theme nord)
  theme --current           Muestra el tema activo

Opciones:
  --render-only             Renderiza plantillas y archivos de tema, sin recargar
                            componentes ni tocar el wallpaper (lo usa install.sh)
  --restart-firefox         Cierra y reabre Firefox para que tome userChrome.css
  -h, --help                Esta ayuda
EOF
}

list_themes() {
    local d name display current=""
    [[ -f "$CURRENT_THEME_FILE" ]] && current="$(jq -r '.name // empty' "$CURRENT_THEME_FILE" 2>/dev/null || true)"
    echo "Temas disponibles:"
    for d in "$THEMES_DIR"/*/; do
        [[ -f "$d/theme.json" ]] || continue
        name="$(basename "$d")"
        display="$(jq -r '.name' "$d/theme.json")"
        printf '  %-18s %s%s\n' "$name" "$display" "$([[ "$display" == "$current" ]] && echo '  (activo)')"
    done
}

check_deps() {
    command -v jq >/dev/null 2>&1 || { echo "Error: jq no está instalado" >&2; exit 1; }
}

# Un solo punto para el wallpaper: hyprpaper (Hyprland), feh (X11) o Qtile.
set_wallpaper() {
    local wp="${TOK[wallpaper]:-}"
    if [[ -z "$wp" ]]; then
        echo "  ⚠ wallpaper '$(jq -r '.wallpaper' "$THEME_JSON")' no encontrado (buscado en: $WALLPAPER_DIRS)" >&2
        return 0
    fi
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
        if ! pgrep -x hyprpaper >/dev/null 2>&1; then
            setsid -f hyprpaper >/dev/null 2>&1 || true
            sleep 0.5
        fi
        hyprctl hyprpaper wallpaper ",$wp" >/dev/null 2>&1 || true
    elif [[ "${XDG_SESSION_TYPE:-}" != "wayland" ]] && command -v feh >/dev/null 2>&1; then
        feh --bg-fill "$wp" 2>/dev/null || true
    elif pgrep -x qtile >/dev/null 2>&1; then
        local s
        for s in 0 1; do
            qtile cmd-obj -o screen "$s" -f set_wallpaper -a "$wp" -a fill 2>/dev/null || true
        done
    fi
}

reload_components() {
    command -v herdr >/dev/null 2>&1 && { herdr server reload-config >/dev/null 2>&1 || true; }
    command -v dunstctl >/dev/null 2>&1 && { dunstctl reload >/dev/null 2>&1 || true; }

    # swayosd-server no relee su CSS en caliente.
    if pgrep -x swayosd-server >/dev/null 2>&1; then
        pkill -x swayosd-server || true
        setsid -f swayosd-server >/dev/null 2>&1 || true
    fi

    [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && { hyprctl reload >/dev/null 2>&1 || true; }

    if command -v kitty >/dev/null 2>&1 && [[ -f "$DOTFILES_CONFIG/kitty/colors.conf" ]]; then
        kitty @ set-colors --all -c "$DOTFILES_CONFIG/kitty/colors.conf" 2>/dev/null || true
    fi

    if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
        bash "$DOTFILES_CONFIG/waybar/launch.sh" >/dev/null 2>&1 || true
    else
        bash "$DOTFILES_CONFIG/polybar/launch.sh" >/dev/null 2>&1 || true
    fi

    if pgrep -x cliamp >/dev/null 2>&1; then
        cliamp theme dotfiles >/dev/null 2>&1 || true
    fi
}

# Firefox solo lee userChrome/userContent al arrancar: cierre limpio + reapertura.
restart_firefox() {
    if ! pgrep -x firefox >/dev/null 2>&1; then
        echo "  → firefox no está abierto, nada que reiniciar"
        return 0
    fi
    local ws=""
    if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
        ws=$(hyprctl clients -j 2>/dev/null | jq -r \
            '[.[] | select(.class | test("^firefox$"; "i")) | .workspace.id] | unique | if length == 1 then .[0] else empty end' \
            2>/dev/null || true)
    fi
    pkill -TERM -x firefox || true
    local _
    for _ in $(seq 1 75); do
        pgrep -x firefox >/dev/null 2>&1 || break
        sleep 0.2
    done
    if pgrep -x firefox >/dev/null 2>&1; then
        echo "  ⚠ Firefox no cerró a tiempo, no se reabre (cerralo a mano)"
        return 0
    fi
    if [[ -n "$ws" ]]; then
        hyprctl dispatch exec "[workspace $ws silent] firefox" >/dev/null 2>&1 || true
    else
        setsid -f firefox >/dev/null 2>&1 || true
    fi
    echo "  → firefox reiniciado"
}

apply_theme() {
    local name="$1" render_only="$2" restart_ff="$3"
    local dir="$THEMES_DIR/$name"

    [[ -f "$dir/theme.json" ]] || {
        echo "Error: tema '$name' no encontrado (theme --list)" >&2
        exit 1
    }
    THEME_JSON="$dir/theme.json"

    theme_load_tokens "$THEME_JSON"
    theme_load_user_tokens

    echo "Aplicando tema: ${TOK[name]:-$name}"
    render_all_templates
    write_current_theme "$THEME_JSON"
    apply_external_themes
    apply_sddm_theme

    if [[ "$render_only" == false ]]; then
        set_wallpaper
        reload_components
        [[ "$restart_ff" == true ]] && restart_firefox
        notify-send "Tema aplicado" "${TOK[name]:-$name}" -i dialog-information 2>/dev/null || true
    fi
    echo "✓ Tema '$name' aplicado"
}

main() {
    local render_only=false restart_ff=false theme="" arg
    for arg in "$@"; do
        case "$arg" in
            -h|--help)         usage; exit 0 ;;
            --list)            check_deps; list_themes; exit 0 ;;
            --current)         [[ -f "$CURRENT_THEME_FILE" ]] && jq -r '.name' "$CURRENT_THEME_FILE" || echo "(ninguno)"; exit 0 ;;
            --render-only)     render_only=true ;;
            --restart-firefox) restart_ff=true ;;
            -*)                echo "Opción desconocida: $arg" >&2; usage >&2; exit 2 ;;
            *)                 [[ -z "$theme" ]] && theme="$arg" ;;
        esac
    done

    check_deps
    if [[ -z "$theme" ]]; then
        list_themes
        exit 0
    fi
    apply_theme "$theme" "$render_only" "$restart_ff"
}

main "$@"
