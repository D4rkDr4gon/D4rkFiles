#!/usr/bin/env bash
# Buscador único (Mod+Space) — combina drun (apps) + run (comandos de $PATH)
# en una sola lista/caja, con spotlight-fallback.sh como catch-all de lo que
# no matchea nada (comando con args → calculadora → búsqueda web). Ver
# docs/design-system.md para la arquitectura completa y sus limitaciones.
exec rofi \
    -modi "combi,drun,run,spotlight:$HOME/.config/rofi/scripts/spotlight-fallback.sh" \
    -show combi \
    -combi-modi "spotlight,drun,run" \
    -theme "$HOME/.config/rofi/theme-drun.rasi"
