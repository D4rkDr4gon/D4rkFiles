# ====== BANNER AL ABRIR LA TERMINAL ======
# Nombre y título salen de ~/.config/dotfiles/user.conf. Desactivable con
# DOTFILES_NO_BANNER=1. Va antes del prompt para no interferir con el instant prompt de p10k.

if [[ -o interactive && -z "$DOTFILES_NO_BANNER" && -z "$TMUX" ]]; then
  _c=${COLOR_BANNER:-$'\033[0;31m'}
  _r=$'\033[0m'
  _text="${USER_DISPLAY_NAME}${USER_TITLE:+ - $USER_TITLE}"
  _bar="${(l:$(( ${#_text} + 12 ))::=:)}"
  print -r -- "${_c}${_bar}"
  print -r -- "    >>> ${_r}${_text}${_c} <<<"
  print -r -- "${_bar}${_r}"
  unset _c _r _text _bar
fi
