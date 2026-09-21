#!/usr/bin/env bash
# theme.sh — motor de temas: tokens de theme.json + renderizado de plantillas.
# Se hace `source` (requiere scripts/lib/env.sh cargado antes). No se ejecuta.
#
# Una plantilla es cualquier `archivo.ext.tpl` con tokens @nombre@ dentro de
# config/, home/ o system/. Se renderiza a `archivo.ext` (mismo directorio,
# ignorado por git). Nada trackeado se edita nunca en el lugar.

THEMES_DIR="$DOTFILES_DIR/themes"
TEMPLATES_DIR="$THEMES_DIR/templates"
CURRENT_THEME_FILE="$DOTFILES_STATE_DIR/current_theme.json"

declare -A TOK=()

# Mezcla dos colores "#rrggbb"; pct = peso (0-100) del primero.
hex_blend() {
    local c1="${1#\#}" c2="${2#\#}" pct=$3
    local r1=$((16#${c1:0:2})) g1=$((16#${c1:2:2})) b1=$((16#${c1:4:2}))
    local r2=$((16#${c2:0:2})) g2=$((16#${c2:2:2})) b2=$((16#${c2:4:2}))
    printf '#%02x%02x%02x' \
        $(( (r1 * pct + r2 * (100 - pct)) / 100 )) \
        $(( (g1 * pct + g2 * (100 - pct)) / 100 )) \
        $(( (b1 * pct + b2 * (100 - pct)) / 100 ))
}

_is_hex() { [[ "$1" =~ ^#[0-9a-fA-F]{6}$ ]]; }

# Carga theme.json en TOK (con defaults y valores derivados).
theme_load_tokens() {
    local json="$1" k v c

    TOK=()
    # to_entries respeta valores falsy (false/0): no se pisan con el default.
    while IFS=$'\t' read -r k v; do
        TOK[$k]="$v"
    done < <(jq -r 'to_entries[] | select(.value | type != "object" and type != "array")
                    | [.key, (.value | tostring)] | @tsv' "$json")

    local req
    for req in primary secondary background foreground chip_battery chip_bluetooth chip_wlan \
               chip_audio status_ok status_warn status_error; do
        _is_hex "${TOK[$req]:-}" || { echo "Error: '$req' inválido en $json" >&2; return 1; }
    done

    # "Forma": opcionales. Sin ellos, el resultado es el de siempre.
    : "${TOK[radius]:=10}" "${TOK[opacity]:=0.80}" "${TOK[blur_enabled]:=true}"
    : "${TOK[blur_size]:=6}" "${TOK[blur_passes]:=2}" "${TOK[font_mono]:=Hack Nerd Font}"
    : "${TOK[icon_theme]:=Papirus-Dark}" "${TOK[opencode_theme]:=}"

    # Opacidad por niveles (kitty = base, rofi = base-0.05, resto = base+0.05).
    # Con opacidad total (>=0.98) todo pasa a 1.0. Los TUI flotantes van fijos.
    if awk -v o="${TOK[opacity]}" 'BEGIN{exit !(o>=0.98)}'; then
        TOK[opacity_secondary]=1.0; TOK[opacity_rofi]=1.0
    else
        TOK[opacity_secondary]=$(awk -v o="${TOK[opacity]}" 'BEGIN{v=o+0.05; if(v>1.0)v=1.0; printf "%.2f", v}')
        TOK[opacity_rofi]=$(awk -v o="${TOK[opacity]}" 'BEGIN{v=o-0.05; if(v<0.50)v=0.50; printf "%.2f", v}')
    fi
    TOK[opacity_tui]=0.97

    TOK[radius_outer]=$(( TOK[radius] + 4 ))
    # "Hack Nerd Font" y "Hack Nerd Font Mono" son familias distintas (gtklock/SDDM).
    TOK[font_mono_alt]="${TOK[font_mono]}"
    [[ "${TOK[font_mono]}" == "Hack Nerd Font" ]] && TOK[font_mono_alt]="Hack Nerd Font Mono"

    TOK[text_muted]=$(hex_blend "${TOK[foreground]}" "${TOK[background]}" 45)
    TOK[text_dim]=$(hex_blend "${TOK[foreground]}" "${TOK[background]}" 20)
    TOK[text_sub]=$(hex_blend "${TOK[foreground]}" "${TOK[background]}" 75)

    # Paleta ANSI 16 (kitty): sin ella los TUI usan la paleta por defecto.
    TOK[ansi_cyan]=$(hex_blend "${TOK[primary]}" "${TOK[status_ok]}" 50)
    TOK[ansi_bright_red]=$(hex_blend "${TOK[foreground]}" "${TOK[status_error]}" 25)
    TOK[ansi_bright_green]=$(hex_blend "${TOK[foreground]}" "${TOK[status_ok]}" 25)
    TOK[ansi_bright_yellow]=$(hex_blend "${TOK[foreground]}" "${TOK[status_warn]}" 25)
    TOK[ansi_bright_blue]=$(hex_blend "${TOK[foreground]}" "${TOK[primary]}" 25)
    TOK[ansi_bright_magenta]=$(hex_blend "${TOK[foreground]}" "${TOK[secondary]}" 25)
    TOK[ansi_bright_cyan]=$(hex_blend "${TOK[foreground]}" "${TOK[ansi_cyan]}" 25)

    # Componentes RGB y colores sin "#" (Hyprland usa rgb(rrggbb)).
    for c in background primary chip_battery; do
        local h="${TOK[$c]#\#}"
        TOK[${c}_r]=$((16#${h:0:2})); TOK[${c}_g]=$((16#${h:2:2})); TOK[${c}_b]=$((16#${h:4:2}))
        TOK[${c}_hex]="$h"
    done
    TOK[bg_r]=${TOK[background_r]}; TOK[bg_g]=${TOK[background_g]}; TOK[bg_b]=${TOK[background_b]}

    # Colores ANSI de 24 bits (statusline de Claude Code): \033[38;2;R;G;Bm
    local ac h2
    for ac in ok:status_ok warn:status_warn error:status_error primary:primary; do
        h2="${TOK[${ac#*:}]#\#}"
        TOK[ansi_${ac%%:*}]="$(printf '\\033[38;2;%d;%d;%dm' "$((16#${h2:0:2}))" "$((16#${h2:2:2}))" "$((16#${h2:4:2}))")"
    done

    if [[ -n "${TOK[opencode_theme]}" ]]; then
        TOK[opencode_theme_line]="  \"theme\": \"${TOK[opencode_theme]}\","
    else
        TOK[opencode_theme_line]=""
    fi

    # Wallpaper: el theme.json guarda solo el nombre; se resuelve contra WALLPAPER_DIRS.
    TOK[wallpaper]="$(df_resolve_wallpaper "${TOK[wallpaper]:-}" || true)"
}

# Tokens que vienen del usuario/máquina (user.conf + autodetección).
theme_load_user_tokens() {
    TOK[user_display_name]="$USER_DISPLAY_NAME"
    TOK[user_title]="$USER_TITLE"
    TOK[terminal]="$TERMINAL"
    TOK[browser]="$BROWSER"
    TOK[file_manager]="$FILE_MANAGER"
    TOK[editor_gui]="$EDITOR_GUI"
    TOK[kb_layout]="$KB_LAYOUT"
    TOK[kb_variant]="$KB_VARIANT"
    TOK[dotfiles]="$DOTFILES_DATA_DIR"
    TOK[home]="$HOME"
    TOK[user]="${USER:-$(id -un)}"

    # Banner (gtklock: XML en una línea; SDDM: string QML en una línea).
    local banner xml="" qml="" l
    banner="$(df_banner)"
    while IFS= read -r l; do
        l="${l//&/&amp;}"; l="${l//</&lt;}"; l="${l//>/&gt;}"
        xml+="${xml:+&#10;}$l"
        l="${l//\\/\\\\}"; l="${l//\"/\\\"}"
        qml+="${qml:+ + }\"$l\\n\""
    done <<<"$banner"
    TOK[banner_xml]="$xml"
    TOK[banner_qml]="$qml"
    printf '%s\n' "$banner" > "$DOTFILES_DIR/home/zsh/banner.txt"   # lo imprime 60-banner.zsh
    TOK[battery]="$(df_detect_battery || true)"
    TOK[wifi_iface]="$(df_detect_wifi_iface || true)"
    # NVIDIA y VMs necesitan cursor por software en wlroots/Hyprland.
    TOK[hw_cursor_env]=""
    if command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -qiE 'nvidia|vmware|virtio|qxl'; then
        TOK[hw_cursor_env]="env = WLR_NO_HARDWARE_CURSORS,1"
    fi
}

# Escapa un valor para usarlo como REEMPLAZO en `sed 's|..|VALOR|'`.
_sed_repl() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

_SEDSCRIPT=""
_build_sedscript() {
    _SEDSCRIPT="$(mktemp)"
    local k
    for k in "${!TOK[@]}"; do
        printf 's|@%s@|%s|g\n' "$k" "$(_sed_repl "${TOK[$k]}")"
    done > "$_SEDSCRIPT"
}

# render_template <origen.tpl> <destino>
render_template() {
    local src="$1" dst="$2" tk
    [[ -n "$_SEDSCRIPT" ]] || _build_sedscript
    for tk in $(grep -oE '@[a-z][a-z0-9_]*@' "$src" | sort -u); do
        tk="${tk//@/}"
        [[ -v TOK[$tk] ]] || echo "  ⚠ token @$tk@ sin valor en $(basename "$src")" >&2
    done
    mkdir -p "$(dirname "$dst")"
    sed -f "$_SEDSCRIPT" "$src" > "$dst.tmp" && mv -f "$dst.tmp" "$dst"
}

# Renderiza todas las plantillas del repo junto a su origen (X.tpl -> X).
render_all_templates() {
    local t n=0
    while IFS= read -r -d '' t; do
        render_template "$t" "${t%.tpl}"
        n=$((n + 1))
    done < <(find "$DOTFILES_DIR/config" "$DOTFILES_DIR/home" "$DOTFILES_DIR/system" \
                  -name '*.tpl' -not -path '*/node_modules/*' -print0 2>/dev/null)
    echo "  → $n plantillas renderizadas"
}

# Genera el JSON del tema activo con el wallpaper ya resuelto (lo leen
# Qtile y las TUIs). Vive en el directorio de estado, no en el repo.
write_current_theme() {
    local json="$1"
    mkdir -p "$DOTFILES_STATE_DIR"
    jq --arg wp "${TOK[wallpaper]}" '.wallpaper = $wp' "$json" > "$CURRENT_THEME_FILE.tmp" \
        && mv -f "$CURRENT_THEME_FILE.tmp" "$CURRENT_THEME_FILE"
}

# Firefox: userChrome/userContent van al perfil activo (nombre aleatorio por
# máquina). Firefox los lee solo al arrancar.
apply_firefox_theme() {
    local ini="$HOME/.mozilla/firefox/profiles.ini" prof=""
    [[ -f "$ini" ]] || return 0
    prof=$(awk -F= '/^\[Install/{s=1;next} /^\[/{s=0} s && $1=="Default"{print $2; exit}' "$ini" || true)
    [[ -n "$prof" ]] || return 0
    [[ "$prof" = /* ]] || prof="$(dirname "$ini")/$prof"
    [[ -d "$prof" ]] || return 0
    mkdir -p "$prof/chrome"
    render_template "$TEMPLATES_DIR/firefox-userChrome.css.tpl" "$prof/chrome/userChrome.css"
    render_template "$TEMPLATES_DIR/firefox-userContent.css.tpl" "$prof/chrome/userContent.css"
    local pref='user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'
    grep -qF "$pref" "$prof/user.js" 2>/dev/null || echo "$pref" >> "$prof/user.js"
    echo "  → firefox userChrome/userContent (reiniciar Firefox)"
}

# HyprFM y cliamp guardan su tema en su propio directorio de config.
apply_external_themes() {
    local hf="$XDG_CONFIG_HOME/hyprfm"
    if [[ -d "$hf" ]]; then
        render_template "$TEMPLATES_DIR/hyprfm.toml.tpl" "$hf/themes/dotfiles.toml"
        if [[ -f "$hf/config.toml" ]] && ! grep -q "^theme = 'dotfiles'" "$hf/config.toml"; then
            sed -i "s|^theme = .*|theme = 'dotfiles'|" "$hf/config.toml"
        fi
        echo "  → hyprfm"
    fi
    local cl="$XDG_CONFIG_HOME/cliamp"
    if [[ -f "$cl/config.toml" ]]; then
        render_template "$TEMPLATES_DIR/cliamp.toml.tpl" "$cl/themes/dotfiles.toml"
        if grep -q '^theme = ' "$cl/config.toml"; then
            sed -i 's|^theme = .*|theme = "dotfiles"|' "$cl/config.toml"
        else
            sed -i '1i theme = "dotfiles"' "$cl/config.toml"
        fi
        echo "  → cliamp"
    fi
    apply_firefox_theme
}

# Copia el theme.conf de SDDM al tema del sistema (si el usuario puede escribirlo;
# scripts/setup-sddm-theme.sh deja ese archivo a nombre del usuario).
apply_sddm_theme() {
    local repo="$DOTFILES_DIR/system/sddm/dotfiles-ascii/theme.conf"
    local sys="/usr/share/sddm/themes/dotfiles-ascii/theme.conf"
    [[ -f "$repo" && -w "$sys" ]] && cat "$repo" > "$sys" && echo "  → sddm"
    return 0
}
