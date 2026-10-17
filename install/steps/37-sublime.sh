#!/usr/bin/env bash
# Etapa: sublime — deja Sublime Text listo para instalar sus paquetes.
# config/sublime-text/Packages/User/Package Control.sublime-settings lista los paquetes (Terminus,
# esquemas de color), pero Sublime solo los baja si el paquete "Package Control" ya está en
# "Installed Packages". Acá se descarga una vez, desde el sitio oficial (el mismo método que
# documenta packagecontrol.io/installation), y al abrir Sublime instala el resto solo.

SUBLIME_PC_URL="https://packagecontrol.io/Package%20Control.sublime-package"

step_sublime() {
    header "Sublime Text (Package Control)"
    if ! command -v subl >/dev/null 2>&1 && ! command -v sublime_text >/dev/null 2>&1; then
        info "Sublime Text no está instalado: se omite"
        return 0
    fi
    local dir="${XDG_CONFIG_HOME:-$HOME/.config}/sublime-text/Installed Packages"
    local pkg="$dir/Package Control.sublime-package"
    if [[ -s "$pkg" ]]; then
        log "Package Control ya está instalado"
        return 0
    fi
    command -v curl >/dev/null 2>&1 || { warn "Falta curl: no se pudo bajar Package Control"; return 0; }

    if $DRY_RUN; then
        echo "[dry-run] curl $SUBLIME_PC_URL -> ${pkg/#"$HOME"/\~}"
        return 0
    fi
    local tmp; tmp="$(mktemp)"
    # Un .sublime-package es un zip: se valida antes de dejarlo en su lugar
    if curl -fsSL --max-time 60 -o "$tmp" "$SUBLIME_PC_URL" \
        && python3 -c 'import sys, zipfile; sys.exit(1 if zipfile.ZipFile(sys.argv[1]).testzip() else 0)' "$tmp" 2>/dev/null; then
        mkdir -p "$dir" && chmod 644 "$tmp" && mv -f "$tmp" "$pkg"
        log "Package Control instalado: al abrir Sublime baja Terminus y los esquemas de color"
    else
        rm -f "$tmp"
        warn "No se pudo bajar Package Control; reintentá con ./install.sh --only sublime"
    fi
}
