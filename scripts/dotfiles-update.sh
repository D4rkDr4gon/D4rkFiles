#!/usr/bin/env bash
#===============================================================================
# dotfiles-update — actualización del sistema con rollback
#   1. Snapshot de Timeshift (rsync) antes de tocar nada
#   2. pacman -Syu
#   3. yay -Sua (solo AUR; los repos ya los actualizó pacman)
#   4. Limpieza: caché de pacman y yay (paccache), journal, aviso de huérfanos
#   5. Avisos: .pacnew pendientes y reinicio por kernel nuevo
#
# Uso: dotfiles-update.sh [modo] [--no-snapshot] [--no-aur] [--no-clean] [-h]
#   modo: all (default) | check | snapshot | rollback | pacman | aur | clean | orphans
# Rollback: sudo timeshift --restore   (o timeshift-gtk)
#===============================================================================

set -uo pipefail

KEEP_SNAPSHOTS=5          # snapshots "pre-update" que se conservan
KEEP_PKG_VERSIONS=2       # versiones por paquete que deja paccache
JOURNAL_MAX=500M          # tope del journal de systemd al limpiar
SNAP_TAG="dotfiles-update"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
log()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()  { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }
header() { echo -e "\n${BLUE}══ $1 ══${NC}"; }

MODE=all
DO_SNAPSHOT=1; DO_AUR=1; DO_CLEAN=1
for arg in "$@"; do      # el modo puede ir en cualquier posición
    case "$arg" in
        all|check|snapshot|rollback|pacman|aur|clean|orphans) MODE="$arg" ;;
        --no-snapshot) DO_SNAPSHOT=0 ;;
        --no-aur)      DO_AUR=0 ;;
        --no-clean)    DO_CLEAN=0 ;;
        -h|--help)     sed -n '3,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)             error "Opción desconocida: $arg (usá -h)" ;;
    esac
done

[ "$EUID" -eq 0 ] && error "No lo corras como root; usa sudo cuando hace falta."
[ -f /etc/arch-release ] || error "Solo para Arch Linux"

# ------------------------------------------------------------------ snapshot
snapshot() {
    header "SNAPSHOT (Timeshift)"
    command -v timeshift &>/dev/null || error "timeshift no está instalado (usá --no-snapshot para omitirlo)"

    local comment
    comment="$SNAP_TAG pre-update $(date '+%Y-%m-%d %H:%M')"
    sudo timeshift --create --comments "$comment" --tags D \
        || error "Falló el snapshot: no se actualiza sin punto de retorno (usá --no-snapshot para forzar)"
    log "Snapshot creado: $comment"

    # Poda: deja solo los últimos $KEEP_SNAPSHOTS creados por este script
    local old
    old=$(sudo timeshift --list 2>/dev/null \
        | grep -F "$SNAP_TAG" \
        | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}' \
        | sort | head -n -"$KEEP_SNAPSHOTS")
    for name in $old; do
        log "Borrando snapshot viejo: $name"
        sudo timeshift --delete --snapshot "$name" --scripted || warn "No se pudo borrar $name"
    done
}

# ------------------------------------------------------------------- updates
update_repos() {
    header "PACMAN -Syu"
    sudo pacman -Syu || error "pacman falló. Snapshot disponible para rollback: sudo timeshift --restore"
}

update_aur() {
    header "AUR (yay -Sua)"
    command -v yay &>/dev/null || { warn "yay no está instalado, se omite AUR"; return 0; }
    yay -Sua || warn "yay terminó con errores"
}

