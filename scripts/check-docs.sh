#!/usr/bin/env bash
# check-docs.sh — verifica que la documentación no apunte a cosas que no existen.
#   1. Enlaces markdown relativos [texto](ruta) -> el archivo existe.
#   2. Rutas del repo entre `backticks` (scripts/x.sh, config/..., docs/...) -> existen
#      (o existe su plantilla .tpl, o están en .gitignore como archivos generados).
# Uso: scripts/check-docs.sh        Salida: 0 sin problemas · 1 con problemas
set -uo pipefail

ROOT="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
cd "$ROOT" || exit 2

bad=0
report() { printf '  ✗ %s: %s\n' "$1" "$2"; bad=$((bad + 1)); }

mapfile -t docs < <(git ls-files --cached --others --exclude-standard '*.md' 2>/dev/null || find . -name '*.md' -not -path './.git/*')

for f in "${docs[@]}"; do
    dir="$(dirname "$f")"

    # 1) enlaces relativos
    while IFS= read -r link; do
        target="${link%%#*}"
        [[ -z "$target" || "$target" =~ ^(https?:|mailto:) ]] && continue
        [[ -e "$dir/$target" ]] || report "$f" "enlace roto -> $link"
    done < <(grep -oE '\]\([^)]+\)' "$f" | sed -E 's/^\]\(//; s/\)$//')

    # 2) rutas del repo entre backticks
    while IFS= read -r p; do
        p="${p%/}"; p="${p#./}"
        [[ "$p" == *'*'* || "$p" == *'<'* || "$p" == *'{'* || "$p" == *'…'* ]] && continue
        [[ -e "$p" || -e "$p.tpl" ]] && continue
        git check-ignore -q "$p" 2>/dev/null && continue
        report "$f" "ruta inexistente: $p"
    done < <(grep -oE '`(scripts|config|home|system|install|manifest|tools|themes|assets|docs|skills)/[A-Za-z0-9_./-]+`' "$f" | tr -d '`' | sort -u)
done

if ((bad)); then echo "$bad problema(s) en la documentación"; exit 1; fi
echo "Documentación: sin enlaces ni rutas rotas (${#docs[@]} archivos)"
