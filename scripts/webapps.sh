#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# webapps.sh — Webapps (PWAs) sobre Firefox vía firefoxpwa
# Instala el runtime y crea las webapps de la lista como ventanas propias
# (sin pestañas ni barra de URL). Idempotente: saltea las que ya existen.
#
# Lista: ~/.config/dotfiles/webapps.conf (se gestiona desde Settings →
# WEBAPPS, ver scripts/webapp-manager.sh). Sin ese archivo se usa
# webapps.conf.example del repo. Formato "nombre|manifest|página inicial|ícono";
# manifest vacío = sitio sin PWA, se arma uno mínimo. Los .desktop quedan en
# ~/.local/share/applications/FFPWA-<ID>.desktop, así que
# walker/rofi las encuentran como cualquier otra app.
#
# Uso: webapps.sh [nombre]   (con nombre instala solo esa entrada)
# ──────────────────────────────────────────────────────────
set -euo pipefail

# shellcheck source=/dev/null
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"
CONF="$DOTFILES_CONF_DIR/webapps.conf"
[[ -r "$CONF" ]] || CONF="$DOTFILES_DIR/webapps.conf.example"
ONLY="${1:-}"

command -v firefoxpwa &>/dev/null || {
    echo "firefoxpwa no está instalado: sudo pacman -S firefoxpwa" >&2
    exit 1
}

# Manifest mínimo para sitios que no son PWA: firefoxpwa acepta data: URLs
data_manifest() {
    jq -cn --arg n "$1" --arg u "$2" --arg i "$3" '{
        name: $n, short_name: $n, start_url: $u, display: "standalone",
        scope: ($u | capture("^(?<o>https?://[^/]+)").o + "/"),
        icons: (if $i == "" then [] else [{src: $i, sizes: "any"}] end)
    }' | sed 's/^/data:application\/manifest+json,/'
}

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

while IFS='|' read -r name manifest doc icon; do
    [[ -n "$ONLY" && "$name" != "$ONLY" ]] && continue
    if grep -qF -- "- ${name}: " <<< "$installed"; then
        echo "✓ ${name} ya instalada"
        continue
    fi
    echo "→ Instalando ${name}"
    [[ -z "$manifest" ]] && manifest="$(data_manifest "$name" "$doc" "$icon")"
    args=(site install "$manifest" --document-url "$doc" --name "$name")
    [[ -n "$icon" ]] && args+=(--icon-url "$icon")
    firefoxpwa "${args[@]}"
done < <(grep -vE '^\s*(#|$)' "$CONF")
