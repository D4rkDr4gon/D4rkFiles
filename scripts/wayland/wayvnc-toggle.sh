#!/usr/bin/env bash
# =============================================================================
# wayvnc-toggle.sh — Levanta/baja wayvnc bajo demanda para usar una tablet
#                     (o cualquier cliente VNC) como monitor secundario táctil.
# =============================================================================
# Uso:
#   wayvnc-toggle.sh init  -> crea ~/.config/dotfiles/wayvnc/config con usuario,
#                              password aleatoria y certificado TLS (una sola vez)
#   wayvnc-toggle.sh on    -> crea un output headless virtual extendido,
#                              lo pone a la derecha de los monitores físicos,
#                              arranca wayvnc bindeado a la IP de la LAN
#   wayvnc-toggle.sh off   -> mata wayvnc y destruye el output headless
#   wayvnc-toggle.sh status
#
# Requiere: wayvnc, hyprctl (Hyprland), openssl (solo para `init`)
#
# Variables (opcionales, ej. en ~/.config/dotfiles/user.conf):
#   VNC_RES=1920x1080   resolución del monitor virtual (ajustala a tu tablet)
#   VNC_PORT=5900
# =============================================================================
set -u

CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/wayvnc"
CONFIG="$CONF_DIR/config"   # contiene la password: fuera del repo, permisos 600
# shellcheck source=/dev/null
[ -r "${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/user.conf" ] && . "${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/user.conf"
PIDFILE="${XDG_RUNTIME_DIR:-/tmp}/wayvnc.pid"
LOGFILE="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/wayvnc.log"
OUTPUT_NAME="HEADLESS-1"   # nombre lógico que asigna Hyprland al crear el headless
RES="${VNC_RES:-1920x1080}"
PORT="${VNC_PORT:-5900}"
mkdir -p "$(dirname "$LOGFILE")"

get_lan_ip() {
    # Detecta automáticamente la interfaz de la ruta por defecto (ethernet o WiFi,
    # cualquiera sea su nombre: enp2s0, wlan0, etc.) en vez de asumir una fija.
    local iface
    iface=$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')
    [ -n "$iface" ] || return 1
    ip -4 -br addr show "$iface" 2>/dev/null | awk '{print $3}' | cut -d/ -f1
}

init() {
    if [ -e "$CONFIG" ]; then
        echo "Ya existe $CONFIG (no se sobrescribe). Borralo para regenerarlo." >&2
        return 1
    fi
    command -v openssl >/dev/null || { echo "ERROR: falta openssl" >&2; return 1; }
    local pass
    pass=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
    mkdir -p "$CONF_DIR" && chmod 700 "$CONF_DIR"
    openssl req -x509 -newkey rsa:4096 -nodes -days 3650 -subj "/CN=$(hostname)" \
        -keyout "$CONF_DIR/key.pem" -out "$CONF_DIR/cert.pem" >/dev/null 2>&1 || return 1
    chmod 600 "$CONF_DIR/key.pem"
    umask 077
    cat > "$CONFIG" <<EOF
enable_auth=true
username=$USER
password=$pass
private_key_file=$CONF_DIR/key.pem
certificate_file=$CONF_DIR/cert.pem
EOF
    echo "Config creada en $CONFIG"
    echo "Usuario: $USER | Password: $pass   (guardala; no se vuelve a mostrar)"
}

status() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "wayvnc activo (PID $(cat "$PIDFILE")) en $(get_lan_ip):$PORT"
        return 0
    else
        echo "wayvnc inactivo"
        return 1
    fi
}

start() {
    if status >/dev/null 2>&1; then
        echo "wayvnc ya está corriendo."
        status
        return 0
    fi

    local ip
    ip=$(get_lan_ip) || true
    if [ -z "$ip" ]; then
        echo "ERROR: no se detectó una IP en la ruta por defecto. ¿Estás conectado a la LAN/WiFi?" >&2
        return 1
    fi
    if [ ! -r "$CONFIG" ]; then
        echo "ERROR: falta $CONFIG. Creala con: $0 init" >&2
        return 1
    fi

    # Crear output headless dedicado (monitor extendido virtual para la tablet)
    if ! hyprctl monitors | grep -q "$OUTPUT_NAME"; then
        hyprctl output create headless "$OUTPUT_NAME" >/dev/null
        sleep 0.5
    fi
    # Setear resolución y posicionarlo a la derecha de los monitores existentes
    hyprctl keyword monitor "$OUTPUT_NAME,$RES@60,auto-right,1" >/dev/null

    echo "Iniciando wayvnc en $ip:$PORT (output $OUTPUT_NAME)..."
    nohup wayvnc -C "$CONFIG" -o "$OUTPUT_NAME" "$ip" "$PORT" \
        >>"$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1

    if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "wayvnc arriba. Conectate desde la tablet a: $ip:$PORT"
        echo "Usuario y password: ver $CONFIG"
    else
        echo "ERROR: wayvnc no arrancó, revisá $LOGFILE" >&2
        rm -f "$PIDFILE"
        return 1
    fi
}

stop() {
    if [ -f "$PIDFILE" ]; then
        kill "$(cat "$PIDFILE")" 2>/dev/null
        rm -f "$PIDFILE"
    else
        pkill -x wayvnc 2>/dev/null
    fi

    # Destruir el output headless para que el compositor vuelva al estado normal
    if hyprctl monitors | grep -q "$OUTPUT_NAME"; then
        hyprctl output remove "$OUTPUT_NAME" >/dev/null 2>&1
    fi
    echo "wayvnc detenido y output headless removido."
}

case "${1:-}" in
    init)       init ;;
    on|start)   start ;;
    off|stop)   stop ;;
    status)     status ;;
    *)          echo "Uso: $0 {init|on|off|status}" ; exit 1 ;;
esac
