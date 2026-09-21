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
            skills) $WITH_SKILLS || continue ;;
            *) continue ;;
        esac
        s="$DOTFILES_DIR/$src"; [[ "$src" == "." ]] && s="$DOTFILES_DIR"
        "$cb" "$s" "$HOME/$dst" "$group"
    done < "$DOTFILES_DIR/manifest/links.tsv"
}

# Activa la statusline de Claude Code (alimenta el widget "Agentes IA" de waybar).
# Solo agrega `statusLine` a ~/.claude/settings.json si NO está definida; nunca pisa la tuya.
_claude_statusline() {
    local settings="$HOME/.claude/settings.json" script="$HOME/.claude/statusline-command.sh"
    [[ -e "$script" ]] || return 0
    command -v jq >/dev/null 2>&1 || { warn "Falta jq: no se configuró la statusline de Claude Code"; return 0; }
    local entry='{"type":"command","command":"bash ~/.claude/statusline-command.sh"}'
    if [[ ! -f "$settings" ]]; then
        if $DRY_RUN; then echo "[dry-run] crear $settings con statusLine"; return 0; fi
        printf '{\n  "statusLine": %s\n}\n' "$entry" | jq . > "$settings"
        log "Claude Code: statusline configurada en ~/.claude/settings.json"
    elif [[ "$(jq -r 'has("statusLine")' "$settings" 2>/dev/null)" == "false" ]]; then
        if $DRY_RUN; then echo "[dry-run] agregar statusLine a $settings (con backup)"; return 0; fi
        local bak; bak="$(backup_dir)/.claude/settings.json"
        mkdir -p "$(dirname "$bak")" && cp -- "$settings" "$bak"
        jq --argjson e "$entry" '. + {statusLine: $e}' "$bak" > "$settings.tmp" && mv -f "$settings.tmp" "$settings"
        log "Claude Code: statusline agregada a ~/.claude/settings.json (backup en $bak)"
    else
        info "Claude Code ya tiene una statusLine configurada: no se toca"
    fi
}

step_links() {
    header "Enlaces simbólicos"
    manifest_each _link_cb
    $WITH_SKILLS && _claude_statusline
    [[ -n "$_BACKUP_DIR" ]] && info "Lo que ya existía se movió a $_BACKUP_DIR"
    return 0
}

_link_cb() { link_one "$1" "$2"; }
