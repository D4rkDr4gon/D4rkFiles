#!/usr/bin/env bash
# Etapa: preflight — valida el sistema y prepara sudo.

_SUDO_KEEPALIVE_PID=""

step_preflight() {
    header "Sistema"
    [[ -f /etc/arch-release ]] || die "Este instalador es para Arch Linux (y derivadas con pacman)."
    [[ $EUID -ne 0 ]] || die "No lo ejecutes como root: usa sudo solo cuando hace falta."
    command -v sudo >/dev/null 2>&1 || die "Falta sudo."
    log "Usuario: ${USER:-$(id -un)} | kernel $(uname -r) | repo: $DOTFILES_DIR"

    # Una sola contraseña para todo el proceso (yay compila durante minutos y
    # el ticket de sudo caduca). Se cancela al salir.
    if ! $DRY_RUN && [[ -t 0 ]]; then
        sudo -v || die "No se pudo obtener sudo."
        ( while true; do sudo -n true 2>/dev/null; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) &
        _SUDO_KEEPALIVE_PID=$!
        trap '[[ -n "$_SUDO_KEEPALIVE_PID" ]] && kill "$_SUDO_KEEPALIVE_PID" 2>/dev/null' EXIT
    fi
}
