#!/usr/bin/env bash
# Widget "Agentes IA": delega en el lanzador generico de TUIs flotantes
# (ver float-tui-launch.sh). El ancho (92 columnas) queda fijo porque el
# separador y las columnas de las filas de agente ya dibujan a ese ancho
# siempre — pero el ALTO se calcula antes de abrir la ventana, contando
# cuantas filas ocupa el contenido con la cantidad de agentes abiertos AHORA
# (claude-agents-tui.sh --rows), asi no queda un espacio vacio pensado para
# el peor caso (3 agentes + "+N mas" en cada seccion) cuando hay menos.
TUI="$HOME/.config/waybar/scripts/claude-agents-tui.sh"
COLS=92
ROWS=$(bash "$TUI" --rows 2>/dev/null)
[ -n "$ROWS" ] && [ "$ROWS" -gt 0 ] 2>/dev/null || ROWS=24
# Colchon minimo/maximo por las dudas (contenido corrupto, cache gigante, etc).
[ "$ROWS" -lt 14 ] && ROWS=14
[ "$ROWS" -gt 26 ] && ROWS=26

exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    claude-agents 'Agentes IA' "$COLS" "$ROWS" \
    bash "$TUI"
