#!/usr/bin/env bash
#===============================================================================
# D4rkFiles — instalador de dotfiles para Arch Linux (Hyprland + Qtile)
#
#   Una línea (clona el repo y sigue):
#     bash <(curl -fsSL https://raw.githubusercontent.com/D4rkDr4gon/D4rkFiles/main/install.sh)
#
#   Desde un clone:   ./install.sh [opciones]
#
# Es idempotente y no destruye nada: lo que reemplaza se mueve a
# ~/.local/state/dotfiles/backups/<fecha>/. Probalo primero con --dry-run.
#===============================================================================
# shellcheck disable=SC2034  # las etapas (install/steps/*.sh) leen las variables de flags
set -euo pipefail

DOTFILES_REPO="${DOTFILES_REPO:-https://github.com/D4rkDr4gon/D4rkFiles.git}"
DEFAULT_CLONE_DIR="$HOME/D4rkFiles"

usage() {
    cat <<'EOF'
Uso: install.sh [opciones]

Qué instalar:
  --no-wayland        No instala la sesión Hyprland (solo Qtile/X11)
  --no-x11            No instala la sesión Qtile/X11 (solo Hyprland)
  --no-aur            No usa el AUR (ni instala yay)
  --no-upgrade        No ofrece `pacman -Syu` antes de instalar
  --with-ollama       Instala Ollama (IA local) sin preguntar

Cómo ejecutarlo:
  -n, --dry-run       Muestra lo que haría, sin modificar nada
  -y, --yes           No pregunta: usa los valores por defecto (los opcionales quedan en "no")
  --only a,b,c        Corre solo esas etapas
  --skip a,b,c        Salta esas etapas
  --configure         Atajo de: --only configure (crea user.conf y renderiza el tema)
  --dir RUTA          Dónde está (o se clonará) el repo. Por defecto: donde está este script
  --list-stages       Lista las etapas y termina
  -h, --help          Esta ayuda

Etapas (en orden): preflight packages configure links shell system optional summary
(configure va antes de links: renderiza las plantillas que luego se enlazan)

Variables: DOTFILES_REPO (URL del repo), DOTFILES_DIR (equivale a --dir).
EOF
}

#--- Argumentos ---------------------------------------------------------------
DRY_RUN=false; ASSUME_YES=false
WITH_HYPRLAND=true; WITH_X11=true; USE_AUR=true; DO_UPGRADE=true; WITH_OLLAMA=false
ONLY=""; SKIP=""; CLONE_DIR="${DOTFILES_DIR:-}"
ALL_STAGES=(preflight packages configure links shell system optional summary)

while (($#)); do
    case "$1" in
        -h|--help)      usage; exit 0 ;;
        -n|--dry-run)   DRY_RUN=true ;;
        -y|--yes)       ASSUME_YES=true ;;
        --no-wayland)   WITH_HYPRLAND=false ;;
        --no-x11)       WITH_X11=false ;;
        --no-aur)       USE_AUR=false ;;
        --no-upgrade)   DO_UPGRADE=false ;;
        --with-ollama)  WITH_OLLAMA=true ;;
        --configure)    ONLY="configure" ;;
        --only)         shift; ONLY="${1:?--only necesita una lista}" ;;
        --skip)         shift; SKIP="${1:?--skip necesita una lista}" ;;
        --dir)          shift; CLONE_DIR="${1:?--dir necesita una ruta}" ;;
        --list-stages)  printf '%s\n' "${ALL_STAGES[@]}"; exit 0 ;;
        *)              echo "Opción desconocida: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done
$WITH_HYPRLAND || $WITH_X11 || { echo "Error: --no-wayland y --no-x11 juntos no dejan nada que instalar." >&2; exit 2; }

#--- Ubicación del repo (y bootstrap si se ejecutó vía curl) --------------------
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]:-$0}" 2>/dev/null || true)"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

if [[ -f "$SCRIPT_DIR/install/lib/common.sh" && -z "$CLONE_DIR" ]]; then
    DOTFILES_DIR="$SCRIPT_DIR"                  # ejecutado desde un clone
else
    DOTFILES_DIR="$(readlink -m "${CLONE_DIR:-$DEFAULT_CLONE_DIR}")"
    if [[ ! -f "$DOTFILES_DIR/install/lib/common.sh" ]]; then
        # Bootstrap: sin el repo no hay etapas. Se clona y se vuelve a ejecutar desde ahí.
        command -v git >/dev/null 2>&1 || { echo "Error: falta git (sudo pacman -S git)." >&2; exit 1; }
        if $DRY_RUN; then
            echo "[dry-run] git clone $DOTFILES_REPO $DOTFILES_DIR"
            echo "[dry-run] (luego se ejecutaría el install.sh del clone con las mismas opciones)"
            exit 0
        fi
        [[ -e "$DOTFILES_DIR" ]] && { echo "Error: $DOTFILES_DIR existe y no es este repo. Usá --dir." >&2; exit 1; }
        echo "Clonando $DOTFILES_REPO en $DOTFILES_DIR ..."
        git clone --depth=1 "$DOTFILES_REPO" "$DOTFILES_DIR"
        exec "$DOTFILES_DIR/install.sh" --dir "$DOTFILES_DIR" "$@"
    fi
fi
export DOTFILES_DIR

# shellcheck source=install/lib/common.sh
source "$DOTFILES_DIR/install/lib/common.sh"
# shellcheck source=scripts/lib/env.sh
source "$DOTFILES_DIR/scripts/lib/env.sh"
for step_file in "$DOTFILES_DIR"/install/steps/*.sh; do
    # shellcheck source=/dev/null
    source "$step_file"
done

#--- Selección de etapas -------------------------------------------------------
_in_list() { [[ ",$2," == *",$1,"* ]]; }
for _l in $(tr ',' ' ' <<<"$ONLY $SKIP"); do
    printf '%s\n' "${ALL_STAGES[@]}" | grep -qx "$_l" || die "Etapa desconocida: $_l (ver --list-stages)"
done

main() {
    printf '%sD4rkFiles%s — dotfiles para Arch Linux\n' "$C_BLUE" "$C_RESET"
    $DRY_RUN && warn "Modo --dry-run: no se modifica nada."

    local stage
    for stage in "${ALL_STAGES[@]}"; do
        [[ -n "$ONLY" ]] && ! _in_list "$stage" "$ONLY" && continue
        [[ -n "$SKIP" ]] && _in_list "$stage" "$SKIP" && continue
        # preflight solo hace falta si se va a tocar el sistema (paquetes/servicios)
        if [[ "$stage" == preflight && -n "$ONLY" ]] && ! _in_list packages "$ONLY" && ! _in_list system "$ONLY" && ! _in_list optional "$ONLY"; then
            continue
        fi
        "step_$stage"
    done
}

main
