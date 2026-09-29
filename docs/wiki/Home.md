<p align="center">
<img src="https://raw.githubusercontent.com/D4rkDr4gon/D4rkFiles/main/config/waybar/logo.png" alt="Logo de D4rkFiles" width="140">
</p>

**D4rkFiles** son dotfiles de Arch Linux con dos sesiones —**Hyprland** (Wayland) y **Qtile** (X11)— y un
motor de temas: cambiás de tema y cambian a la vez el borde de las ventanas, waybar, rofi, kitty, dunst,
Neovim, Firefox, la pantalla de login y unas veinte cosas más.

Está pensado para que **cualquiera lo instale**: no asume usuario, ruta de clone, monitores, teclado,
batería ni GPU. Lo tuyo (nombre, apps, atajos propios) vive fuera del repo, en `~/.config/dotfiles/`.

<p align="center">
<img src="https://raw.githubusercontent.com/D4rkDr4gon/D4rkFiles/main/assets/screenshots/escritorio.jpg" alt="Escritorio con el tema red-dark en Hyprland" width="100%">
</p>

## Empezar en 5 minutos

```bash
git clone https://github.com/D4rkDr4gon/D4rkFiles.git
cd D4rkFiles
./install.sh --dry-run     # ver qué haría, sin tocar nada
./install.sh
```

Después de reiniciar la sesión:

```bash
theme                          # lista los 17 temas
theme nord                     # aplica uno
scripts/dotfiles-doctor.sh     # verifica la instalación
```

`Super+Return` terminal · `Super+Space` buscador · `Super+Shift+Space` Settings · `Super+K` todos los atajos.

El instalador es idempotente y **no borra nada**: lo que reemplaza queda en
`~/.local/state/dotfiles/backups/<fecha>/`.

## ¿Qué estás buscando?

| Quiero… | Leé |
|---|---|
| Instalarlo, ver las opciones o desinstalarlo | [[Instalación]] |
| Poner mi nombre, monitores, wallpapers, VPN, webapps o modos de escritorio | [[Personalización]] |
| Aprender los atajos | [[Atajos]] |
| Cambiar de tema o crear uno | [[Temas]] · [[Sistema de diseño|Sistema-de-diseño]] |
| Saber qué hace cada pieza del escritorio | [[Componentes]] |
| Encontrar dónde está cada archivo | [[Estructura]] |
| Usar las herramientas (doctor, update, theme…) | [[Scripts]] |
| Pedirle cambios a Claude Code u opencode | [[Skill de IA|Skill-de-IA]] |
| Saber qué datos personales quedan fuera del repo | [[Seguridad]] |
| Arreglar algo que no anda | [[Problemas frecuentes|Problemas-frecuentes]] |

## Stack

| Área | Hyprland (Wayland) | Qtile (X11) |
|---|---|---|
| WM | Hyprland + hyprpaper + hyprshell | Qtile + picom |
| Barra | waybar | polybar |
| Launcher | rofi (+ walker/elephant) | rofi |
| Bloqueo / login | gtklock · SDDM | betterlockscreen / i3lock · SDDM |
| Común | kitty · zsh + powerlevel10k · dunst · Neovim (LazyVim) · herdr · lazygit · Thunar | |
