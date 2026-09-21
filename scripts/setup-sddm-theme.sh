#!/usr/bin/env bash
# Instala el tema de login de SDDM "dotfiles-ascii" (fondo negro + banner en el
# color del tema). Requiere sudo. Idempotente: se puede volver a correr.
#
# theme.conf queda con dueño = usuario, para que theme-switch.sh actualice los
# colores sin pedir sudo cada vez que se cambia de tema.
#
# Opciones:
#   --with-fingerprint-pam   Instala además /etc/pam.d/sddm con login por contraseña
#                            O huella (solo si pam_fprintd está instalado; hace
#                            backup del PAM actual). Es opcional: modifica la
#                            autenticación del sistema, revisá system/sddm/pam.d/sddm.
#
# Rollback tema: sudo cp /etc/sddm-theme.conf.bak-previous /etc/sddm.conf.d/theme.conf
# Rollback PAM:  sudo cp /etc/sddm-pam.bak-previous /etc/pam.d/sddm
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
DOTFILES_DIR="$(cd -P "$(dirname "$SELF")/.." && pwd)"
export DOTFILES_DIR
# shellcheck source=lib/env.sh
source "$DOTFILES_DIR/scripts/lib/env.sh"

WITH_PAM=false
for arg in "$@"; do
    case "$arg" in
        --with-fingerprint-pam) WITH_PAM=true ;;
        -h|--help) sed -n '2,15p' "$SELF"; exit 0 ;;
        *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
    esac
done

SRC="$DOTFILES_DIR/system/sddm/dotfiles-ascii"
DST="/usr/share/sddm/themes/dotfiles-ascii"
CONF="/etc/sddm.conf.d/theme.conf"
# SDDM lee TODOS los archivos de /etc/sddm.conf.d/ (sin filtrar extensión), en orden
# alfabético: un backup dentro de ese directorio pisaría el tema. Va afuera.
BAK="/etc/sddm-theme.conf.bak-previous"

command -v sddm >/dev/null 2>&1 || { echo "sddm no está instalado, nada que hacer"; exit 0; }

# Renderiza Main.qml y theme.conf con el tema activo (o el default).
theme="$(jq -r '.name // empty' "$DOTFILES_STATE_DIR/current_theme.json" 2>/dev/null | tr 'A-Z ' 'a-z-' || true)"
[[ -d "$DOTFILES_DIR/themes/$theme" ]] || theme="$DEFAULT_THEME"
"$DOTFILES_DIR/scripts/theme-switch.sh" "$theme" --render-only >/dev/null

sudo install -d -m 755 "$DST"
sudo install -m 644 "$SRC/Main.qml" "$SRC/metadata.desktop" "$DST/"
sudo install -m 644 -o "$USER" -g "$(id -gn)" "$SRC/theme.conf" "$DST/theme.conf"

sudo install -d -m 755 /etc/sddm.conf.d
if [[ -f "$CONF" ]] && ! grep -q "dotfiles-ascii" "$CONF"; then
    sudo cp "$CONF" "$BAK"
fi
printf '[Theme]\nCurrent=dotfiles-ascii\n' | sudo tee "$CONF" >/dev/null

if $WITH_PAM; then
    if [[ ! -e /usr/lib/security/pam_fprintd.so ]]; then
        echo "pam_fprintd no está instalado (paquete fprintd): se omite el PAM." >&2
    else
        PAM_BAK="/etc/sddm-pam.bak-previous"
        if [[ -f /etc/pam.d/sddm ]] && ! cmp -s "$DOTFILES_DIR/system/sddm/pam.d/sddm" /etc/pam.d/sddm && [[ ! -f "$PAM_BAK" ]]; then
            sudo cp /etc/pam.d/sddm "$PAM_BAK"
        fi
        sudo install -m 644 "$DOTFILES_DIR/system/sddm/pam.d/sddm" /etc/pam.d/sddm
        echo "PAM instalado (contraseña o huella). Backup en $PAM_BAK"
    fi
fi

echo "Tema instalado. SDDM lee su config solo al arrancar: reiniciá o corré 'sudo systemctl restart sddm'."
echo "Previsualizar sin cerrar sesión: sddm-greeter-qt6 --test-mode --theme $DST"
