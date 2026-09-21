#!/usr/bin/env bash
# Etapa: configure — user.conf, overrides locales y render del tema.

step_configure() {
    header "Configuración de usuario"
    local conf_dir="${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles"
    local conf="$conf_dir/user.conf"

    run mkdir -p "$conf_dir/hypr"
    # Hyprland necesita al menos un .conf en este directorio (source con glob).
    if [[ ! -e "$conf_dir/hypr/local.conf" ]]; then
        if $DRY_RUN; then echo "[dry-run] crear $conf_dir/hypr/local.conf"; else
            cat > "$conf_dir/hypr/local.conf" <<'CONF'
# Tus overrides de Hyprland (se cargan al final, pisan todo lo anterior).
# Ejemplo de monitores (nombres con `hyprctl monitors`):
#   monitor=eDP-1,1920x1080@60,0x0,1
#   monitor=DP-1,2560x1440@144,1920x0,1
CONF
        fi
        log "Creado ${conf_dir/#"$HOME"/\~}/hypr/local.conf"
    fi

    if [[ -e "$conf" ]]; then
        log "Ya existe ${conf/#"$HOME"/\~} (no se toca)"
    else
        local name title
        name="$(ask_value "Nombre para banners y bienvenida" "$(df_detect_display_name)")"
        title="$(ask_value "Título/alias opcional (Enter = ninguno)" "")"
        if $DRY_RUN; then
            echo "[dry-run] crear $conf (USER_DISPLAY_NAME=\"$name\", USER_TITLE=\"$title\")"
        else
            {
                sed -n '1,/^# --- Identidad/p' "$DOTFILES_DIR/user.conf.example" | sed '$d'
                printf '# --- Identidad ---\nUSER_DISPLAY_NAME="%s"\nUSER_TITLE="%s"\n' "$name" "$title"
                sed -n '/^# --- Aplicaciones por defecto/,$p' "$DOTFILES_DIR/user.conf.example"
            } > "$conf"
            log "Creado ${conf/#"$HOME"/\~}"
        fi
        # Recargar valores recién escritos
        # shellcheck disable=SC1090
        $DRY_RUN || { set -a; source "$conf"; set +a; }
    fi

    header "Tema"
    if [[ -x "$DOTFILES_DIR/scripts/theme-switch.sh" ]] && command -v jq >/dev/null 2>&1; then
        if $DRY_RUN; then
            echo "[dry-run] theme-switch.sh $DEFAULT_THEME --render-only"
        else
            "$DOTFILES_DIR/scripts/theme-switch.sh" "$DEFAULT_THEME" --render-only
        fi
    else
        warn "Falta jq: instalá los paquetes (etapa 'packages') y volvé a correr --only configure"
    fi
}
