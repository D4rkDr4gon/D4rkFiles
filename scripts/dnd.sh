#!/usr/bin/env bash
# dnd.sh — No Molestar de dunst (backend, sin menú propio).
# Toggle global, temporizador con auto-desactivación, y silenciar apps
# específicas (skip_display) sin tocar el resto de las notificaciones.
# La interfaz es Settings → Notifications (tools/settings/settings_tui.py);
# sin argumentos abre esa sección. Antes era dnd-menu.sh (menús de rofi).
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
        echo "# Generado por scripts/dnd.sh — no editar a mano."
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
    # Refresca al instante el módulo custom/dnd de waybar ("signal": 9).
    pkill -RTMIN+9 -x waybar 2>/dev/null
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


sanitize_name() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | sed 's/_\+/_/g; s/^_//; s/_$//'
}

regenerate_rules() { write_dropin; }


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



if [ "$1" = "--disable-dnd" ]; then
    # set_dnd primero: cancel_timer para la propia unidad systemd que corre
    # este proceso, no queremos que nos mate antes de terminar el trabajo.
    set_dnd false
    rm -f "$TIMER_STATE"
    exit 0
fi

if [ "$1" = "--toggle" ]; then
    # Click en el módulo custom/dnd de waybar.
    toggle_global
    exit 0
fi

# Subcomandos (los usa Settings → Notifications, tools/settings).
case "${1:-}" in
    --status)
        # {"active": bool, "remaining": "1h 5m"|"", "apps": [{"app", "enabled"}]}
        active=false; is_dnd_active && active=true
        while IFS=$'\t' read -r enabled app; do
            [ -z "$app" ] && continue
            printf '%s\t%s\n' "$enabled" "$app"
        done <"$STATE_LIST" \
            | jq -R -s --argjson active "$active" --arg rem "$(timer_remaining)" '
                {active: $active, remaining: $rem,
                 apps: (split("\n") | map(select(length > 0) | split("\t")
                        | {app: .[1], enabled: (.[0] == "1")}))}'
        exit 0 ;;
    --on)  set_dnd true; exit 0 ;;
    --off) cancel_timer; set_dnd false; exit 0 ;;
    --timer)
        [[ "${2:-}" =~ ^[0-9]+$ ]] || { echo "Uso: $(basename "$0") --timer <segundos>" >&2; exit 2; }
        set_dnd true; start_timer "$2"; exit 0 ;;
    --app-toggle)
        [ -n "${2:-}" ] || exit 2
        toggle_app "$2"; exit 0 ;;
    --app-add)
        app="${2//\"/}"; [ -n "$app" ] || exit 2
        grep -qP "\t\Q$app\E\$" "$STATE_LIST" 2>/dev/null || printf '1\t%s\n' "$app" >>"$STATE_LIST"
        regenerate_rules; exit 0 ;;
esac

# Sin argumentos (clic derecho en el módulo de waybar): Settings → Notifications
exec bash "$HOME/.config/waybar/scripts/center-tui-launch.sh" settings 'Settings' \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/settings/settings_tui.py" --section notifications
