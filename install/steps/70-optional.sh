#!/usr/bin/env bash
# Etapa: optional — extras que NUNCA se instalan sin pedirlos (--with-* o pregunta).

step_optional() {
    header "Opcionales"

    if $WITH_OLLAMA || ask "Instalar Ollama (IA local)?" n; then
        local -a noconfirm=(); $ASSUME_YES && noconfirm=(--noconfirm)
        run sudo pacman -S --needed "${noconfirm[@]}" ollama
        run sudo systemctl enable --now ollama.service
        info "Modelos: ollama pull <modelo> (ej. qwen3:1.7b). No se descargan automáticamente."
    fi

    # netguard: proyecto aparte (github.com/D4rkDr4gon/netguard) en una versión fijada; también se usa sin D4rkFiles
    if $WITH_NETGUARD || ask "Instalar netguard (zonas de red: VPN obligatoria en redes inseguras, kill switch)?" n; then
        local -a ngpkgs=(git base-devel); $ASSUME_YES && ngpkgs+=(--noconfirm)
        run sudo pacman -S --needed "${ngpkgs[@]}"
        if run "$DOTFILES_DIR/scripts/install-netguard.sh" --setup; then
            info "netguard: Settings → Firewall → Zones y Network security, o netguard tui. Sumá una VPN: netguard pool add <conexión>"
        else
            warn "netguard no se instaló: reintentá con scripts/install-netguard.sh --setup"
        fi
    fi

    if command -v firefoxpwa >/dev/null 2>&1 && ask "Crear las webapps de scripts/webapps.sh (descarga un runtime)?" n; then
        run "$DOTFILES_DIR/scripts/webapps.sh" || warn "Reintentá con scripts/webapps.sh"
    fi
}
