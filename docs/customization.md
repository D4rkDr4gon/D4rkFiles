# Personalización

Todo lo que es tuyo vive **fuera del repo**, en `~/.config/dotfiles/`. Así podés
actualizar el repo con `git pull` sin conflictos.

## `user.conf`

`~/.config/dotfiles/user.conf` (`KEY=VALUE`; plantilla en [`user.conf.example`](../user.conf.example)).
Lo leen los scripts, zsh, Hyprland y Qtile. Todo es opcional: lo que falta se autodetecta.

| Clave | Para qué | Por defecto |
|---|---|---|
| `USER_DISPLAY_NAME` | Nombre en el banner de zsh, la pantalla de bloqueo, SDDM, la bienvenida y Settings | Tu nombre (GECOS) o login |
| `USER_TITLE` | Título/alias junto al nombre | vacío |
| `BANNER_ART_FILE` | Arte del banner (por defecto el DARKDRAGON del proyecto, `assets/banner-art.txt`); `none` = solo tu nombre | — |
| `TERMINAL`, `BROWSER`, `FILE_MANAGER`, `EDITOR_GUI` | Apps de los atajos | kitty, firefox, thunar, subl |
| `KB_LAYOUT`, `KB_VARIANT` | Teclado de Hyprland/Qtile | `localectl` → `vconsole.conf` → `us` |
| `DISPLAY_MANAGER` | Login manager a habilitar | `sddm` |
| `DEFAULT_THEME` | Tema del instalador | `red-dark` |
| `EXTRA_WALLPAPER_DIRS` | Carpetas extra de wallpapers (separadas por `:`) | — |
| `EXTRA_REPO_DIRS` | Carpetas extra donde Settings → Repositories busca clones de git (separadas por `:`; `~` siempre) | — |
| `VPN_PROFILE` | Conexión de NetworkManager para los alias `vpnup`/`vpndown` | — |
| `VNC_RES`, `VNC_PORT` | Monitor virtual de `wayvnc-toggle` | `1920x1080`, `5900` |
| `EXPENSES_CURRENCY` | Moneda principal del [gestor de gastos](#gestor-de-gastos) | la del locale (`LC_MONETARY`) o `USD` |
| `EXPENSES_RATES` | Monedas que el gestor de gastos cotiza de internet (separadas por `,`) | `USD,EUR` |

Después de cambiar algo: `theme <tema-actual>` (o `./install.sh --configure`) regenera los archivos.

## Hyprland: monitores y atajos propios

`config/hypr/hyprland.lua` carga al final `~/.config/dotfiles/hypr/*.conf` y después
`*.lua`, así que lo tuyo pisa todo. El instalador crea `local.conf` de ejemplo.

```ini
# ~/.config/dotfiles/hypr/local.conf
monitor=eDP-1,1920x1080@60,0x0,1
monitor=DP-1,2560x1440@144,1920x0,1
bind = SUPER, O, exec, obsidian
env = WLR_NO_HARDWARE_CURSORS,1
```

`hyprctl monitors` lista los nombres de salida; `hyprmon` (paquete AUR) los configura gráficamente.

Hyprland >= 0.57 solo lee Lua: esos `.conf` los traduce `config/hypr/lib/user_conf.lua`, que
entiende un subconjunto de hyprlang. Opciones planas (`input:sensitivity = 0.2`) o en bloques
(`general { gaps_in = 2 }`), `$variables`, `env`, `monitor`, `exec-once`/`exec`, `unbind` y
`bind*` con `exec`, `killactive`, `togglefloating`, `fullscreen`, `workspace` o
`movetoworkspace[silent]`. Heredan `$mainMod`, `$terminal`, `$browser`, `$fileManager`,
`$editor`, `$dotfiles` y `$SCRIPTS_DIR`. Lo demás (`windowrule`, `layerrule`, `source`,
`gesture`, otros dispatchers) no se aplica y Hyprland lo avisa con una notificación al
cargar: pasalo a un `.lua` en la misma carpeta, que tiene toda la API `hl.*`:

```lua
-- ~/.config/dotfiles/hypr/local.lua
hl.window_rule({ match = { class = "^(foot)$" }, float = true })
hl.bind("SUPER + Z", hl.dsp.window.pseudo())
```

### Actualizar desde Hyprland < 0.57

1. `sudo pacman -Syu` (trae Hyprland 0.57).
2. `git -C ~/.local/share/dotfiles pull`.
3. `~/.local/share/dotfiles/scripts/theme-switch.sh <tu-tema> --render-only` (genera
   `env.lua` y `theme.lua`; `./install.sh --only configure` también, pero con `DEFAULT_THEME`).
4. Cerrar sesión y volver a entrar.

Tus archivos de `~/.config/dotfiles/hypr/` se siguen leyendo; si alguna línea no se puede
traducir, la notificación dice cuál (`archivo:línea`). Un `workspaces.conf` viejo con
`unbind`/`bind` no molesta: de ese archivo solo se lee `# count: N`.

[Settings](settings.md) también escribe en esa carpeta, nunca en el repo: `settings.conf`
(input y cursor, como líneas planas `input:sensitivity = 0.2`), `autostart.conf` (tus apps de
inicio) y `workspaces.conf` (cuántos workspaces habilitar: la línea `# count: N`, que leen
`hyprland.lua` para los atajos, waybar, Ctrl+Tab y rofi). Se pueden editar a mano; como se cargan
en orden alfabético, lo que pongas en `local.conf` queda por debajo de `settings.conf`.

**Qtile/X11:** los monitores se configuran con `xrandr` (o `arandr`); poné el comando en tu
`~/.xprofile` o en `local.zsh`. Qtile y polybar detectan los monitores conectados solos.

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

## VPN

El módulo de VPN de waybar y su panel (`tools/vpn_tui.py`, `Super+K` no; se abre con click en el ícono) trabajan
sobre **NetworkManager** y no traen ningún perfil. Tiene tres paneles, uno por tipo; usás el que te sirva y
los demás quedan vacíos:

| Panel | Qué agrupa | `n` |
|---|---|---|
| **NetworkManager** | Otras VPN de NM: OpenConnect, L2TP, vpnc, strongSwan, PPTP… (columna Type = plugin) | Abre `nm-connection-editor` para crearla |
| **WireGuard** | `.conf` de cualquier proveedor (formato wg-quick) | Importa un `.conf` |
| **OpenVPN** | `.ovpn` (paquete `networkmanager-openvpn`) | Importa un `.ovpn` |

1. Importá con `n` desde cualquier ruta, o copiá el archivo a `~/.config/dotfiles/vpn/`: ahí aparece en su panel
   como *not imported* y `enter` lo importa.
2. `enter` conecta o desconecta, `d` elimina el perfil de NetworkManager (no el archivo), `r` refresca.

OpenVPN con `auth-user-pass` pide usuario y contraseña: el usuario queda en la conexión y la contraseña se pasa con
un archivo temporal que se borra al instante (NetworkManager no la guarda); los perfiles solo de certificados
conectan directo. Los de NetworkManager se conectan en la terminal (`nmcli --ask`) porque suelen pedir contraseña
u OTP. También sirve `nmcli connection import type wireguard file <archivo>`. Los archivos de
`~/.config/dotfiles/vpn/` nunca se versionan.

Ninguna VPN arranca sola: lo importado queda con `autoconnect=no` (NetworkManager lo trae en `yes` y levantaría
varias a la vez al iniciar) y al abrir el panel se apaga el autoconnect de las VPN importadas por fuera.

## Webapps

Sitios web como apps de escritorio (ventana propia, sin pestañas, con ícono en el launcher)
sobre **firefoxpwa** (`sudo pacman -S firefoxpwa`).

**Settings → 󰖟 WEBAPPS** abre un gestor en la terminal (`tools/webapps_tui.py`):

- `n`: pegá la URL (`drive.proton.me` alcanza) y confirmá el nombre. Detecta el
  manifest del sitio; si no es PWA arma uno mínimo con el favicon, así sirve para cualquier web.
- Sobre una app: `enter` la abre, `d` la borra, `r` la reinstala. El panel **Detalle** muestra
  página, manifest y si está en tu lista.

La lista vive en `~/.config/dotfiles/webapps.conf` (una por línea:
`nombre|manifest|página inicial|ícono`, manifest vacío = sitio sin PWA). El gestor la crea
a partir de [`webapps.conf.example`](../webapps.conf.example) la primera vez; sin ese archivo
`scripts/webapps.sh` usa el ejemplo (solo YouTube). `scripts/webapps.sh [nombre]` instala lo
que falte de la lista, así que en otra máquina alcanza con copiar tu `webapps.conf` y correrlo.

## Modos de escritorio

Un modo ubica un conjunto de apps en workspaces fijos según lo que vayas a hacer (ej:
TRABAJO con el chat en el 2 y el navegador en el 5; JUGAR con Steam en el 1). No viene
ninguno de fábrica: los creás vos.

**Settings → 󰕮 MODES** (o `Mod + Shift + M`) muestra tus modos para aplicar uno y, al
final, **Gestionar modos...**, que abre un gestor en la terminal (`tools/modes_tui.py`) con
dos paneles: **Modos** arriba y las **Apps** del modo seleccionado abajo (`tab` cambia):

- Panel Modos: `enter` aplica el modo, `n` nuevo (nombre e ícono Nerd Font), `r` renombra,
  `d` borra.
- `a` lista las **ventanas abiertas**: elegís una y toma su clase exacta y el comando de su
  `.desktop` (las terminales se identifican por título). La primera fila, **Cargar a mano**,
  abre el formulario vacío.
- Panel Apps: `enter`/`e` edita nombre, comando, match y workspace; `d` la quita.

Al aplicar un modo (`scripts/mode-switch.sh <modo>`), cada app que ya está abierta se mueve
a su workspace y las que no, se abren ahí sin sacarte del workspace actual. Las que no
forman parte del modo no se tocan (no cierra nada). Termina en el workspace 1.

Los modos viven en `~/.config/dotfiles/modes.conf`, fuera del repo (formato en
[`modes.conf.example`](../modes.conf.example)); el modo activo queda en
`$XDG_RUNTIME_DIR/desktop-mode`, así que tras un reinicio **no hay ninguno activo**. "Sin modo" (primera entrada del menú,
`mode-switch.sh --none`, la fila *No mode* del gestor o `x`) lo desactiva sin tocar ninguna ventana. Requiere Hyprland.

## Gestor de gastos

`Super+G` abre `tools/expenses_tui.py` (también el widget de escritorio **Money** y Settings → **Finances**, que
concentra la gestión: cuentas, categorías, cotizaciones, import y export). Guarda lo mismo que una app de finanzas
como Money Manager: cuentas (efectivo, banco, tarjeta de crédito con día de cierre y vencimiento, inversiones…),
categorías de gasto e ingreso con presupuesto mensual (y uno distinto por mes), gastos, ingresos, transferencias
(también entre monedas) y ajustes de saldo, **compras en cuotas** (cada cuota es un movimiento con fecha futura),
**gastos fijos** que se generan solos al llegar la fecha, y el resumen de cada tarjeta (cerrado, ciclo en curso,
cuotas que vienen y deuda; `s` lo carga como lo muestra el banco y `p` registra el pago).

| Página | Qué muestra |
|---|---|
| `1` Overview | Mes en curso (`h`/`l` cambia de mes): patrimonio, cuentas, presupuesto por categoría y movimientos |
| `2` Installments | Compras en cuotas: avance, cuota, lo que falta |
| `3` Recurring | Gastos/ingresos fijos (`space` pausa, `p` genera los vencidos) |
| `4` Cards | Tarjetas de crédito: resumen, ciclo, cuotas futuras y deuda |

- **Datos**: `~/.local/state/dotfiles/expenses/expenses.db` (SQLite; otra ruta con `EXPENSES_DB`). Esquema en
  `tools/expenses_db.py`.
- **Moneda y cotizaciones**: la principal sale de `EXPENSES_CURRENCY` (o del locale). Al abrir la TUI se cotizan
  las de `EXPENSES_RATES` en un hilo aparte (`tools/expenses_rates.py`): por defecto
  [open.er-api.com](https://open.er-api.com) (gratis, sin clave, una vez por día); si la principal es ARS, el
  dólar y el euro van con [DolarAPI](https://dolarapi.com) (oficial por defecto; en `$` se elige MEP, blue,
  tarjeta, CCL…). Sin red quedan las últimas. Un gasto en otra moneda guarda el monto original y el convertido.
- **Montos y fechas** se escriben como uno quiera: `15999,50`, `15.999,50`, `$ 1,500.00`; `11/10/2026`,
  `11/10`, `hoy`, `2026-10-11`.
- **Importar de Money Manager** (Realbyte): en la app, backup como `.sqlite`; en la TUI o en Settings → Finances,
  `i`. Muestra antes de aplicar lo nuevo, lo que parece un duplicado de algo cargado a mano (no se marca y se
  vincula) y lo que cambió en la app desde el último import (no se marca: la TUI manda). Lo desmarcado no se
  vuelve a ofrecer y antes de aplicar se guarda `expenses.db.bak-…`. También por línea de comandos:
  `python3 tools/expenses_import.py backup.sqlite [--apply]`.

## Backup en Proton Drive

Respaldo incremental de carpetas locales en Proton Drive con el CLI oficial (`proton-drive`, paquete AUR
`proton-drive-cli-bin`; también `gawk` y `script` de util-linux). Se maneja desde **Settings → Backup** (una TUI en una
ventana flotante, clase `proton-backup`). Inicia sesión una vez con `proton-drive auth login` (guarda la sesión en el keyring
vía Secret Service) o con `L` desde la TUI si venció.

Las carpetas viven en `~/.config/dotfiles/proton-backup.conf`, fuera del repo (formato en
[`proton-backup.conf.example`](../proton-backup.conf.example)): `id|ícono|nombre|ruta local|ruta remota|exclusiones`. Se
agregan con `a` en la TUI. Por defecto no hay ninguna.

- **Cómo sube**: compara contra el manifiesto de la última subida (`<id>.files`: ruta, tamaño, mtime), copia **solo lo nuevo o
  modificado** a un stage y lo sube con `-d merge -f create-new-revision` (un archivo modificado queda como nueva revisión). Lo
  que borraste en local va a la **papelera** de Proton (30 días). Las exclusiones se aplican en el stage (el CLI no las tiene);
  un patrón con `/` es relativo a la raíz de la carpeta, si no se compara contra el nombre (`.git`). Los symlinks no se suben.
- **Segundo plano**: corre con `setsid`, sigue aunque cierres la TUI y avisa con `notify-send`. Hay un lock: una subida a la vez.
- **Avance**: el CLI solo dibuja su barra con una terminal, así que corre bajo `script` y un parser en `gawk` calcula bytes,
  velocidad y tiempo restante.
- **Estado**: `~/.local/state/dotfiles/proton-backup/` (manifiestos, avance, logs). `PROTON_BACKUP_CONF` / `PROTON_BACKUP_STATE`
  apuntan a otras rutas.

| Tecla (en la TUI) | Acción |
|---|---|
| `enter` / `u` | Sube la carpeta seleccionada / todas |
| `x` | Cancela la subida en curso (lo ya subido queda) |
| `a` / `e` / `d` | Agrega / edita / deja de respaldar una carpeta (no borra nada en Proton) |
| `l` / `L` | Log de la última subida / `proton-drive auth login` |

Desde la terminal: `scripts/proton-backup.sh start|run [id...]|cancel|running`.

## Teclas de las TUIs

`~/.config/dotfiles/keymap.json` guarda las teclas de Settings y de las TUIs que reasignaste en
Settings → Shortcuts → Settings (`{"FirewallView.add": "n"}`; solo lo que cambiaste). Borrarlo
vuelve todo a los defaults.

## Cambiar la config de una app

Editá el archivo del repo (`config/<app>/...`); el symlink hace que el cambio aplique al
instante. Si el archivo tiene versión `.tpl`, **editá el `.tpl`** (el otro se regenera al
cambiar de tema y perdería tus cambios). Ver [themes.md](themes.md#plantillas).

## Integrar tus propias herramientas

El repo no incluye nada específico de trabajo ni de tus servicios. Para tus scripts, alias
o widgets, usá `local.zsh`, `hypr/*.conf` y tu propio repo/carpeta; el motor de temas
expone los colores en `~/.local/state/dotfiles/current_theme.json` para que tus scripts
combinen con el tema activo.
