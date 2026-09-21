#!/usr/bin/env bash
# env.sh — entorno común de los scripts del repo. Se hace `source`, no se ejecuta.
#
# Resuelve, sin asumir usuario ni ruta de clone:
#   DOTFILES_DIR         raíz del repo (readlink -f de este archivo)
#   DOTFILES_CONF_DIR    ~/.config/dotfiles      (config del usuario, fuera del repo)
#   DOTFILES_STATE_DIR   ~/.local/state/dotfiles (backups, logs)
#   DOTFILES_DATA_DIR    ~/.local/share/dotfiles (symlink estable al repo)
#   DOTFILES_CONFIG      $DOTFILES_DIR/config    (origen de ~/.config/<app>)
# y carga ~/.config/dotfiles/user.conf (KEY=VALUE) aplicando defaults autodetectados.

[[ -n "${_DF_ENV_LOADED:-}" ]] && return 0
_DF_ENV_LOADED=1

if [[ -z "${DOTFILES_DIR:-}" ]]; then
    _df_self="$(readlink -f "${BASH_SOURCE[0]}")"
    DOTFILES_DIR="$(cd -P "$(dirname "$_df_self")/../.." && pwd)"
    unset _df_self
fi
export DOTFILES_DIR

: "${XDG_CONFIG_HOME:=$HOME/.config}"
: "${XDG_DATA_HOME:=$HOME/.local/share}"
: "${XDG_STATE_HOME:=$HOME/.local/state}"

DOTFILES_CONF_DIR="$XDG_CONFIG_HOME/dotfiles"
DOTFILES_STATE_DIR="$XDG_STATE_HOME/dotfiles"
DOTFILES_DATA_DIR="$XDG_DATA_HOME/dotfiles"
DOTFILES_CONFIG="$DOTFILES_DIR/config"
DOTFILES_USER_CONF="$DOTFILES_CONF_DIR/user.conf"
export DOTFILES_CONF_DIR DOTFILES_STATE_DIR DOTFILES_DATA_DIR DOTFILES_CONFIG DOTFILES_USER_CONF

# Primer comando de la lista que exista en el PATH (imprime su nombre).
df_first_cmd() {
    local c
    for c in "$@"; do
        if command -v "$c" >/dev/null 2>&1; then
            printf '%s' "$c"
            return 0
        fi
    done
    return 1
}

# Distribución de teclado: X11 (localectl) -> consola (vconsole.conf) -> us.
df_detect_kb_layout() {
    local l=""
    if command -v localectl >/dev/null 2>&1; then
        l="$(localectl status 2>/dev/null | awk -F': *' '/X11 Layout/{print $2; exit}')"
    fi
    if [[ -z "$l" && -r /etc/vconsole.conf ]]; then
        l="$(awk -F= '/^KEYMAP=/{print $2; exit}' /etc/vconsole.conf | tr -d '"')"
    fi
    # vconsole usa nombres como "la-latin1"/"es"; xkb usa "latam"/"es".
    case "$l" in
        la-latin1|latam*) l="latam" ;;
    esac
    printf '%s' "${l:-us}"
}

# Batería: primera BAT* de /sys/class/power_supply (vacío si es un desktop).
df_detect_battery() {
    local b
    for b in /sys/class/power_supply/BAT*; do
        [[ -e "$b" ]] && { basename "$b"; return 0; }
    done
    return 1
}

