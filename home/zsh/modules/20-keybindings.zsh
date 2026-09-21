# ====== KEYBINDINGS ======
# Teclas de función para Kitty

# Cargar módulo terminfo para acceder a $terminfo
zmodload zsh/terminfo 2>/dev/null

# ========================================
# Teclas de función estándar
# ========================================

# Inicio / Fin (línea actual)
bindkey "$terminfo[khome]" beginning-of-line   # Home → principio de línea
bindkey "$terminfo[kend]"  end-of-line         # End → fin de línea

# Alternativas: algunos terminales envían ^[[H / ^[[F en vez de ^[OH / ^[OF
bindkey '^[[H' beginning-of-line
bindkey '^[[F' end-of-line

# Av Pág / Re Pág (historial)
bindkey "$terminfo[kpp]" beginning-of-buffer-or-history   # Re Pág → principio del historial
bindkey "$terminfo[knp]" end-of-buffer-or-history         # Av Pág → fin del historial

# Insert / Supr
bindkey "$terminfo[kich1]" overwrite-mode   # Insert → toggle insert/overwrite
bindkey "$terminfo[kdch1]" delete-char      # Supr → borrar caracter bajo cursor

# ========================================
# Navegación con Ctrl + flechas
# ========================================

# Ctrl + ← / → (saltar palabras)
bindkey '^[[1;5C' forward-word    # Ctrl + →
bindkey '^[[1;5D' backward-word   # Ctrl + ←

# Alternativas para Ctrl + flechas (según terminal)
bindkey '^[OC' forward-word
bindkey '^[OD' backward-word

# ========================================
# Atajos adicionales útiles
# ========================================

# Ctrl + Retroceso → borrar palabra anterior
bindkey '^H' backward-kill-word
# Ctrl + Supr → borrar palabra siguiente (si el terminal lo soporta)
bindkey '^[[3;5~' kill-word
