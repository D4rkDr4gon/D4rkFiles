#!/usr/bin/env bash
# common.sh — utilidades del instalador (logging, dry-run, preguntas, enlaces).
# Se hace `source` desde install.sh; no se ejecuta directamente.

if [[ -t 1 ]]; then
    C_RED=$'\033[0;31m'; C_GREEN=$'\033[0;32m'; C_YELLOW=$'\033[1;33m'
    C_BLUE=$'\033[0;34m'; C_CYAN=$'\033[0;36m'; C_RESET=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_CYAN=""; C_RESET=""
fi

log()    { printf '%s[ok]%s   %s\n' "$C_GREEN" "$C_RESET" "$*"; }
info()   { printf '%s[..]%s   %s\n' "$C_CYAN" "$C_RESET" "$*"; }
warn()   { printf '%s[warn]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()    { printf '%s[error]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
header() { printf '\n%s== %s ==%s\n' "$C_BLUE" "$*" "$C_RESET"; }

# Flags globales (los fija install.sh).
DRY_RUN="${DRY_RUN:-false}"
ASSUME_YES="${ASSUME_YES:-false}"

# run <comando...>: ejecuta, o solo lo muestra con --dry-run.
run() {
    if $DRY_RUN; then
        printf '%s[dry-run]%s %s\n' "$C_YELLOW" "$C_RESET" "$*"
        return 0
    fi
    "$@"
}

# ask <pregunta> [default s|n]: 0 = sí. Con --yes devuelve siempre el default
# (los pasos opcionales tienen default "n": --yes nunca instala extras).
ask() {
    local prompt="$1" default="${2:-n}" reply
    if $ASSUME_YES || [[ ! -t 0 ]]; then
        [[ "$default" == "s" ]]
        return
    fi
    read -r -p "   $prompt [$([[ $default == s ]] && echo S/n || echo s/N)]: " reply || reply=""
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[sSyY] ]]
}

# ask_value <pregunta> <default>: imprime la respuesta (o el default con --yes / sin tty).
ask_value() {
    local prompt="$1" default="${2:-}" reply
    if $ASSUME_YES || [[ ! -t 0 ]]; then
        printf '%s' "$default"
        return
    fi
    read -r -p "   $prompt [${default}]: " reply || reply=""
    printf '%s' "${reply:-$default}"
}

# Directorio de backups de esta ejecución (se crea recién cuando hace falta).
_BACKUP_DIR=""
backup_dir() {
    if [[ -z "$_BACKUP_DIR" ]]; then
        _BACKUP_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/backups/$(date +%Y%m%d-%H%M%S)"
    fi
    printf '%s' "$_BACKUP_DIR"
}

# backup_path <ruta absoluta bajo $HOME>: mueve lo existente al backup (conserva la
# ruta relativa). Nada se borra: rehacer el estado previo es un `mv`.
backup_path() {
    local target="$1" rel dest
    rel="${target#"$HOME"/}"
    dest="$(backup_dir)/$rel"
    info "Backup: $target -> $dest"
    if ! $DRY_RUN; then
        mkdir -p "$(dirname "$dest")"
        mv -- "$target" "$dest"
    fi
}

# link_one <origen absoluto> <destino absoluto>: symlink idempotente con backup.
#   - ya apunta al origen        -> nada
#   - symlink a otro lado        -> se registra y se reemplaza
#   - archivo/directorio real    -> backup y se reemplaza
link_one() {
    local src="$1" dst="$2"
    if [[ ! -e "$src" ]]; then
        if [[ -e "$src.tpl" ]]; then
            warn "Falta $(basename "$src") (se genera desde su .tpl): corré la etapa configure antes que links"
        else
            warn "Origen inexistente, se omite: $src"
        fi
        return 0
    fi
    # Origen y destino son la misma ruta real (ej. el repo clonado directamente en
    # ~/.local/share/dotfiles): no hay nada que enlazar, y NO hay que "respaldarlo".
    if [[ "$(readlink -f "$src")" == "$(readlink -f "$dst")" ]]; then
        return 0
    fi
    if [[ -L "$dst" ]]; then
        if [[ "$(readlink -f "$dst")" == "$(readlink -f "$src")" ]]; then
            return 0
        fi
        info "Symlink distinto en $dst -> $(readlink "$dst") (se reemplaza)"
        run rm -f -- "$dst"
    elif [[ -e "$dst" ]]; then
        backup_path "$dst"
    fi
    run mkdir -p "$(dirname "$dst")"
    run ln -sfT -- "$src" "$dst"
    log "Enlace: ${dst/#"$HOME"/\~} -> ${src/#"$HOME"/\~}"
}

# Lee un archivo de paquetes: un nombre por línea, ignora comentarios y vacías.
read_pkgs() {
    local f="$1"
    [[ -r "$f" ]] || return 0
    awk '!/^[[:space:]]*(#|$)/ {print $1}' "$f"
}
