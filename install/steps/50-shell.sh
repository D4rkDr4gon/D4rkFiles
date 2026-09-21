#!/usr/bin/env bash
# Etapa: shell — powerlevel10k, shell por defecto y Neovim.

step_shell() {
    header "Zsh y Neovim"
    local zsh_dir="${XDG_DATA_HOME:-$HOME/.local/share}/zsh"

    if [[ -d "$zsh_dir/powerlevel10k" ]]; then
        log "powerlevel10k ya instalado"
    elif [[ -e /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme ]]; then
        log "powerlevel10k (paquete del sistema)"
    else
        run mkdir -p "$zsh_dir"
        run git clone --depth=1 https://github.com/romkatv/powerlevel10k.git "$zsh_dir/powerlevel10k"
    fi

    local zsh_path; zsh_path="$(command -v zsh || true)"
    if [[ -z "$zsh_path" ]]; then
        warn "zsh no está instalado (etapa 'packages')"
    elif [[ "${SHELL:-}" != "$zsh_path" ]]; then
        # chsh pide la contraseña: solo en modo interactivo.
        if ask "Cambiar tu shell por defecto a zsh?" n && run chsh -s "$zsh_path"; then
            log "Shell cambiado a zsh (efecto al volver a iniciar sesión)"
        else
            info "Para cambiarlo después: chsh -s $zsh_path"
        fi
    else
        log "Tu shell ya es zsh"
    fi

    if command -v nvim >/dev/null 2>&1 && ask "Instalar los plugins de Neovim ahora (LazyVim, tarda unos minutos)?" n; then
        run nvim --headless "+Lazy! sync" +qa
    else
        info "Los plugins de Neovim se instalan solos la primera vez que abrís nvim."
    fi
}
