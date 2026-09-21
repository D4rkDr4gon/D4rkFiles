#!/usr/bin/env bash
# Etapa: links — symlinks desde manifest/links.tsv (mismo archivo que usa el doctor).

# Recorre el manifiesto y llama a "$@" <origen abs> <destino abs> <grupo>.
# Lo usan install.sh (link_one) y dotfiles-doctor.sh (verificación).
manifest_each() {
    local cb="$1" src dst group s
    while IFS=$'\t' read -r src dst group; do
        [[ -z "$src" || "$src" == \#* ]] && continue
        case "$group" in
            core) ;;
            hyprland) $WITH_HYPRLAND || continue ;;
            x11) $WITH_X11 || continue ;;
            *) continue ;;
        esac
        s="$DOTFILES_DIR/$src"; [[ "$src" == "." ]] && s="$DOTFILES_DIR"
        "$cb" "$s" "$HOME/$dst" "$group"
    done < "$DOTFILES_DIR/manifest/links.tsv"
}

step_links() {
    header "Enlaces simbólicos"
    manifest_each _link_cb
    [[ -n "$_BACKUP_DIR" ]] && info "Lo que ya existía se movió a $_BACKUP_DIR"
    return 0
}

_link_cb() { link_one "$1" "$2"; }
