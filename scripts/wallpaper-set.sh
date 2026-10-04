#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# wallpaper-set.sh — aplica un wallpaper sin cambiar de tema
# Lo usa Settings → Backgrounds (tools/settings/settings_tui.py). Es la
# lógica que antes vivía en el menú rofi de Settings (list_backgrounds):
#   1) guarda la ruta en ~/.local/state/dotfiles/current_theme.json (fuente
#      única del wallpaper; start-hyprpaper.sh y Qtile la leen al iniciar)
#   2) Hyprland: lo aplica por IPC de hyprpaper (lo arranca si no corre)
#      X11/Qtile: actualiza betterlockscreen (si está) y recarga Qtile
#   3) reinicia la barra y avisa
#
# Uso: wallpaper-set.sh <ruta-al-wallpaper>
# ──────────────────────────────────────────────────────────
set -uo pipefail

# shellcheck source=lib/env.sh
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"

WALLPAPER="${1:-}"
[[ -n "$WALLPAPER" && -f "$WALLPAPER" ]] || { echo "Uso: $(basename "$0") <wallpaper>" >&2; exit 2; }
WALLPAPER="$(readlink -f "$WALLPAPER")"

CURRENT_THEME="$DOTFILES_STATE_DIR/current_theme.json"
if command -v jq &>/dev/null && [[ -f "$CURRENT_THEME" ]]; then
    tmp="$(mktemp)"
    jq --arg wp "$WALLPAPER" '.wallpaper = $wp' "$CURRENT_THEME" > "$tmp" && mv -f "$tmp" "$CURRENT_THEME"
    rm -f "$tmp"
fi

if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]]; then
    pgrep -x hyprpaper >/dev/null || { setsid -f hyprpaper >/dev/null 2>&1; sleep 0.3; }
    hyprctl hyprpaper wallpaper ",$WALLPAPER" >/dev/null 2>&1 || true
else
    if [[ "${XDG_SESSION_TYPE:-}" != "wayland" ]] && command -v feh &>/dev/null; then
        feh --bg-fill "$WALLPAPER" 2>/dev/null || true
    fi
    if command -v betterlockscreen &>/dev/null; then
        betterlockscreen -u "$WALLPAPER" >> "$DOTFILES_STATE_DIR/betterlockscreen.log" 2>&1 || true
    fi
    pgrep -x qtile >/dev/null && { qtile cmd-obj -o cmd -f reload_config 2>/dev/null || true; }
fi

bash "$DOTFILES_DIR/scripts/barupdate.sh" 2>/dev/null || true
name="$(basename "$WALLPAPER")"
notify-send "Background" "Changed to ${name%.*}" -t 2000 2>/dev/null || true
