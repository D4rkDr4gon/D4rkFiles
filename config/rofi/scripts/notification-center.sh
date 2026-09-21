#!/bin/bash
# Notification Center - Rofi + Dunst
# Muestra el historial y permite ver el texto completo sin cerrar notis.
# Opción "Clear all" para limpiar el historial.

ROFI_THEME="$HOME/.config/rofi/theme.rasi"

while true; do
    COUNT=$(dunstctl count history 2>/dev/null)

    entries=()
    ids=()
    summaries=()
    bodies=()

    if [ "$COUNT" -gt 0 ] 2>/dev/null; then
        while IFS=$'\t' read -r id summary body; do
            entries+=("$summary")
            ids+=("$id")
            summaries+=("$summary")
            bodies+=("$body")
        done < <(dunstctl history | jq -r '.data[][] | [.id.data, .summary.data, .body.data] | @tsv' 2>/dev/null)
    fi

    urgent_idx=()

    urgent_idx+=(${#entries[@]})
    entries+=("No Molestar")
    ids+=("dnd")

    if [ "$COUNT" -gt 0 ] 2>/dev/null; then
        urgent_idx+=(${#entries[@]})
        entries+=("󰧧  Clear all notifications")
        ids+=("clear")
    fi

    urgent_csv=$(IFS=,; echo "${urgent_idx[*]}")

    selected=$(printf '%s\n' "${entries[@]}" | rofi -dmenu -i \
        -p "Notifications ($COUNT)" \
        -theme "$ROFI_THEME" \
        -no-custom \
        -u "$urgent_csv" \
        -format i)

    [[ -z "$selected" || ! "$selected" =~ ^[0-9]+$ ]] && exit 0

    if [ "${ids[$selected]}" = "dnd" ]; then
        bash "$(dirname "$0")/dnd-menu.sh"
        continue
    elif [ "${ids[$selected]}" = "clear" ]; then
        dunstctl history-clear
        continue
    elif [ "$selected" -lt "${#ids[@]}" ]; then
        full="${summaries[$selected]}"
        if [ -n "${bodies[$selected]}" ]; then
            full="${summaries[$selected]}

${bodies[$selected]}"
        fi
        rofi -e "$full" -theme "$ROFI_THEME"
        continue
    fi
done
