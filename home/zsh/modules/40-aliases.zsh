# ====== ALIASES ======

# Dotfiles
alias theme="$DOTFILES/scripts/theme-switch.sh"
alias barupdate="$DOTFILES/scripts/barupdate.sh"
alias dotfiles-update="$DOTFILES/scripts/dotfiles-update.sh"
alias dotfiles-doctor="$DOTFILES/scripts/dotfiles-doctor.sh"
alias dotfiles="cd $DOTFILES"
alias zshconfig="${EDITOR:-nvim} ~/.zshrc"
alias logo="$DOTFILES/scripts/logo.sh"

# Editor y visor
alias vi="nvim"
if command -v bat >/dev/null; then
  alias cat='bat'
  alias catn='command cat'
  alias catnl='bat --paging=never'
fi

# Listados
if command -v lsd >/dev/null; then
  alias ls='lsd --group-dirs=first'
  alias l='lsd --group-dirs=first'
  alias la='lsd -a --group-dirs=first'
  alias ll='lsd -la --group-dirs=first'
  alias lla='lsd -lha --group-dirs=first'
fi

# Navegación
alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."

# Sistema
command -v btop >/dev/null && alias top='btop'
command -v uv >/dev/null && alias venv='uv venv'
alias c="clear"
alias q="exit"
alias hosts="sudo ${EDITOR:-nvim} /etc/hosts"
alias vpnfail="sudo systemctl restart systemd-resolved"
ischarging() { cat /sys/class/power_supply/BAT*/status 2>/dev/null || echo "sin batería"; }

# VPN vía NetworkManager: definí VPN_PROFILE en ~/.config/dotfiles/user.conf
# (nombre exacto de tu conexión, `nmcli connection show`).
if [[ -n "$VPN_PROFILE" ]]; then
  alias vpnup="nmcli connection up \"$VPN_PROFILE\""
  alias vpndown="nmcli connection down \"$VPN_PROFILE\""
fi

# Pantalla compartida por VNC (segundo monitor, ver docs/components.md)
alias vnc-on="$DOTFILES/scripts/wayland/wayvnc-toggle.sh on"
alias vnc-off="$DOTFILES/scripts/wayland/wayvnc-toggle.sh off"
alias vnc-status="$DOTFILES/scripts/wayland/wayvnc-toggle.sh status"

# Herramientas de ciberseguridad (solo si están instaladas)
[[ -x "$HOME/.cargo/bin/ThreatDeck" ]] && alias threatdeck="$HOME/.cargo/bin/ThreatDeck"

# Ollama (solo si está instalado)
if command -v ollama >/dev/null; then
  alias ollama-ps='curl -s http://localhost:11434/api/ps | python3 -m json.tool 2>/dev/null'
fi
