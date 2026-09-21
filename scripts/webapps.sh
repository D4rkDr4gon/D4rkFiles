#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# webapps.sh — Webapps (PWAs) sobre Firefox vía firefoxpwa
# Instala el runtime y crea las webapps de la lista como ventanas propias
# (sin pestañas ni barra de URL). Idempotente: saltea las que ya existen.
#
# Tu propia lista: ~/.config/dotfiles/webapps.conf, una por línea, con el
# formato "nombre|manifest|página inicial|ícono(opcional)". Ejemplo:
#   WhatsApp|https://web.whatsapp.com/data/manifest.json|https://web.whatsapp.com/|
# Si el archivo existe reemplaza a la lista por defecto. Los .desktop quedan en
# ~/.local/share/applications/FFPWA-<ID>.desktop, así que
# walker/rofi las encuentran como cualquier otra app.
# ──────────────────────────────────────────────────────────
set -euo pipefail

command -v firefoxpwa &>/dev/null || {
    echo "firefoxpwa no está instalado: sudo pacman -S firefoxpwa" >&2
    exit 1
}

# nombre | manifest | página inicial | ícono (opcional, si el manifest no trae uno usable)
WEBAPPS=(
    "YouTube|https://www.youtube.com/manifest.webmanifest|https://www.youtube.com/|"
)
_conf="${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/webapps.conf"
if [[ -r "$_conf" ]]; then
    mapfile -t WEBAPPS < <(grep -vE '^\s*(#|$)' "$_conf")
fi

# El runtime (Firefox parcheado que corre las PWAs) se descarga a
# ~/.local/share/firefoxpwa/runtime; no requiere root. --link no sirve:
# es experimental y necesita parchear /usr/lib/firefox.
if [[ ! -d "$HOME/.local/share/firefoxpwa/runtime/browser" ]]; then
    echo "→ Instalando runtime de firefoxpwa"
    firefoxpwa runtime install
fi

# El instalador escribe en ~/.local/share/mime/packages y se queja si no existe
mkdir -p "$HOME/.local/share/mime/packages"

installed="$(firefoxpwa profile list 2>/dev/null || true)"

for entry in "${WEBAPPS[@]}"; do
    IFS='|' read -r name manifest doc icon <<< "$entry"
    if grep -q "^- ${name}:" <<< "$installed"; then
        echo "✓ ${name} ya instalada"
        continue
    fi
    echo "→ Instalando ${name}"
    args=(site install "$manifest" --document-url "$doc" --name "$name")
    [[ -n "$icon" ]] && args+=(--icon-url "$icon")
    firefoxpwa "${args[@]}"
done
