#!/usr/bin/env bash
# Gestor de gastos (Mod+G, widget Money, Settings → Finances): ventana centrada
# con tools/expenses_tui.py (ver center-tui-launch.sh).
exec bash "$HOME/.config/waybar/scripts/center-tui-launch.sh" expenses 'Expenses' \
    python3 "${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/tools/expenses_tui.py"
