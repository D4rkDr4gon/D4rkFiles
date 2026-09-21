#!/usr/bin/env bash
# Etapa: packages — paquetes oficiales y AUR según las sesiones elegidas.

PKG_DIR="$DOTFILES_DIR/install/packages"

# Grupos de paquetes activos, según flags y hardware.
_pkg_groups() {
    printf 'base\n'
    $WITH_HYPRLAND && printf 'hyprland\n'
    $WITH_X11 && printf 'x11\n'
    return 0
}

_gpu_groups() {
    command -v lspci >/dev/null 2>&1 || return 0
    local gpus; gpus="$(lspci -nn 2>/dev/null | grep -iE 'vga|3d|display' || true)"
    grep -qiE 'amd|ati|radeon' <<<"$gpus" && printf 'gpu-amd\n'
    grep -qi 'intel' <<<"$gpus" && printf 'gpu-intel\n'
    grep -qi 'nvidia' <<<"$gpus" && printf 'gpu-nvidia\n'
    return 0
}

_collect() {  # _collect <sufijo: "" | ".aur"> -> lista de paquetes únicos
    local g
    { for g in $(_pkg_groups) $( [[ -z "$1" ]] && _gpu_groups ); do
          read_pkgs "$PKG_DIR/$g$1.txt"
      done; } | awk '!seen[$0]++'
}

install_yay() {
    command -v yay >/dev/null 2>&1 && { log "yay ya instalado"; return 0; }
    info "Instalando yay (AUR helper)..."
    local tmp; tmp="$(mktemp -d)"
    run sudo pacman -S --needed --noconfirm git base-devel
    run git clone https://aur.archlinux.org/yay.git "$tmp/yay"
    if ! $DRY_RUN; then
        ( cd "$tmp/yay" && makepkg -si --noconfirm ) || { rm -rf "$tmp"; die "Falló la instalación de yay"; }
    else
        echo "[dry-run] (cd $tmp/yay && makepkg -si --noconfirm)"
    fi
    rm -rf "$tmp"
}

step_packages() {
    header "Paquetes"
    local -a official aur missing noconfirm=()
    $ASSUME_YES && noconfirm=(--noconfirm)

    if $DO_UPGRADE && ask "Actualizar el sistema (pacman -Syu) antes de instalar? Evita 404 y actualizaciones parciales" s; then
        run sudo pacman -Syu "${noconfirm[@]}"
    fi

    mapfile -t official < <(_collect "")
    for p in "${official[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then
        info "Instalando ${#missing[@]} paquetes oficiales: ${missing[*]}"
        run sudo pacman -S --needed "${noconfirm[@]}" "${missing[@]}"
    else
        log "Paquetes oficiales: todo instalado"
    fi

    if $USE_AUR; then
        mapfile -t aur < <(_collect ".aur")
        missing=()
        for p in "${aur[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
        if ((${#missing[@]})); then
            install_yay
            info "Instalando ${#missing[@]} paquetes del AUR: ${missing[*]}"
            run yay -S --needed "${noconfirm[@]}" "${missing[@]}"
        else
            log "Paquetes AUR: todo instalado"
        fi
    else
        info "AUR omitido (--no-aur): faltarán walker, hyprshell, cliamp, sublime-text, etc."
    fi
}
