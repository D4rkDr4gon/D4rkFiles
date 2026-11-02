#!/usr/bin/env bash
# OCR de una región de pantalla: elegís un recuadro con slurp, grim lo captura,
# tesseract lee el texto y queda en el portapapeles (Mod+Shift+O).
# Necesita: grim slurp tesseract wl-clipboard (+ tesseract-data-spa / -eng).
set -u

notify() { notify-send "OCR" "$1" -t 2500; }

for cmd in grim slurp tesseract wl-copy; do
    command -v "$cmd" >/dev/null || { notify "Falta $cmd (sudo pacman -S tesseract tesseract-data-spa tesseract-data-eng)"; exit 1; }
done

# Idiomas: español + inglés si están instalados; si no, los que haya.
langs=""
for l in spa eng; do
    tesseract --list-langs 2>/dev/null | grep -qx "$l" && langs="${langs:+$langs+}$l"
done
[ -n "$langs" ] || { notify "Sin datos de idioma (sudo pacman -S tesseract-data-spa tesseract-data-eng)"; exit 1; }

region=$(slurp) || exit 0          # esc = cancelar, sin aviso

tmp=$(mktemp --suffix=.png)
trap 'rm -f "$tmp"' EXIT
grim -g "$region" "$tmp" || { notify "No se pudo capturar"; exit 1; }

# --psm 6: el recuadro elegido es un bloque de texto uniforme (evita líneas en blanco de más).
# Mejora la lectura del texto chico de pantalla: agranda, pasa a grises y, si el
# fondo es oscuro (tu tema lo es casi siempre), invierte para que quede texto negro.
if command -v magick >/dev/null; then
    mean=$(magick "$tmp" -colorspace Gray -format '%[fx:mean]' info: 2>/dev/null || echo 1)
    neg=()
    awk -v m="$mean" 'BEGIN { exit !(m < 0.5) }' && neg=(-negate)
    magick "$tmp" -colorspace Gray "${neg[@]}" -resize 250% "$tmp"
fi

text=$(tesseract "$tmp" stdout -l "$langs" --psm 6 2>/dev/null | sed -e 's/[[:space:]]*$//' | cat -s)
text="${text#"${text%%[![:space:]]*}"}"    # recorta saltos de línea al principio

if [ -z "$text" ]; then
    notify "No se encontró texto"
    exit 0
fi

printf '%s' "$text" | wl-copy
first=$(printf '%s' "$text" | head -n1 | cut -c1-70)
notify "Copiado: $first"
