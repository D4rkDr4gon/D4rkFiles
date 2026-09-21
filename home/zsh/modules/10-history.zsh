# ====== HISTORIAL ======
HISTSIZE=100000
SAVEHIST=100000
HISTFILE=~/.zsh_history

setopt append_history      # añadir en lugar de sobrescribir
setopt share_history       # compartir entre sesiones concurrentes
setopt inc_append_history  # escribir al archivo inmediatamente
setopt extended_history    # guardar timestamps
setopt hist_ignore_dups    # ignorar duplicados consecutivos
setopt hist_ignore_space   # no guardar comandos que empiezan con espacio
