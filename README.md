<p align="center">
  <img src="config/waybar/logo.png" alt="Logo de D4rkFiles" width="160">
</p>

<h1 align="center">D4rkFiles</h1>
<p align="center"><sub>por <a href="https://github.com/D4rkDr4gon">D4rkDr4gon</a></sub></p>

Dotfiles de Arch Linux con dos sesiones —**Hyprland** (Wayland) y **Qtile** (X11)— y un
motor de temas: cambiás de tema y cambian a la vez el borde de las ventanas, waybar, rofi,
kitty, dunst, Neovim, Firefox, la pantalla de login y unas veinte cosas más.

Está pensado para que **cualquiera lo instale**: no asume usuario, ruta de clone, monitores,
teclado, batería ni GPU. Lo tuyo (nombre, apps, atajos propios) vive fuera del repo.

## Instalación

```bash
git clone https://github.com/D4rkDr4gon/D4rkFiles.git
cd D4rkFiles
./install.sh --dry-run     # ver qué haría, sin tocar nada
./install.sh
```

O en una línea: `bash <(curl -fsSL https://raw.githubusercontent.com/D4rkDr4gon/D4rkFiles/main/install.sh)`.

Es idempotente y **no borra nada**: lo que reemplaza queda en
`~/.local/state/dotfiles/backups/<fecha>/`. Detalles y opciones en [docs/installation.md](docs/installation.md).

## Primeros pasos

```bash
theme                 # lista los 17 temas
theme nord            # aplica uno
scripts/dotfiles-doctor.sh   # verifica la instalación
```

`Super+Return` terminal · `Super+Space` buscador · `Super+Shift+Space` Settings ·
`Super+K` todos los atajos ([docs/keybindings.md](docs/keybindings.md)).

Tu nombre y título (banner de la terminal, pantalla de bloqueo, login de SDDM y saludo) se
configuran en `~/.config/dotfiles/user.conf`; el instalador te los pregunta.

## Stack

| Área | Hyprland (Wayland) | Qtile (X11) |
|---|---|---|
| WM | Hyprland + hyprpaper + hyprshell | Qtile + picom |
| Barra | waybar | polybar |
| Launcher | rofi (+ walker/elephant) | rofi |
| Bloqueo / login | gtklock · SDDM | betterlockscreen / i3lock · SDDM |
| Común | kitty · zsh + powerlevel10k · dunst · Neovim (LazyVim) · herdr · lazygit · Thunar | |

## Skill de IA

El instalador deja lista la skill **`d4rkfiles`** para [Claude Code](https://claude.com/claude-code) y
[opencode](https://opencode.ai): le pedís en lenguaje natural "cambiá al tema nord", "configurá mis
monitores", "agregá este atajo", "actualizá el sistema" o "¿por qué no anda waybar?" y sabe dónde está cada
cosa, cómo cambiarla sin romper nada y cómo recargarla. Ver [docs/ai-skill.md](docs/ai-skill.md).

## Personalizar

Tu configuración vive en `~/.config/dotfiles/` (`user.conf`, overrides de Hyprland,
`local.zsh`), así `git pull` nunca choca con tus cambios.
Ver [docs/customization.md](docs/customization.md).

## Documentación

| Doc | Contenido |
|---|---|
| [installation.md](docs/installation.md) | Opciones, etapas, paquetes, backups, desinstalar |
| [customization.md](docs/customization.md) | `user.conf`, monitores, wallpapers, alias propios |
| [structure.md](docs/structure.md) | Layout del repo y archivos generados |
| [themes.md](docs/themes.md) | Motor de temas, `theme.json`, plantillas, crear un tema |
| [design-system.md](docs/design-system.md) | Reglas de diseño compartidas |
| [keybindings.md](docs/keybindings.md) | Atajos de Hyprland, Qtile, kitty y herdr |
| [components.md](docs/components.md) | Qué hace cada pieza |
| [scripts.md](docs/scripts.md) | Herramientas: doctor, update, theme, gen-assets… |
| [security.md](docs/security.md) | Qué no se versiona y dónde van tus credenciales |
| [ai-skill.md](docs/ai-skill.md) | La skill `d4rkfiles` para Claude Code y opencode |
| [troubleshooting.md](docs/troubleshooting.md) | Problemas frecuentes |

## Licencia

MIT — ver [LICENSE](LICENSE).
