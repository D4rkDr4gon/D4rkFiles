# Componentes

Qué hace cada pieza y dónde está su config. Todo vive en `config/<app>/` y se enlaza a
`~/.config/<app>` (ver [`manifest/links.tsv`](../manifest/links.tsv)).

## Hyprland

`config/hypr/`

- `hyprland.conf` — configuración base (monitores autodetectados, gestos de touchpad,
  reglas de ventana, atajos). No tiene valores de máquina.
- `env.conf` *(generado)* — `$terminal`, `$browser`, `$fileManager`, `$editor`, teclado, y
  `WLR_NO_HARDWARE_CURSORS` si se detecta NVIDIA o una VM.
- `theme.conf` *(generado)* — color de borde, `rounding`, blur y opacidad por app.
- `~/.config/dotfiles/hypr/*.conf` — **tus** overrides, cargados al final.
- `config/hypr/scripts/start-hyprland.sh` — wrapper de arranque (limpia `DISPLAY`, activa la sesión de
  logind, guarda logs en `~/.local/state/hyprland/`). Lo usa la sesión "Hyprland (dotfiles)".
- `config/hypr/scripts/start-hyprpaper.sh` — arranca hyprpaper con el wallpaper del tema activo.
- `config/hypr/scripts/move-and-focus-workspace.sh`, `move-window-to-workspace.sh` — `Super+N` trae el
  workspace N al monitor actual (mismo comportamiento que Qtile).

Autostart: waybar, dunst, swayosd, historial de portapapeles (cliphist), hyprpaper, hyprshell,
la unidad `hyprland-session-init`, y (si están instalados) fprint-osd y KDE Connect.

## Qtile (X11)

`config/qtile/` — `config.py` importa `modules/`: `keys`, `groups` (6 workspaces), `layouts`,
`screens`, `mouse`, `hooks` (autostart y opacidad por app). `modules/user.py` lee
`user.conf` y el tema activo; los `Screen` se generan según los monitores detectados.
Barra: polybar; compositor: picom.

## waybar y polybar

