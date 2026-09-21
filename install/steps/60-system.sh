#!/usr/bin/env bash
# Etapa: system — servicios, login manager, unidades de usuario y directorios.

_enable_system() {
    local svc="$1"
    systemctl is-enabled "$svc" >/dev/null 2>&1 && { log "$svc ya habilitado"; return 0; }
    run sudo systemctl enable "$svc" || warn "No se pudo habilitar $svc"
}

step_system() {
    header "Servicios y sesión"
    command -v systemctl >/dev/null 2>&1 || { warn "systemd no disponible: se omite"; return 0; }

    _enable_system NetworkManager.service
    _enable_system bluetooth.service

    # Display manager: solo si no hay uno ya habilitado (no pisa el tuyo).
    if $WITH_HYPRLAND; then
        if systemctl is-enabled display-manager.service >/dev/null 2>&1; then
            log "Display manager ya configurado: $(basename "$(readlink -f /etc/systemd/system/display-manager.service)")"
        elif [[ "$DISPLAY_MANAGER" != "none" ]] && ask "Habilitar $DISPLAY_MANAGER como login manager?" s; then
            _enable_system "$DISPLAY_MANAGER.service"
        fi
        # Entrada de sesión propia: NO pisa la que instala el paquete hyprland.
        local session="$DOTFILES_DIR/system/sessions/hyprland.desktop"
        if [[ -f "$session" && ! -e /usr/share/wayland-sessions/hyprland-dotfiles.desktop ]] \
            && ask "Agregar la sesión 'Hyprland (dotfiles)' al login manager (usa sudo)?" s; then
            run sudo install -Dm644 "$session" /usr/share/wayland-sessions/hyprland-dotfiles.desktop
        fi
        if command -v sddm >/dev/null 2>&1 && [[ "$DISPLAY_MANAGER" == "sddm" ]] \
            && ask "Instalar el tema de login de SDDM (usa sudo)?" s; then
            run "$DOTFILES_DIR/scripts/setup-sddm-theme.sh" || warn "Reintentá con scripts/setup-sddm-theme.sh"
        fi
    fi

    # Sesión de usuario: PipeWire y unidades del repo.
    run systemctl --user daemon-reload || true
    if command -v pipewire >/dev/null 2>&1; then
        run systemctl --user enable pipewire pipewire-pulse wireplumber 2>/dev/null || true
    fi
    if [[ -e "$HOME/.config/systemd/user/battery-watch.timer" ]] \
        && [[ -d /sys/class/power_supply ]] && ls /sys/class/power_supply/BAT* >/dev/null 2>&1; then
        run systemctl --user enable battery-watch.timer 2>/dev/null || true
    fi
    if $WITH_HYPRLAND; then
        run systemctl --user enable hyprland-session-init.service elephant.service 2>/dev/null || true
    fi

    # Brillo sin root (brightnessctl) y directorios de usuario.
    if getent group video >/dev/null 2>&1 && ! id -nG | grep -qw video; then
        run sudo usermod -aG video "$USER" && info "Agregado al grupo video (cerrá sesión para que aplique)"
    fi
    command -v xdg-user-dirs-update >/dev/null 2>&1 && run xdg-user-dirs-update
    run mkdir -p "$(xdg-user-dir PICTURES 2>/dev/null || echo "$HOME/Pictures")/Screenshots"
}
