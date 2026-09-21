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

    if command -v firefoxpwa >/dev/null 2>&1 && ask "Crear las webapps de scripts/webapps.sh (descarga un runtime)?" n; then
        run "$DOTFILES_DIR/scripts/webapps.sh" || warn "Reintentá con scripts/webapps.sh"
    fi
}
