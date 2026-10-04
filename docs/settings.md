# Settings

Panel central del entorno: una TUI (`tools/settings/settings_tui.py`) con el estilo común de
las TUIs ([design-system.md](design-system.md#tuis)). Reemplazó al menú rofi de
Settings. Los textos de la TUI están en inglés.

Se abre con `Mod + Shift + Space` (Hyprland y Qtile) o con un click en el logo de waybar o de
polybar. `config/waybar/scripts/settings-launch.sh` la abre en una kitty flotante **centrada**
en el monitor con foco, como un diálogo (clase `settings`, 1560×960 por `windowrule`
`center`/`size` en `config/hypr/hyprland.conf`; en Qtile, `FLOAT_GEOMETRY` de
`config/qtile/modules/hooks.py` con márgenes `None` = centrada). Si ya está abierta, el mismo
atajo la enfoca o la cierra (`config/waybar/scripts/center-tui-launch.sh`).

## Nada de lo que cambia toca el repo

Settings escribe solo en tu configuración, fuera del clone (así `git pull` nunca choca con
tus ajustes):

| Qué | Dónde |
|---|---|
| Input (teclado, mouse, touchpad) y cursor | `~/.config/dotfiles/hypr/settings.conf`: líneas planas (`input:sensitivity = 0.2`, `env = XCURSOR_SIZE,24`). `config/hypr/hyprland.conf` incluye `~/.config/dotfiles/hypr/*.conf` al final, así que ganan sobre el repo |
| Distribución de teclado | Además, `KB_LAYOUT` / `KB_VARIANT` de `~/.config/dotfiles/user.conf` (de ahí salen `config/hypr/env.conf` y la sesión X11) |
| Apps de inicio propias | `~/.config/dotfiles/hypr/autostart.conf` |
| Temas editados (Theme editor, Appearance, Fonts) | `~/.config/dotfiles/themes/<tema>/`. Si el tema es del repo se copia ahí primero; `scripts/theme-switch.sh` busca primero ahí, así que tu copia reemplaza a la original ([themes.md](themes.md#temas-propios)) |
| Inactividad (Power) | `config/hypr/hypridle.conf`, generado e ignorado por git |
| Historial del Color picker | `~/.local/state/dotfiles/settings/colors.json` |

## Layout

- **Izquierda**: perfil (el logo de waybar, `config/waybar/logo.png`, con `textual-image`, y
  tu nombre: `USER_DISPLAY_NAME` de `user.conf`, o el de la cuenta) y el menú **Settings**
  agrupado por categoría: Connectivity, System, Tools, Hardware, Desktop y Look & feel. Abre en
  la primera sección (Wi-Fi), salvo `--section <id>`. Los encabezados no se seleccionan.
- **Derecha**: la sección seleccionada. Moverse por el menú cambia la sección al instante.

| Tecla | Acción |
|-------|--------|
| `j`/`k`, flechas | Moverse por el menú |
| `enter` / `tab` | Entrar a la sección |
| `esc` | Volver al menú (en el menú, cerrar) |
| `q` | Cerrar |

Dentro de una sección rigen sus propias teclas (al pie); las que tienen varios paneles
(Modes, Notifications, Shortcuts, VPN, Audio) usan `tab` para cambiar de panel.

## Secciones

| Sección | Qué hace | Implementación |
|---|---|---|
| Wi-Fi | Estado (red, señal `▂▄▆█`, IP, canal/banda) y redes (conectada, guardadas, resto por señal); `enter` conecta (pide contraseña si hace falta), `d` desconecta, `f` olvida, `r` reescanea, `w` prende/apaga, `o` abre `impala` | `nmcli` |
| Bluetooth | Adaptador y dispositivos agrupados (Connected, Paired, Available) con batería; `enter` conecta/desconecta (empareja si hace falta), `s` escanea, `t` confianza, `x` olvida, `b` prende/apaga, `o` abre `bluetui` | `bluetoothctl` |
| VPN | Tres paneles vacíos de fábrica: NetworkManager (OpenConnect, L2TP…), WireGuard y OpenVPN; importa `.conf`/`.ovpn` | Vista de `tools/vpn_tui.py` |
| Phone | Teléfono vinculado por KDE Connect: batería, hacer sonar, ping, mandar el portapapeles, compartir archivo o texto, ver sus notificaciones, bloquearlo | `kdeconnect-cli`, `busctl --user` |
| Network tools | Interfaz, IP, gateway, DNS, latencia y puertos escuchando; `i` IP pública y `s` test de velocidad (solo a pedido) | `ip`, `resolvectl`, `ping`, `ss`, `curl` |
| Services | Servicios de usuario conocidos que estén instalados (elephant, hypridle, battery-watch, wayvnc…): `enter` arranca/para, `e` al iniciar sesión, `l` logs | `systemctl --user` |
| Startup apps | Tus apps de inicio (`a` agrega, `enter` prende/apaga, `d` borra) y, de solo lectura, las del repo; `x` corre una ahora | `~/.config/dotfiles/hypr/autostart.conf` |
| Logs | Errores (o errores + warnings con `w`) del journal de este arranque o el anterior (`b`), filtro `/`, unidades fallidas | `journalctl -o json` |
| Snapshots | Snapshots de Timeshift; `n` crear, `enter` restaurar, `d` borrar, con `sudo` en la misma ventana | `/timeshift/snapshots` (modo rsync), `sudo timeshift` |
| System | Host, CPU, memoria, swap y discos con barras estilo statusline; repos de GitHub (tuyos, los de tu cuenta sin clonar vía `gh`, de terceros); `f` fetch de todos; correr `scripts/dotfiles-doctor.sh` | Busca clones en `~` y en `EXTRA_REPO_DIRS` de `user.conf` |
| Update | Check, full update, snapshot, rollback, pacman, AUR, clean, orphans | `scripts/dotfiles-update.sh <modo>` en la misma ventana |
| Notifications | Historial de dunst y **Do Not Disturb**: on/off, por tiempo y apps silenciadas | `dunstctl` + subcomandos de `config/rofi/scripts/dnd-menu.sh` (`--status`, `--on`, `--off`, `--timer`, `--app-toggle`, `--app-add`) |
| Clipboard | Historial con búsqueda y preview | Vista de `tools/clipboard_tui.py` |
| Screenshots | Capturar región / ventana / pantalla (Settings se esconde mientras) y galería con preview; grabar con `wf-recorder` si está | `grim`, `slurp`; carpeta `$(xdg-user-dir PICTURES)/Screenshots` |
| Color picker | Color de un píxel con historial; `enter` copia en hex/rgb/hsl | `slurp -p` + `grim` |
| AI Agents | Uso y contexto de Claude Code, opencode, Codex y Antigravity; panel **Providers** para mostrar u ocultar cada uno (también en waybar) | Vista de `tools/agents_tui.py`; config en `~/.config/dotfiles/agents.conf` |
| Displays | Monitores, **Tablet as monitor** (VNC) y `hyprmon` en la misma ventana | `scripts/wayland/wayvnc-toggle.sh` (la primera vez: `init`) |
| Audio | Salidas y entradas: `enter` predeterminada, `←/→` volumen, `m` silenciar | `pw-dump`, `wpctl` |
| Input | Teclado, mouse y touchpad, en vivo y guardado | `hyprctl keyword` + `settings.conf` |
| Power | Perfil de energía, brillo y **Idle actions** (bloquear, apagar pantalla, suspender) | `powerprofilesctl`, `brightnessctl`, `hypridle` |
| Battery | Carga, salud, ciclos, consumo y baterías de periféricos | `upower` |
| Storage | Discos y pendrives con uso; `enter` monta/desmonta, `o` abre, `e` expulsa | `lsblk`, `udisksctl` |
| Modes | Modos de escritorio | Vista de `tools/modes_tui.py` ([customization.md](customization.md#modos-de-escritorio)) |
| Workspaces | Ir a un workspace | `hyprctl` / `qtile cmd-obj` |
| Webapps | Abrir, crear, reinstalar y borrar webapps | Vista de `tools/webapps_tui.py` ([customization.md](customization.md#webapps)) |
| Default apps | Navegador, archivos, editor, PDF, imágenes, video, música, mail | `xdg-mime`, `xdg-settings` |
| Shortcuts | Cheatsheet y edición de atajos | Vista de `tools/shortcuts_tui.py` |
| Themes | Temas (los tuyos marcados *yours*) con preview y paleta; `enter` aplica | `scripts/theme-switch.sh`; Settings se reabre sola para tomar los colores |
| Theme editor | Borrador de un tema con preview; `n` lo guarda como tema nuevo, `s` guarda el base (como copia tuya si es del repo) | `~/.config/dotfiles/themes/` |
| Appearance | Radio de esquinas, opacidad y blur del tema activo | Copia del tema en `~/.config/dotfiles/themes/` + `theme-switch.sh` |
| Fonts & cursor | Fuente mono e íconos del tema; tema y tamaño del cursor | `fc-list`, `hyprctl setcursor`, `gsettings`, `settings.conf` |
| Backgrounds | Imágenes de `EXTRA_WALLPAPER_DIRS`, `~/.local/share/backgrounds` y `assets/wallpapers` con preview; `enter` aplica | `scripts/wallpaper-set.sh` |

Las secciones viven una por archivo en `tools/settings/sections/` o dentro de
`settings_tui.py`; los helpers comunes (rutas, `user.conf`, overrides de Hyprland, temas
editables, `settings_hidden`) están en `tools/settings/sections/common.py`. Las TUIs de Modes,
Webapps, Shortcuts, VPN, Clipboard y AI Agents siguen existiendo sueltas (waybar, `Mod + K`,
`Mod + V`…): Settings monta las mismas vistas (`DView` de `tools/dtui.py`), y sus timers no
corren mientras la sección no se ve.

## Dependencias

`python-textual` (repos oficiales) y `python-textual-image` (AUR) para las previews con el
protocolo gráfico de kitty; sin este último la TUI anda igual, con un texto en lugar de la
imagen. Cada sección usa la herramienta de su fila y, si falta, lo avisa en vez de fallar.
