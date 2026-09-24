#!/usr/bin/env bash
# Regla [notif_jump_record] de dunstrc: corre en cada notificación y anota
# id -> app para que scripts/wayland/notif-jump.py sepa a qué ventana saltar cuando
# se hace click del medio. Formato: id<TAB>appname<TAB>desktop_entry.

LOG="${XDG_RUNTIME_DIR:-/tmp}/dunst-notif-apps.tsv"
printf '%s\t%s\t%s\n' "$DUNST_ID" "$DUNST_APP_NAME" "$DUNST_DESKTOP_ENTRY" >> "$LOG"

# Solo interesan las recientes: se recorta a las últimas 200.
if [ "$(wc -l < "$LOG")" -gt 400 ]; then
    tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
