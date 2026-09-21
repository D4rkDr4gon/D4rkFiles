# ====== BANNER AL ABRIR LA TERMINAL ======
# El arte es el del proyecto (assets/banner-art.txt); el nombre y el título salen de
# ~/.config/dotfiles/user.conf. scripts/theme-switch.sh genera home/zsh/banner.txt.
# Desactivable con DOTFILES_NO_BANNER=1. Va antes del prompt (instant prompt de p10k).

if [[ -o interactive && -z "$DOTFILES_NO_BANNER" && -r "$DOTFILES/home/zsh/banner.txt" ]]; then
  _c=${COLOR_BANNER:-$'\033[0;31m'}
  _r=$'\033[0m'
  print -r -- ""
  while IFS= read -r _line; do
    # El texto entre ">>>" y "<<<" va en el color normal; el resto, en el del tema.
    _line=${_line/>>> />>> ${_r}}
    _line=${_line/ <<</${_c} <<<}
    print -r -- "    ${_c}${_line}${_r}"
  done < "$DOTFILES/home/zsh/banner.txt"
  unset _c _r _line
fi
