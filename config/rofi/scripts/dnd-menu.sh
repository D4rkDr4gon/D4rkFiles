#!/usr/bin/env bash
# Do Not Disturb manager - Dunst + Rofi
# Toggle global, temporizador con auto-desactivacion, y silenciar apps
# especificas (skip_display) sin tocar el resto de las notificaciones.

ROFI_THEME="$HOME/.config/rofi/theme.rasi"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles"
DROPIN="${XDG_CONFIG_HOME:-$HOME/.config}/dunst/dunstrc.d/50-dnd.conf"
STATE_LIST="$STATE_DIR/dunst-blocked-apps.conf"   # "<1|0>\t<app>" por línea
STATE_GLOBAL="$STATE_DIR/dunst-dnd-global"        # true | false
TIMER_STATE="${XDG_CACHE_HOME:-$HOME/.cache}/dunst-dnd-until"
TIMER_UNIT="dnd-timer"

mkdir -p "$STATE_DIR" "$(dirname "$DROPIN")"
touch "$STATE_LIST"
[ -f "$STATE_GLOBAL" ] || echo false > "$STATE_GLOBAL"

# Genera el drop-in completo (regla global + una regla por app) desde el estado.
# Sin sed sobre el dunstrc: el archivo se reescribe entero.
write_dropin() {
    local app sec enabled flag
    {
        echo "# Generado por dnd-menu.sh — no editar a mano."
        echo "[dnd_global]"
        echo "    enabled = $(cat "$STATE_GLOBAL")"
        echo "    skip_display = true"
        while IFS=$'\t' read -r enabled app; do
            [ -z "$app" ] && continue
            sec="block_$(sanitize_name "$app")"
            flag="false"; [ "$enabled" = "1" ] && flag="true"
            printf '\n[%s]\n    enabled = %s\n    appname = "%s"\n    skip_display = true\n' "$sec" "$flag" "$app"
        done <"$STATE_LIST"
    } >"$DROPIN"
    dunstctl reload &>/dev/null || true
}

is_dnd_active() { [ "$(cat "$STATE_GLOBAL")" = "true" ]; }

# Regla global sin filtros = matchea todas las notificaciones. skip_display
# las manda directo al historial (sin toast) en vez de encolarlas como hace
# dunstctl set-paused, que las muestra todas de golpe al reanudar.
set_dnd() {
    echo "$1" > "$STATE_GLOBAL"   # true|false
    write_dropin
}

cancel_timer() {
    systemctl --user stop "${TIMER_UNIT}.timer" "${TIMER_UNIT}.service" &>/dev/null
    rm -f "$TIMER_STATE"
}

SCRIPT_PATH="$(readlink -f "$0")"

start_timer() {
    local seconds="$1"
    cancel_timer
    systemd-run --user --unit="$TIMER_UNIT" --on-active="${seconds}s" \
        --timer-property=AccuracySec=1s \
        --description="Auto-desactivar No Molestar" \
        /usr/bin/bash "$SCRIPT_PATH" --disable-dnd &>/dev/null
    date -d "+${seconds} seconds" '+%s' > "$TIMER_STATE"
}

timer_remaining() {
    [ -f "$TIMER_STATE" ] || return
    local until now diff
    until=$(cat "$TIMER_STATE")
    now=$(date +%s)
    diff=$((until - now))
    if [ "$diff" -le 0 ]; then
        rm -f "$TIMER_STATE"
        return
    fi
    if [ "$diff" -ge 3600 ]; then
        printf '%dh %dm' $((diff / 3600)) $(((diff % 3600) / 60))
    else
        printf '%dm' $((diff / 60))
    fi
}

toggle_global() {
    if is_dnd_active; then
        cancel_timer
        set_dnd false
        notify-send "No Molestar" "Desactivado" -t 2000
    else
        set_dnd true
        notify-send "No Molestar" "Activado" -t 2000
    fi
}

