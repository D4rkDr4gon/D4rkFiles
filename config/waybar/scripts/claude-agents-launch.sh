#!/usr/bin/env bash
# Widget "Agentes IA": delega en el lanzador generico de TUIs flotantes
# (ver float-tui-launch.sh) con tools/agents_tui.py. El ALTO se calcula antes
# de abrir la ventana segun cuantos agentes hay abiertos AHORA
# (agents_tui.py --rows), asi no queda espacio vacio pensado para el peor
# caso cuando hay menos.
TUI="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/agents_tui.py"
COLS=92
ROWS=$(python3 "$TUI" --rows 2>/dev/null)
[ -n "$ROWS" ] && [ "$ROWS" -gt 0 ] 2>/dev/null || ROWS=20
# Colchon minimo/maximo por las dudas (contenido corrupto, cache gigante, etc).
[ "$ROWS" -lt 12 ] && ROWS=12
[ "$ROWS" -gt 45 ] && ROWS=45

exec bash "$HOME/.config/waybar/scripts/float-tui-launch.sh" \
    claude-agents 'AI Agents' "$COLS" "$ROWS" \
    python3 "$TUI"
