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
| `scripts/setup-sddm-theme.sh` | Instala el tema de login de SDDM |
| `scripts/wayland/wayvnc-toggle.sh` | Monitor virtual por VNC |
| `scripts/bluetooth-status.sh` | Ícono de estado de bluetooth (waybar y polybar) |

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
dotfiles-update [all|check|snapshot|rollback|pacman|aur|clean|orphans] [--no-snapshot] [--no-aur] [--no-clean]
```

`all` crea un snapshot de **Timeshift** (debe estar configurado), corre `pacman -Syu` y
`yay -Sua`, limpia cachés y avisa de `.pacnew` y de reinicio por kernel nuevo (`linux`,
`-lts`, `-zen`, `-hardened`). El modo puede ir en cualquier posición. Rollback:
`sudo timeshift --restore`.
