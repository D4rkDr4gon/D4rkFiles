# ====== ENTORNO ======

# Configuración por usuario (KEY=VALUE), la misma que usan los scripts y Hyprland/Qtile.
_dotfiles_conf="${XDG_CONFIG_HOME:-$HOME/.config}/dotfiles/user.conf"
[[ -r "$_dotfiles_conf" ]] && { set -a; source "$_dotfiles_conf"; set +a; }
unset _dotfiles_conf
: "${USER_DISPLAY_NAME:=${$(getent passwd "$USER" 2>/dev/null | cut -d: -f5 | cut -d, -f1):-$USER}}"

# PATH (solo agrega lo que existe; sin duplicados)
typeset -U path
for _p in "$HOME/.local/bin" "$HOME/.cargo/bin" "$HOME/.opencode/bin"; do
  [[ -d "$_p" ]] && path=("$_p" $path)
done
unset _p

# Colores del tema activo (los genera scripts/theme-switch.sh)
[[ -r "$DOTFILES/home/zsh/colors.zsh" ]] && source "$DOTFILES/home/zsh/colors.zsh"

# Ollama: un hilo por núcleo físico; el resto son valores conservadores.
export OLLAMA_NUM_THREADS="${OLLAMA_NUM_THREADS:-$(nproc 2>/dev/null || echo 4)}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-5m}"
