#!/usr/bin/env bash
# Modo "script" de rofi, usado como fallback del buscador único (Mod+Space).
#
# Se registra PRIMERO en -combi-modi (junto a drun,run) — por eso cualquier
# texto tipeado que no matchea ninguna app/comando ("custom entry") se enruta
# acá al presionar Enter (documentado en `man rofi`: "If no match, the input
# is handled by the first combined modes.").
#
# Importante (ver docs/design-system.md): rofi NO vuelve a ejecutar este
# script en cada tecla, solo al presionar Enter sobre texto sin match
# (ROFI_RETV=2, ver `man rofi-script`). Por eso esto es una cascada que actúa
# al confirmar, no un resultado que aparece solo mientras se escribe.
#
# Cascada: 1) comando de shell existente en $PATH → lo ejecuta
#          2) expresión matemática → copia el resultado + notifica
#          3) si no matchea nada de lo anterior → busca en la web

if [[ "$ROFI_RETV" != "2" ]]; then
    # Llamada inicial (RETV=0): no aportamos ninguna fila a la lista visible;
    # todo el contenido de reposo/filtrado en vivo sale de drun+run.
    exit 0
fi

query="$1"
[[ -z "$query" ]] && exit 0

first_word="${query%% *}"

# 1) Comando de shell (cubre casos con argumentos, ej. "firefox --private-window",
#    que el modo "run" nativo no matchea como entrada exacta)
if command -v "$first_word" &>/dev/null; then
    setsid -f bash -c "$query" &>/dev/null
    exit 0
fi

# 2) Calculadora — solo dígitos/operadores/paréntesis/espacios, sin preview
#    en vivo (ver nota de arriba); resultado va al portapapeles + notificación
if [[ "$query" =~ ^[0-9+*/().\ -]+$ ]] && [[ "$query" =~ [0-9] ]]; then
    result=$(python3 -c "print($query)" 2>/dev/null)
    if [[ -n "$result" ]]; then
        echo -n "$result" | wl-copy 2>/dev/null
        notify-send "🧮 $query = $result" "Copiado al portapapeles" -i accessories-calculator 2>/dev/null
        exit 0
    fi
fi

# 3) Fallback: búsqueda web (mismo patrón que rofi/scripts/web-search.sh —
#    cambia al workspace 5, reservado para navegador, y abre ahí la búsqueda)
encoded=$(echo "$query" | sed 's/ /+/g')
if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
    hyprctl dispatch workspace 5 &>/dev/null
else
    qtile cmd-obj -o group "5" -f toscreen &>/dev/null
fi
setsid -f xdg-open "https://www.google.com/search?q=$encoded" &>/dev/null
