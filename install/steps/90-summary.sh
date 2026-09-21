#!/usr/bin/env bash
# Etapa: summary — resumen y próximos pasos.

step_summary() {
    header "Listo"
    if $DRY_RUN; then
        echo "  --dry-run: no se modificó nada."
        return 0
    fi
    cat <<MSG
  Próximos pasos:
    1. Cerrá sesión y elegí Hyprland$($WITH_X11 && echo " o Qtile") en tu login manager.
    2. Cambiá de tema:       theme            (lista)   |   theme <nombre>
    3. Tus ajustes:          ~/.config/dotfiles/user.conf y ~/.config/dotfiles/hypr/local.conf
    4. Verificar todo:       scripts/dotfiles-doctor.sh
  Atajos básicos: Super+Enter (terminal) · Super+Space (launcher) · Super+K (todos los atajos)
  Lo reemplazado quedó respaldado en: ${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/backups/
MSG
}
