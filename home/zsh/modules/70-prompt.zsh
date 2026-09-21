# ====== POWERLEVEL10K ======
# Instalado por install.sh en ~/.local/share/zsh/powerlevel10k (o el paquete del sistema).
# Para personalizar: `p10k configure` (escribe ~/.p10k.zsh, que tiene prioridad sobre la base del repo).

if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

for _p10k in "${XDG_DATA_HOME:-$HOME/.local/share}/zsh/powerlevel10k/powerlevel10k.zsh-theme" \
             /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme; do
  [[ -r "$_p10k" ]] && { source "$_p10k"; break; }
done
unset _p10k

if [[ -r ~/.p10k.zsh ]]; then
  source ~/.p10k.zsh
elif [[ -r "$DOTFILES/home/zsh/p10k.zsh" ]]; then
  source "$DOTFILES/home/zsh/p10k.zsh"
fi