clean_cache() {
    header "LIMPIEZA"
    local before after
    before=$(du -sk /var/cache/pacman/pkg "$HOME/.cache/yay" /var/log/journal 2>/dev/null | awk '{s+=$1} END {print s+0}')

    if command -v paccache &>/dev/null; then
        sudo paccache -rk"$KEEP_PKG_VERSIONS"   # versiones viejas de lo instalado
        sudo paccache -ruk0                     # paquetes ya desinstalados
    else
        warn "paccache no está (pacman-contrib), se omite"
    fi

    if command -v yay &>/dev/null; then
        yay -Sc --noconfirm >/dev/null 2>&1 || warn "yay -Sc terminó con errores"
    fi

    sudo journalctl --vacuum-size="$JOURNAL_MAX" 2>&1 | tail -1

    after=$(du -sk /var/cache/pacman/pkg "$HOME/.cache/yay" /var/log/journal 2>/dev/null | awk '{s+=$1} END {print s+0}')
    log "Liberado: $(( (before - after) / 1024 )) MB"

    local orphans
    orphans=$(pacman -Qdtq 2>/dev/null)
    if [ -n "$orphans" ]; then
        warn "Paquetes huérfanos (revisá y borrá con: sudo pacman -Rns \$(pacman -Qdtq)):"
        echo "$orphans"
    fi
}

# ------------------------------------------------------------ check / rollback
check_updates() {
    header "PENDIENTES (sin aplicar nada)"
    if command -v checkupdates &>/dev/null; then
        local repo
        repo=$(checkupdates 2>/dev/null)
        if [ -n "$repo" ]; then
            log "Repos oficiales: $(echo "$repo" | wc -l) paquetes"
            echo "$repo"
        else
            log "Repos oficiales: al día"
        fi
    else
        warn "checkupdates no está (pacman-contrib)"
    fi

    if command -v yay &>/dev/null; then
        local aur
        aur=$(yay -Qua 2>/dev/null)
        if [ -n "$aur" ]; then
            log "AUR: $(echo "$aur" | wc -l) paquetes"
            echo "$aur"
        else
            log "AUR: al día"
        fi
    fi
}

rollback() {
    header "SNAPSHOTS (Timeshift)"
    command -v timeshift &>/dev/null || error "timeshift no está instalado"
    sudo timeshift --list || error "No se pudo listar los snapshots"

    echo
    read -rp "[r] restaurar  [d] borrar uno  [Enter] salir: " action
    case "$action" in
        r|R)
            warn "Restaurar revierte el SISTEMA (no /home) al snapshot que elijas."
            sudo timeshift --restore
            ;;
        d|D)
            read -rp "Nombre del snapshot a borrar (ej. 2026-09-20_12-03-32): " name
            [ -n "$name" ] && sudo timeshift --delete --snapshot "$name"
            ;;
    esac
}

remove_orphans() {
    header "HUÉRFANOS"
    local orphans
    orphans=$(pacman -Qdtq 2>/dev/null)
    if [ -z "$orphans" ]; then
        log "No hay paquetes huérfanos"
        return 0
    fi
    warn "Paquetes que ya nadie necesita:"
    echo "$orphans"
    echo
    # pacman pide confirmación (Y/n) antes de borrar nada
    # shellcheck disable=SC2086
    sudo pacman -Rns $orphans
}

# -------------------------------------------------------------------- avisos
post_checks() {
    header "REVISIÓN"
    local pacnew
    pacnew=$(sudo find /etc -name '*.pacnew' -o -name '*.pacsave' 2>/dev/null)
    if [ -n "$pacnew" ]; then
        warn "Archivos de configuración por revisar (pacdiff):"
        echo "$pacnew"
    else
        log "Sin .pacnew/.pacsave pendientes"
    fi

    local running installed
    running=$(uname -r)
    for pkg in linux linux-lts linux-zen linux-hardened; do
        installed=$(pacman -Q "$pkg" 2>/dev/null | awk '{print $1 " " $2}')
        [ -n "$installed" ] && break
    done
    if [ -n "$installed" ] && [ ! -d "/usr/lib/modules/$running" ]; then
        warn "Kernel actualizado ($installed): reiniciá para usarlo"
    fi
}

case "$MODE" in
    check)    check_updates ;;
    snapshot) snapshot ;;
    rollback) rollback ;;
    orphans)  remove_orphans ;;
    pacman)   update_repos ;;
    aur)      update_aur ;;
    clean)    clean_cache ;;
    all)
        [ "$DO_SNAPSHOT" -eq 1 ] && snapshot
        update_repos
        [ "$DO_AUR" -eq 1 ]      && update_aur
        [ "$DO_CLEAN" -eq 1 ]    && clean_cache
        post_checks
        ;;
esac
log "Listo ($MODE)"