show_timer_menu() {
    local choice
    choice=$(printf "1 hora\n2 horas\nHasta mañana (08:00)\nPersonalizado...\n←  Volver\n" \
        | rofi -dmenu -p "No Molestar por..." -theme "$ROFI_THEME")

    local seconds=""
    case "$choice" in
        "1 hora") seconds=3600 ;;
        "2 horas") seconds=7200 ;;
        "Hasta mañana (08:00)")
            local now target
            now=$(date +%s)
            target=$(date -d "08:00" +%s)
            [ "$target" -le "$now" ] && target=$(date -d "tomorrow 08:00" +%s)
            seconds=$((target - now))
            ;;
        "Personalizado...")
            local hours
            hours=$(rofi -dmenu -p "Horas de No Molestar" -theme "$ROFI_THEME" \
                -theme-str 'entry { placeholder: "Ej: 3"; }')
            [[ "$hours" =~ ^[0-9]+([.][0-9]+)?$ ]] || return
            seconds=$(awk -v h="$hours" 'BEGIN{printf "%d", h*3600}')
            ;;
        *) return ;;
    esac

    [ -z "$seconds" ] && return
    set_dnd true
    start_timer "$seconds"
    notify-send "No Molestar" "Activado por $(timer_remaining)" -t 2000
}

sanitize_name() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | sed 's/_\+/_/g; s/^_//; s/_$//'
}

regenerate_rules() { write_dropin; }

add_app() {
    local suggestions app
    suggestions=$(dunstctl history 2>/dev/null | jq -r '.data[][].appname.data' 2>/dev/null | sort -u)
    app=$(printf '%s\n' "$suggestions" | rofi -dmenu -p "Silenciar app" -theme "$ROFI_THEME" \
        -theme-str 'entry { placeholder: "Nombre de la app (ej: Discord)..."; }')
    [ -z "$app" ] && return
    app="${app//\"/}"

    if ! grep -qP "\t\Q$app\E\$" "$STATE_LIST" 2>/dev/null; then
        printf '1\t%s\n' "$app" >>"$STATE_LIST"
    fi
    regenerate_rules
}

toggle_app() {
    local target="$1" tmp
    tmp=$(mktemp)
    while IFS=$'\t' read -r enabled app; do
        [ -z "$app" ] && continue
        if [ "$app" = "$target" ]; then
            [ "$enabled" = "1" ] && enabled=0 || enabled=1
        fi
        printf '%s\t%s\n' "$enabled" "$app"
    done <"$STATE_LIST" >"$tmp"
    mv "$tmp" "$STATE_LIST"
    regenerate_rules
}

manage_apps() {
    while true; do
        local enabled_arr=() app_arr=() display_arr=()
        while IFS=$'\t' read -r enabled app; do
            [ -z "$app" ] && continue
            enabled_arr+=("$enabled")
            app_arr+=("$app")
            if [ "$enabled" = "1" ]; then
                display_arr+=("✓  $app")
            else
                display_arr+=("○  $app")
            fi
        done <"$STATE_LIST"

        local add_idx=${#display_arr[@]}
        display_arr+=("+  Silenciar nueva app")
        local back_idx=${#display_arr[@]}
        display_arr+=("←  Volver")

        local idx
        idx=$(printf '%s\n' "${display_arr[@]}" | rofi -dmenu -i -p "Apps silenciadas" \
            -theme "$ROFI_THEME" -no-custom -format i)
        [[ -z "$idx" || ! "$idx" =~ ^[0-9]+$ ]] && return

        if [ "$idx" -eq "$back_idx" ]; then
            return
        elif [ "$idx" -eq "$add_idx" ]; then
            add_app
        else
            toggle_app "${app_arr[$idx]}"
        fi
    done
}

main_menu() {
    while true; do
        local status_line rem
        if is_dnd_active; then
            rem=$(timer_remaining)
            if [ -n "$rem" ]; then
                status_line="Desactivar No Molestar (auto en $rem)"
            else
                status_line="Desactivar No Molestar"
            fi
        else
            status_line="Activar No Molestar"
        fi

        local choice
        choice=$(printf "%s\n⏱  Activar por tiempo...\n󱙃  Apps silenciadas...\n←  Volver\n" "$status_line" \
            | rofi -dmenu -p "No Molestar" -theme "$ROFI_THEME")

        case "$choice" in
            "$status_line") toggle_global ;;
            "⏱  Activar por tiempo...") show_timer_menu ;;
            "󱙃  Apps silenciadas...") manage_apps ;;
            *) return ;;
        esac
    done
}

if [ "$1" = "--disable-dnd" ]; then
    # set_dnd primero: cancel_timer para la propia unidad systemd que corre
    # este proceso, no queremos que nos mate antes de terminar el trabajo.
    set_dnd false
    rm -f "$TIMER_STATE"
    exit 0
fi

main_menu
