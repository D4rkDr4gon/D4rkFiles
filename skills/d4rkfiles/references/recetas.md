# Recetas

Todas las rutas son relativas al repo (`~/.local/share/dotfiles`) salvo que se indique.

## Temas y wallpapers

**Cambiar de tema:** `theme` (lista) · `theme <nombre>` · `theme --current`. Desde el menú: `Super+Shift+Space → THEMES`.

**Crear un tema:**
```bash
cp -r themes/nord themes/mi-tema
$EDITOR themes/mi-tema/theme.json      # name, colores, "wallpaper": "mi-tema.jpg"
scripts/gen-assets.sh mi-tema          # wallpaper original + preview.png (o usá el tuyo, abajo)
theme mi-tema
```
`theme.json` exige `name`, `wallpaper`, `primary`, `secondary`, `background`, `foreground`, `chip_battery`,
`chip_bluetooth`, `chip_wlan`, `chip_audio`, `status_ok`, `status_warn`, `status_error` (todos `#rrggbb`). Opcionales:
`radius`, `opacity`, `blur_*`, `font_mono`, `icon_theme`, `opencode_theme`. Detalle: `docs/themes.md`.

**Wallpaper propio:** copiá la imagen a `~/.local/share/backgrounds/` y poné su nombre en `"wallpaper"`. Para uno
puntual sin tocar el tema: `Super+Shift+Space → BACKGROUNDS`.

**Tematizar una app nueva:** copiá su config a `config/<app>/archivo.tpl`, cambiá los colores por tokens
(`@primary@`, `@background@`, `@radius@`…), agregá `/config/<app>/archivo` a `.gitignore`, `theme <activo>`.

## Monitores

- **Hyprland:** `hyprctl monitors` lista las salidas. Escribí las reglas en `~/.config/dotfiles/hypr/monitors.conf`:
  ```ini
  monitor=eDP-1,1920x1080@60,0x0,1
  monitor=DP-1,2560x1440@144,1920x0,1
  ```
  Luego `hyprctl reload`. Gráfico: `hyprmon` (Settings → DISPLAYS).
- **Qtile/X11:** `xrandr` o `arandr`; poné el comando en `~/.xprofile`. Qtile y polybar detectan los monitores solos.

## Paquetes

1. Decidí el grupo: `install/packages/base.txt` (todas las sesiones), `hyprland.txt`, `x11.txt`; el sufijo `.aur.txt` para el AUR.
2. Agregá una línea con el nombre exacto (el CI verifica que exista).
3. Instalalo: `sudo pacman -S --needed <pkg>` o `yay -S --needed <pkg>` (**pedí confirmación**), o `./install.sh --only packages`.
4. Quitar: sacá la línea y `sudo pacman -Rns <pkg>` (confirmá antes).
5. `scripts/dotfiles-doctor.sh packages` compara lo declarado con lo instalado.

## Actualizar

`dotfiles-update` (alias) → snapshot de Timeshift, `pacman -Syu`, `yay -Sua`, limpieza, aviso de `.pacnew` y de reinicio por
kernel. Modos: `check`, `snapshot`, `rollback`, `pacman`, `aur`, `clean`, `orphans`. Rollback: `sudo timeshift --restore`.
Para actualizar el repo: `git -C ~/.local/share/dotfiles pull` y después `./install.sh --only configure,links`.

## Diagnóstico

1. `scripts/dotfiles-doctor.sh -v` (secciones: `links packages services configs repo`).
2. Logs útiles:
   - Hyprland: `~/.local/state/hyprland/session.log`, `hyprpaper.log`, `workspace.log`
   - Bloqueo: `~/.local/state/dotfiles/lock-screen.log` · wayvnc: `~/.local/state/dotfiles/wayvnc.log`
   - Batería: `~/.local/state/battery-watch/`
   - Errores de config de Hyprland: `hyprctl configerrors`
3. Servicios de usuario: `systemctl --user status battery-watch.timer elephant hyprland-session-init`.
4. Síntomas frecuentes y soluciones: `docs/troubleshooting.md`.

## Servicios y unidades

Las unidades de usuario están en `system/systemd-user/` y se enlazan a `~/.config/systemd/user/`. Habilitar:
`systemctl --user enable --now <unidad>`. `wayvnc.service` es manual (sin `[Install]`): `systemctl --user start wayvnc`.
