# Personalización

Todo lo que es tuyo vive **fuera del repo**, en `~/.config/dotfiles/`. Así podés
actualizar el repo con `git pull` sin conflictos.

## `user.conf`

`~/.config/dotfiles/user.conf` (`KEY=VALUE`; plantilla en [`user.conf.example`](../user.conf.example)).
Lo leen los scripts, zsh, Hyprland y Qtile. Todo es opcional: lo que falta se autodetecta.

| Clave | Para qué | Por defecto |
|---|---|---|
| `USER_DISPLAY_NAME` | Nombre en el banner de zsh, la pantalla de bloqueo, SDDM y la bienvenida | Tu nombre (GECOS) o login |
| `USER_TITLE` | Título/alias junto al nombre | vacío |
| `TERMINAL`, `BROWSER`, `FILE_MANAGER`, `EDITOR_GUI` | Apps de los atajos | kitty, firefox, thunar, subl |
| `KB_LAYOUT`, `KB_VARIANT` | Teclado de Hyprland/Qtile | `localectl` → `vconsole.conf` → `us` |
| `DISPLAY_MANAGER` | Login manager a habilitar | `sddm` |
| `DEFAULT_THEME` | Tema del instalador | `nord` |
| `EXTRA_WALLPAPER_DIRS` | Carpetas extra de wallpapers (separadas por `:`) | — |
| `VPN_PROFILE` | Conexión de NetworkManager para los alias `vpnup`/`vpndown` | — |
| `VNC_RES`, `VNC_PORT` | Monitor virtual de `wayvnc-toggle` | `1920x1080`, `5900` |

Después de cambiar algo: `theme <tema-actual>` (o `./install.sh --configure`) regenera los archivos.

## Hyprland: monitores y atajos propios

`hyprland.conf` carga al final `~/.config/dotfiles/hypr/*.conf`, así que lo tuyo pisa
todo. El instalador crea `local.conf` (siempre debe haber al menos un `.conf`: Hyprland
falla si el glob no encuentra nada).

```ini
# ~/.config/dotfiles/hypr/local.conf
monitor=eDP-1,1920x1080@60,0x0,1
monitor=DP-1,2560x1440@144,1920x0,1
bind = SUPER, O, exec, obsidian
env = WLR_NO_HARDWARE_CURSORS,1
```

`hyprctl monitors` lista los nombres de salida; `hyprmon` (paquete AUR) los configura gráficamente.

## zsh: aliases y funciones propias

`~/.config/dotfiles/local.zsh` se carga al final de `.zshrc`. Ejemplo:

```zsh
alias proyectos="cd ~/work && lazygit"
export PATH="$HOME/tools/bin:$PATH"
```

`DOTFILES_NO_BANNER=1` desactiva el banner de la terminal.

## Wallpapers propios

Copiá imágenes a `~/.local/share/backgrounds/` (o a una carpeta de `EXTRA_WALLPAPER_DIRS`).
`Settings → BACKGROUNDS` (`Mod+Shift+Space`) las lista todas. Para que un **tema** use una:
poné su nombre de archivo en `"wallpaper"` de `theme.json`.

## Webapps

`scripts/webapps.sh` lee `~/.config/dotfiles/webapps.conf` (una por línea:
`nombre|manifest|página inicial|ícono opcional`). Sin ese archivo crea solo YouTube.

## Cambiar la config de una app

Editá el archivo del repo (`config/<app>/...`); el symlink hace que el cambio aplique al
instante. Si el archivo tiene versión `.tpl`, **editá el `.tpl`** (el otro se regenera al
cambiar de tema y perdería tus cambios). Ver [themes.md](themes.md#plantillas).

## Integrar tus propias herramientas

El repo no incluye nada específico de trabajo ni de tus servicios. Para tus scripts, alias
o widgets, usá `local.zsh`, `hypr/*.conf` y tu propio repo/carpeta; el motor de temas
expone los colores en `~/.local/state/dotfiles/current_theme.json` para que tus scripts
combinen con el tema activo.
