#!/usr/bin/env bash
# build-wiki.sh — genera las páginas de la wiki de GitHub a partir de docs/.
#   - docs/<doc>.md      -> <Página>.md (sin el título: la wiki lo toma del nombre)
#   - docs/wiki/*.md     -> tal cual (Home, _Sidebar, _Footer)
#   - enlaces entre docs -> enlaces entre páginas; rutas del repo (../x) -> URL en GitHub
# Uso: scripts/build-wiki.sh DIR     (DIR = clone del repo <repo>.wiki.git)
# El workflow .github/workflows/wiki.yml lo corre en cada push a main que toque docs/.
set -euo pipefail

ROOT="$(cd -P "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="${1:?Uso: build-wiki.sh DIR}"
[[ -d "$OUT" ]] || { echo "No existe $OUT" >&2; exit 2; }

REPO="${GITHUB_REPOSITORY:-D4rkDr4gon/D4rkFiles}"
BLOB="https://github.com/$REPO/blob/main"

# doc -> nombre de página. Una página nueva de docs/ se agrega acá y en docs/wiki/_Sidebar.md.
declare -A PAGES=(
    [installation]=Instalación
    [customization]=Personalización
    [structure]=Estructura
    [themes]=Temas
    [design-system]=Sistema-de-diseño
    [keybindings]=Atajos
    [components]=Componentes
    [settings]=Settings
    [scripts]=Scripts
    [security]=Seguridad
    [ai-skill]=Skill-de-IA
    [troubleshooting]=Problemas-frecuentes
)

# Borra las páginas generadas antes (menos .git) para que no queden huérfanas.
find "$OUT" -mindepth 1 -maxdepth 1 -name '*.md' -delete

# sed que reescribe los enlaces: ](doc.md#x) -> ](Página#x) y ](../ruta) -> ](URL)
rules=()
for doc in "${!PAGES[@]}"; do
    rules+=(-e "s#\]\($doc\.md(\#[^)]*)?\)#](${PAGES[$doc]}\1)#g")
done
rules+=(-e "s#\]\(\.\./([^)]*)\)#]($BLOB/\1)#g")

missing=0
for f in "$ROOT"/docs/*.md; do
    doc="$(basename "$f" .md)"
    page="${PAGES[$doc]:-}"
    [[ -n "$page" ]] || { echo "  ✗ docs/$doc.md no tiene página en PAGES" >&2; missing=1; continue; }
    sed '1{/^# /d}' "$f" | sed '1{/^$/d}' | sed -E "${rules[@]}" > "$OUT/$page.md"
done
cp "$ROOT"/docs/wiki/*.md "$OUT/"

((missing)) && exit 1
echo "Wiki generada en $OUT ($(find "$OUT" -maxdepth 1 -name '*.md' | wc -l) páginas)"
