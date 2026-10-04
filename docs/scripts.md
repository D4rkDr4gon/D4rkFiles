# Scripts

| Script | Para qué |
|---|---|
| `install.sh` | Instalador (ver [installation.md](installation.md)) |
| `scripts/theme-switch.sh` (`theme`) | Aplica un tema ([themes.md](themes.md)) |
| `scripts/gen-assets.sh` | Genera wallpapers y previews desde los temas |
| `scripts/logo.sh` (alias `logo`) | Muestra el dragón y el banner del proyecto en la terminal |
| `scripts/dotfiles-doctor.sh` | Diagnóstico de solo lectura |
| `scripts/dotfiles-update.sh` | Actualización del sistema con snapshot y rollback |
| `scripts/lock-screen.sh` | Bloqueo (gtklock / betterlockscreen / i3lock) |
| `scripts/screenshot.sh` | Captura de región; guarda en `~/Pictures/Screenshots` y copia |
| `scripts/cliphist.sh` | Wrapper único de cliphist (la base vive en `$XDG_RUNTIME_DIR`, no toca el disco) |
| `scripts/battery-watch.sh` | Notificaciones de batería (15/10/5 %) |
| `scripts/barupdate.sh` | Reinicia la barra (waybar o polybar según la sesión) |
| `scripts/welcome.sh` | Notificación de bienvenida con tu nombre |
| `scripts/webapps.sh` | Webapps con firefoxpwa ([customization.md](customization.md#webapps)) |
| `scripts/mode-switch.sh` | Aplica un modo de escritorio; sin argumentos, menú rofi ([customization.md](customization.md#modos-de-escritorio)) |
| `scripts/setup-sddm-theme.sh` | Instala el tema de login de SDDM |
| `scripts/wayland/wayvnc-toggle.sh` | Monitor virtual por VNC |
| `scripts/bluetooth-status.sh` | Ícono de estado de bluetooth (waybar y polybar) |
| `scripts/wayland/notif-jump.py` | Click del medio en una notificación → enfoca la app que la mandó ([components.md](components.md#notificaciones-y-osds)) |
| `scripts/check-docs.sh` | Verifica que la documentación no tenga enlaces ni rutas rotas (lo corre el CI) |
| `scripts/build-wiki.sh` | Genera la [wiki](https://github.com/D4rkDr4gon/D4rkFiles/wiki) a partir de `docs/` |
| `tools/dtui.py` | Base común de las TUIs: paneles, tablas, atajos y popups con el estilo del tema ([design-system.md](design-system.md#tuis)) |
| `tools/shortcuts_tui.py` | Cheatsheet de atajos (`Super+K`) |
| `tools/vpn_tui.py` | Panel de VPN de waybar ([customization.md](customization.md#vpn)) |
| `tools/settings/settings_tui.py` | Settings (`Super+Shift+Space`, logo de la barra), con sus secciones en `tools/settings/sections/` ([settings.md](settings.md)) |
| `tools/modes_tui.py` | Gestor de modos: Settings → Modes ([customization.md](customization.md#modos-de-escritorio)) |
| `tools/webapps_tui.py` | Gestor de webapps: Settings → Webapps ([customization.md](customization.md#webapps)) |
| `tools/clipboard_tui.py` | Historial del portapapeles (`Super+V`) con búsqueda y preview de imágenes |
| `tools/agents_tui.py` | Panel "AI Agents" de waybar y de Settings; proveedores visibles en `~/.config/dotfiles/agents.conf` ([components.md](components.md)) |
| `scripts/wallpaper-set.sh` | Aplica un wallpaper sin cambiar de tema (Settings → Backgrounds) |

## dotfiles-doctor

```bash
scripts/dotfiles-doctor.sh [links packages services configs repo] [-v] [--strict]
```

- **links** — cada enlace de `manifest/links.tsv` existe y apunta al repo; detecta enlaces colgantes.
- **packages** — los paquetes de `install/packages/` (solo de las sesiones instaladas) están instalados y existen en los repos.
- **services** — unidades esperadas habilitadas y unidades fallidas.
- **configs** — sintaxis de shell/Python/JSON/TOML, temas válidos, plantillas renderizadas, `hyprctl configerrors`.
- **repo** — secretos por nombre y contenido, rutas absolutas de usuario, archivos versionados pero ignorados.

Código de salida: 0 todo bien · 1 errores (o avisos con `--strict`) · 2 uso incorrecto.

## dotfiles-update

```bash
dotfiles-update [all|check|snapshot|rollback|pacman|aur|clean|orphans|audit|firmware] [--no-snapshot] [--no-aur] [--no-clean]
```

`all` crea un snapshot de **Timeshift** (debe estar configurado), corre `pacman -Syu` y
`yay -Sua`, limpia cachés y avisa de `.pacnew` y de reinicio por kernel nuevo (`linux`,
`-lts`, `-zen`, `-hardened`). El modo puede ir en cualquier posición. Rollback:
`sudo timeshift --restore`.

- `audit` — paquetes con CVEs conocidos (`arch-audit`, consulta security.archlinux.org): los que
  se arreglan actualizando y los que todavía no tienen parche. `check` y `all` muestran un resumen.
- `firmware` — `sudo fwupdmgr refresh`, lista lo nuevo (`fwupdmgr get-updates`) y pregunta antes
  de instalar. Leer el estado no necesita root; bajar metadata e instalar sí (no hay agente de polkit).

Settings → Update corre estos modos en la misma ventana y muestra el resumen de cada uno.
