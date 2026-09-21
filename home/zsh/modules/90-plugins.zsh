# ====== PLUGINS ======
# Se usan los paquetes del sistema (pacman) y, si no están, la copia que
# install.sh clona en ~/.local/share/zsh/. Cada uno es opcional.

_zsh_plugin() {  # _zsh_plugin <nombre> <archivo>
  local f
  for f in "/usr/share/zsh/plugins/$1/$2" "${XDG_DATA_HOME:-$HOME/.local/share}/zsh/$1/$2"; do
    [[ -r "$f" ]] && { source "$f"; return 0; }
  done
  return 1
}

_zsh_plugin zsh-autosuggestions zsh-autosuggestions.zsh
_zsh_plugin zsh-syntax-highlighting zsh-syntax-highlighting.zsh   # va al final, como pide su documentación
unfunction _zsh_plugin