- **waybar** (`config/waybar/`, Wayland): logo → Settings, workspaces, reloj, brillo,
  **Agentes IA**, audio (cliamp), **No molestar**, red (impala), **VPN**, bluetooth (bluetui), batería. Los paneles se abren como
  **popups flotantes** con `config/waybar/scripts/float-tui-launch.sh` (abre / enfoca / cierra).
  `config.jsonc` no lleva batería ni interfaz fijas: waybar autodetecta.
  - **Agentes IA** (`custom/claude-agents`): uso de tu suscripción de Claude Code (ventanas de 5 h y 7 días) y el
    contexto de cada sesión abierta de Claude Code y opencode. Click abre el panel. El uso de Claude lo escribe la
    statusline (`config/claude/statusline-command.sh`, que muestra `[modelo] - [esfuerzo] | ctx | 5h | 7d | carpeta`
    y que el instalador enlaza y activa en
    `~/.claude/settings.json` solo si no tenés una); el de opencode se lee directo de su storage.
  - **No molestar** (`custom/dnd`, al lado del audio): `󰂛` activado (color `@alert`), `󰂚` desactivado.
    Click hace toggle (`dnd-menu.sh --toggle`), click derecho abre el menú. Lee la regla `dnd_global` de dunst
    (`config/waybar/scripts/dnd-status.sh`) y se refresca al instante con `pkill -RTMIN+9 waybar`.
  - **VPN** (`custom/vpn`): estado de tus perfiles de NetworkManager; click abre `tools/vpn_tui.py`. **Viene vacío**:
    no trae ningún perfil ni proveedor (ver [customization.md](customization.md#vpn)). Sin perfiles muestra "Sin
    perfiles VPN configurados".
- **polybar** (`config/polybar/`, X11): módulos en `modules/*.ini`. `launch.sh` autodetecta
  batería, adaptador AC y Wi-Fi y los pasa por `POLYBAR_BAT`, `POLYBAR_AC`, `POLYBAR_WLAN`.

## rofi y walker

`config/rofi/`: `theme*.rasi` (`colors.rasi` es generado) y `scripts/`:

| Script | Función |
|---|---|
| `settings-menu.sh` | Menú principal: THEMES, WORKSPACES, APPS, SEARCH, BACKGROUNDS, NOTIFICATIONS, SHORTCUTS, DISPLAYS, UPDATE |
| `action-menu.sh` | Bloquear, suspender, reiniciar, apagar, salir |
| `clipboard-menu.sh` | Historial de portapapeles (cliphist); `Supr` borra una entrada |
| `dnd-menu.sh` | No molestar (global, por tiempo y por app) |
| `notification-center.sh`, `update-menu.sh`, `workspace-switcher.sh`, `web-search.sh` | Historial de notificaciones, updates, workspaces, búsqueda |
| `spotlight-launch.sh`, `spotlight-fallback.sh` | Buscador combinado (apps + comandos + calculadora + web) |

`Super+Space` abre rofi (`drun`) en ambas sesiones. **walker** (`config/walker/`, solo
Wayland) usa el backend `elephant` y se abre desde Settings → APPS; queda fuera del atajo
principal por una condición de carrera conocida entre walker y elephant.

## Notificaciones y OSDs

- **dunst** — `dunstrc` es generado. No molestar escribe `dunstrc.d/50-dnd.conf` (ignorado por
  git) y guarda su estado en `~/.local/state/dotfiles/`.
  **Click del medio** en una notificación (solo Hyprland) enfoca la ventana de la app que la mandó, cambiando de
  workspace: dunst invoca la acción (`mouse_middle_click = do_action, close_current`) y
  `scripts/wayland/notif-jump.py` escucha la señal `ActionInvoked` con `dbus-monitor`. Busca la ventana por el PID
  de la conexión D-Bus que mandó la notificación (distingue webapps de FirefoxPWA, que notifican como `Firefox`) y,
  si no, por nombre de app con el log de `config/dunst/scripts/notif-record.sh` (regla `[notif_jump_record]`).
  Solo sirve con notificaciones que traen acción (navegadores, Discord, Telegram...); un `notify-send` pelado solo se cierra.
- **swayosd** — OSD de volumen y brillo (Wayland). No relee su CSS en caliente: el motor de
  temas reinicia el servidor.
- **fprint-osd** — OSD de huella para `sudo`/lock vía `fprintd`. Solo arranca si `fprintd` está instalado.

## Pantalla de bloqueo y login

- **gtklock** (`config/gtklock/`) — bloqueo en Wayland (`scripts/lock-screen.sh`). Muestra el
  banner del proyecto con tu nombre y título; en X11 se usa `betterlockscreen` o `i3lock`.
- **SDDM** (`system/sddm/dotfiles-ascii/`) — tema de login (fondo negro + el mismo banner). Se instala
  con `scripts/setup-sddm-theme.sh`; el PAM con huella es **opcional**
  (`--with-fingerprint-pam`, requiere `fprintd`).

## Terminal y shell

- **kitty** (`config/kitty/`) — `colors.conf` (colores, paleta ANSI y fuente) es generado.
- **herdr** — multiplexor de terminal; `config.toml` es generado (sección `[theme.custom]`).
- **zsh** (`home/zsh/`) — `zshrc` carga `modules/*.zsh` en orden:

| Módulo | Contenido |
|---|---|
| `00-env` | `user.conf`, PATH, colores del tema, variables de Ollama |
| `10-history` | Historial compartido (100k, ignora duplicados y comandos que empiezan con espacio) |
| `20-keybindings` | Home/End, Ctrl+flechas, Supr… |
| `40-aliases` | `theme`, `dotfiles-*`, `ls`→`lsd`, `cat`→`bat`, navegación, VPN (si `VPN_PROFILE`), VNC |
| `50-tools` | `hex-encode/decode`, `rot13`, funciones de Ollama (si está instalado) |
| `60-banner` | El banner del proyecto con tu nombre (desactivable con `DOTFILES_NO_BANNER=1`) |
| `70-prompt` | powerlevel10k (`~/.p10k.zsh` tiene prioridad sobre `home/zsh/p10k.zsh`) |
| `90-plugins` | zsh-autosuggestions y zsh-syntax-highlighting |

## Editores

- **Neovim** (`config/nvim/`) — LazyVim con el mismo banner en el dashboard; `lua/config/colors.lua` es generado.
- **Sublime Text** (`config/sublime-text/`) — solo `Preferences`, esquema de color (generado) y
  la lista de Package Control; los paquetes se descargan solos.
- **opencode** (`config/opencode/opencode.jsonc`, generado) — colores de agentes y tema; sin
  MCPs ni credenciales (agregá los tuyos con `{env:VAR}`).

## Otras apps tematizadas

Firefox (`userChrome.css`/`userContent.css` en el perfil activo; `--restart-firefox`), HyprFM,
cliamp, lazygit, lazydocker, impala, hyprshell, GTK 3 (`gtk.css` + `settings.ini`), Thunar.
bluetui no tiene tema propio: usa la paleta ANSI de kitty.

## Skill de IA

`skills/d4rkfiles/` — skill para Claude Code y opencode; ver [ai-skill.md](ai-skill.md).

## Herramientas y servicios

- **`tools/shortcuts_tui.py`** — cheatsheet (`Super+K`) con los atajos de Hyprland, kitty,
  herdr, Qtile y los defaults de LazyVim; permite reasignar combinaciones.
- **wayvnc** — usar una tablet como monitor secundario: `scripts/wayland/wayvnc-toggle.sh`
  (`init`, `on`, `off`, `status`; aliases `vnc-on`/`vnc-off`).
- **Unidades systemd de usuario** (`system/systemd-user/`): `battery-watch.{service,timer}`
  (notifica batería baja cada 2 min), `wayvnc.service` (manual), `hyprland-session-init.service`
  y `elephant.service`.
