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
`radius`, `opacity`, `blur_*`, `font_mono`, `icon_theme`, `opencode_theme` y los de forma (abajo). Detalle: `docs/themes.md`.

**Wallpaper propio:** copiá la imagen a `~/.local/share/backgrounds/` y poné su nombre en `"wallpaper"`. Para uno
puntual sin tocar el tema: `Super+Shift+Space → BACKGROUNDS`.

**Tematizar una app nueva:** copiá su config a `config/<app>/archivo.tpl`, cambiá los colores por tokens
(`@primary@`, `@background@`, `@radius@`…), agregá `/config/<app>/archivo` a `.gitignore`, `theme <activo>`.

## Forma del tema

Campos opcionales de `theme.json` (defaults = como se veía todo antes; tabla en `docs/themes.md`):
`border_size`, `border_style` (`solid` | `gradient` | `rotating`), `border_angle`, `gaps_in`, `gaps_out`,
`inactive_opacity`, `dim_inactive`, `dim_strength`, `blur_noise`, `blur_contrast`, `blur_brightness`, `blur_vibrancy`,
`blur_popups`, `shadow_enabled`, `shadow_style` (`dark` | `glow`), `shadow_range`, `shadow_power`, `animations`
(`smooth` | `snappy` | `bouncy` | `off`), `font_size` (kitty = N, rofi = N−1, waybar/dunst/GTK = N−3), `font_ui` (GTK).

- Lo más fácil: Settings → Appearance / Fonts & cursor. Editan una **copia** del tema en `~/.config/dotfiles/themes/`
  (nunca `themes/` del repo) y reaplican.
- A mano: editá esa copia (o tu tema) y `theme <tema>`. Llegan a Hyprland por `config/hypr/theme.conf.tpl`; los presets
  de animación son `config/hypr/animations/<preset>.conf`. No pongas gaps/borde/sombra/animaciones en `hyprland.conf`:
  `theme.conf` se carga antes y quedaría pisado.
- Validar: `Hyprland --verify-config -c ~/.config/hypr/hyprland.conf`.

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
4. Quitar: sacá la línea y `sudo pacman -Rns <pkg>` (confirmá antes). Settings → Update → `v` (Installed) lista todo lo
   instalado con tamaño y dependencias, y `x` desinstala mostrando antes qué se borra (`pacman -Rs --print`).
5. `scripts/dotfiles-doctor.sh packages` compara lo declarado con lo instalado.

## Actualizar

`dotfiles-update` (alias) → snapshot de Timeshift, `pacman -Syu`, `yay -Sua`, limpieza, aviso de `.pacnew` y de reinicio por
kernel (y resumen de vulnerabilidades). Modos: `check`, `snapshot`, `rollback`, `pacman`, `aur`, `clean`, `orphans`,
`audit`, `firmware`. Rollback: `sudo timeshift --restore`. Settings → Update muestra el estado y corre cada modo.
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

## Workspaces

Settings → Workspaces: `←/→` elige cuántos (1–10) y `enter` aplica. Genera `~/.config/dotfiles/hypr/workspaces.conf`:
`unbind` de los atajos que sobran (el repo trae `Super+1…9`), el bind del 10 (`Super+0`) si hace falta y la línea
`# count: N`, que leen el indicador de waybar (`config/hypr/scripts/hypr-workspaces.py`), `Ctrl+Tab` y la rueda
(`config/hypr/scripts/workspace-cycle.sh`, dan la vuelta en 1..N) y el switcher de rofi. Sin el archivo rigen 9.
Si quedan ventanas en workspaces que se deshabilitan, Settings ofrece moverlas. Qtile: 6 grupos fijos.

## Luz nocturna

Settings → Displays → Night light (necesita `hyprsunset`): `enter` prende/apaga (la primera vez habilita
`hyprsunset.service`), `←/→` temperatura y `-/+` brillo en vivo, `s` horario (por defecto 21:00 → 07:30, 4500K),
`l` arranque al iniciar sesión. Genera `config/hypr/hyprsunset.conf` (perfiles por horario; lo elegido en la línea
`# settings:`; está en `.gitignore`). A mano: `hyprctl hyprsunset temperature 4000` / `identity`.

## Firewall

Settings → Firewall (firewalld, instalado pero apagado de fábrica). **Antes de prenderlo** avisá: la zona por defecto
(`public`) deja entrar solo lo permitido, así que KDE Connect, VNC (wayvnc) y servicios locales dejan de responder.
Permitir: `a` con un servicio (`kdeconnect`, `ssh`) o puerto (`5900/tcp`). Zona por conexión: `enter` en Connections
(casa en `home`). A mano: `sudo firewall-cmd --permanent --add-service=kdeconnect && sudo firewall-cmd --reload`.
Con Docker, reiniciarlo después de prender firewalld.

## Tailscale

`sudo pacman -S tailscale` y Settings → VPN, panel Tailscale, `n`: habilita `tailscaled`, deja al usuario como
operator (`tailscale set --operator=$USER`, así up/down no piden sudo) y hace el login (URL en la terminal). `enter`
levanta/baja este equipo, usa otro de exit node o copia su IP; `d` cierra la sesión.

## Teclas de las TUIs

Settings → Shortcuts → Settings lista todas las teclas de Settings y sus secciones (y de las TUIs sueltas). `enter`
sobre una la reasigna (valida formato y choques; vacío = default). Se guardan en `~/.config/dotfiles/keymap.json`
(`{"FirewallView.add": "n"}`); borrarlo vuelve todo a los defaults.

## Salud del sistema

- **Tope de carga** (Settings → Battery, `l`): 100/90/80/60 % si existe `/sys/class/power_supply/BAT*/charge_control_end_threshold`.
  Se fija con `/etc/udev/rules.d/90-battery-charge-limit.rules` (sudo); 100 % la borra.
- **Maintenance**: `paccache.timer` (caché de pacman semanal), earlyoom (memoria), `.pacnew`/`.pacsave` (`pacdiff -o`;
  `enter` diff, `m` fusionar en `nvim -d`, `k` conservar, `u` usar el nuevo) y unidades caídas (`systemctl --failed`).
- **USB guard**: `usbguard` con política inicial = lo conectado; los nuevos quedan bloqueados y
  `scripts/usbguard-notify.py` avisa con botones. Si tras un `fwupd` un dispositivo interno aparece bloqueado, permitirlo
  siempre (`p`) desde Settings.
- **Sesión**: `config/hypr/scripts/hypr-session.py save|restore|status` (restore abre apps de verdad: probalo con un
  `hyprctl` falso).

## Seguridad y firmware

- `dotfiles-update audit` — CVEs de los paquetes instalados (`arch-audit`): los que se arreglan actualizando y los
  que no tienen parche todavía.
- `dotfiles-update firmware` — `fwupd`: baja metadata (sudo), lista lo nuevo y pregunta antes de instalar.
- Settings → Update muestra ambos resúmenes en "System status"; `enter` sobre la fila corre el modo.