# Interfaz Wi-Fi: la primera con soporte 802.11.
df_detect_wifi_iface() {
    local i
    for i in /sys/class/net/*/wireless; do
        [[ -e "$i" ]] && { basename "$(dirname "$i")"; return 0; }
    done
    return 1
}

# Nombre "humano" del usuario: GECOS, o el login si está vacío.
df_detect_display_name() {
    local n
    n="$(getent passwd "${USER:-$(id -un)}" 2>/dev/null | cut -d: -f5 | cut -d, -f1)"
    printf '%s' "${n:-${USER:-$(id -un)}}"
}

# Carga user.conf (si existe) y completa los defaults. No pisa lo ya exportado.
df_load_user_conf() {
    if [[ -r "$DOTFILES_USER_CONF" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$DOTFILES_USER_CONF"
        set +a
    fi

    : "${USER_DISPLAY_NAME:=$(df_detect_display_name)}"
    : "${USER_TITLE:=}"
    : "${TERMINAL:=$(df_first_cmd kitty alacritty foot wezterm konsole gnome-terminal xterm || echo kitty)}"
    : "${BROWSER:=$(df_first_cmd firefox chromium brave-browser google-chrome-stable librewolf || echo firefox)}"
    : "${FILE_MANAGER:=$(df_first_cmd thunar nautilus dolphin pcmanfm nemo || echo thunar)}"
    : "${EDITOR_GUI:=$(df_first_cmd subl code codium gedit kate || echo "$TERMINAL -e nvim")}"
    : "${KB_LAYOUT:=$(df_detect_kb_layout)}"
    : "${KB_VARIANT:=}"
    : "${DISPLAY_MANAGER:=sddm}"
    : "${DEFAULT_THEME:=nord}"
    : "${BANNER_ART_FILE:=}"
    : "${EXTRA_WALLPAPER_DIRS:=}"
    WALLPAPER_DIRS="${EXTRA_WALLPAPER_DIRS:+$EXTRA_WALLPAPER_DIRS:}$XDG_DATA_HOME/backgrounds:$DOTFILES_DIR/assets/wallpapers"
    export USER_DISPLAY_NAME USER_TITLE TERMINAL BROWSER FILE_MANAGER EDITOR_GUI \
           KB_LAYOUT KB_VARIANT DISPLAY_MANAGER DEFAULT_THEME BANNER_ART_FILE EXTRA_WALLPAPER_DIRS WALLPAPER_DIRS
}

# Busca un wallpaper por nombre en WALLPAPER_DIRS (o acepta una ruta absoluta).
df_resolve_wallpaper() {
    local name="$1" d
    [[ -z "$name" ]] && return 1
    if [[ "$name" = /* ]]; then
        [[ -f "$name" ]] && { printf '%s' "$name"; return 0; }
        return 1
    fi
    local IFS=:
    for d in $WALLPAPER_DIRS; do
        [[ -f "$d/$name" ]] && { printf '%s' "$d/$name"; return 0; }
    done
    return 1
}

# Banner de la pantalla de bloqueo, login (SDDM) y terminal: el arte del proyecto
# (assets/banner-art.txt, el DARKDRAGON) y una línea "Nombre - Título" entre barras.
# BANNER_ART_FILE en user.conf usa otro arte; "none" deja solo el nombre (con figlet,
# si está instalado). Imprime una línea por renglón.
df_banner() {
    local name="$USER_DISPLAY_NAME" text line width=0 i art_file
    local -a art=() out=()
    text="$name${USER_TITLE:+ - $USER_TITLE}"
    art_file="${BANNER_ART_FILE:-$DOTFILES_DIR/assets/banner-art.txt}"

    if [[ "$art_file" == none ]]; then
        if command -v figlet >/dev/null 2>&1; then
            while IFS= read -r line; do art+=("$line"); done < <(figlet -w 88 -f small -- "$name" 2>/dev/null | sed 's/[[:space:]]*$//')
        fi
    elif [[ -r "$art_file" ]]; then
        while IFS= read -r line; do art+=("$line"); done < "$art_file"
    fi

    width=$(( ${#text} + 20 ))
    for line in "${art[@]}"; do (( ${#line} > width )) && width=${#line}; done
    (( width < 40 )) && width=40

    local bar dash pad rest
    printf -v bar '%*s' "$width" ''; bar="${bar// /=}"
    # "----------- >>> texto <<< -----------" ocupando exactamente el ancho del arte
    rest=$(( width - ${#text} - 12 ))
    (( rest < 4 )) && rest=4
    pad=$(( (rest - 6) / 2 ))          # como el banner original: guiones más largos a la derecha
    (( pad < 2 )) && pad=2
    printf -v dash '%*s' "$pad" ''; dash="${dash// /-}"
    local dash2; printf -v dash2 '%*s' "$(( rest - pad ))" ''; dash2="${dash2// /-}"

    out+=("$bar")
    for line in "${art[@]}"; do out+=("$line"); done
    out+=("$dash  >>> $text <<<  $dash2")
    out+=("$bar")
    for i in "${!out[@]}"; do printf '%s\n' "${out[$i]}"; done
}

df_load_user_conf
