#!/usr/bin/env bash
# logo.sh — muestra el logo del proyecto (dragón + banner) en la terminal.
# El arte está en assets/; el nombre y el título salen de ~/.config/dotfiles/user.conf.

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
DOTFILES_DIR="$(cd -P "$(dirname "$SELF")/.." && pwd)"
export DOTFILES_DIR
# shellcheck source=lib/env.sh
source "$DOTFILES_DIR/scripts/lib/env.sh"

color=$'\033[0;31m'
[[ -r "$DOTFILES_DIR/home/zsh/colors.zsh" ]] && color="$(sed -n "s/^export COLOR_BANNER=\$'\(.*\)'$/\1/p" "$DOTFILES_DIR/home/zsh/colors.zsh")" && color="$(printf '%b' "$color")"
reset=$'\033[0m'

mapfile -t dragon < "$DOTFILES_DIR/assets/dragon.txt"
mapfile -t banner < <(df_banner)

# El banner arranca en la fila 5 del dragón, como siempre.
echo
for i in "${!dragon[@]}"; do
    b=""
    if (( i >= 4 && i - 4 < ${#banner[@]} )); then
        b="${banner[$((i - 4))]}"
        b="${b/>>> />>> ${reset}}"; b="${b/ <<</${color} <<<}"
    fi
    printf ' %s%s %s    %s%s\n' "$reset" "${dragon[$i]}" "$color" "$b" "$reset"
done
echo
