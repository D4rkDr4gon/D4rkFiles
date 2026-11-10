#!/usr/bin/env bash
# launch.sh — arranca el daemon de Quickshell (la GUI propia) solo en modo gui.
# Lo lanza hyprland.lua (exec-once) y Settings al cambiar de modo. En modo tui,
# o sin Quickshell, no hace nada. Idempotente: si ya hay un daemon, no arranca otro.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ "$("$here/../scripts/ui-mode.sh")" = gui ] || exit 0
command -v qs >/dev/null 2>&1 || exit 0
[ -f "$here/shell.qml" ] || exit 0
# `qs list` sale 0 aunque no haya daemon (lista instancias muertas): ipc show sí falla.
# Un daemon trabado tras recargar la config contesta "Not ready" (y sale 0): si sigue así
# unos segundos, se reinicia.
alive() { local out; out=$(qs -p "$here" ipc show 2>&1) || return 1; case "$out" in *"Not ready"*) return 2 ;; esac; return 0; }
alive; st=$?
for _ in 1 2 3 4 5 6; do [ "$st" = 2 ] || break; sleep 0.5; alive; st=$?; done
[ "$st" = 0 ] && exit 0
[ "$st" = 2 ] && { qs -p "$here" kill >/dev/null 2>&1; sleep 0.5; }
exec qs -p "$here" -d
