#!/usr/bin/env bash
# Gestor de monitores (hyprmon): delega en el lanzador generico de TUIs
# flotantes (float-tui-launch.sh). Tamaño generoso porque hyprmon dibuja un
# "desk map" espacial (cajas proporcionales a cada monitor) y necesita lugar
# para no verse recortado.
exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    hyprmon 'Monitores' 110 34 \
    hyprmon
