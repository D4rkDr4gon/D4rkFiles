# Estructura del repositorio

```
.
├── install.sh              Instalador (ver installation.md)
├── install/
│   ├── lib/common.sh       Utilidades: logging, dry-run, backups, enlaces
│   ├── steps/              Una etapa por archivo (preflight, packages, configure, links…)
│   └── packages/           Listas de paquetes por grupo
├── manifest/links.tsv      Qué se enlaza dónde (lo usan install.sh y el doctor)
├── config/                 Configs de cada app → ~/.config/<app>
├── home/zsh/               zshrc + módulos → ~/.zshrc
├── system/                 Lo que requiere root o systemd: sddm/, sessions/, systemd-user/
├── scripts/                Herramientas (theme-switch, doctor, update, lock-screen…)
│   ├── lib/                env.sh (entorno) y theme.sh (motor de temas)
│   └── wayland/            wayvnc-toggle
├── tools/                  TUIs en Python (cheatsheet de atajos)
├── skills/d4rkfiles/       Skill de IA para Claude Code y opencode (la statusline va en config/claude/)
├── themes/                 theme.json + preview.png por tema
├── assets/                 banner-art.txt, dragon.txt y wallpapers/ (generados por gen-assets.sh)
├── docs/                   Esta documentación
├── user.conf.example       Plantilla de tu configuración por usuario
└── .github/workflows/      CI
```

## Dónde va cada cosa

| Necesitás… | Editá |
|---|---|
| Un atajo de Hyprland | `config/hypr/hyprland.conf` (o tu `~/.config/dotfiles/hypr/*.conf`) |
| Un atajo de Qtile | `config/qtile/modules/keys.py` |
| Colores o forma de un tema | `themes/<tema>/theme.json` |
| Cómo se ve una app | su `*.tpl` en `config/<app>/` |
| Un paquete | `install/packages/*.txt` |
| Un enlace nuevo | `manifest/links.tsv` |
| Lo que sabe la skill de IA | `skills/d4rkfiles/SKILL.md` y `references/` |
| Lo tuyo (nombre, apps, teclado) | `~/.config/dotfiles/user.conf` |

## Archivos generados

Los archivos que dependen del tema o del usuario se generan desde una plantilla `.tpl`
y **no se versionan** (están en `.gitignore`). Ejemplos: `config/kitty/colors.conf`,
`config/waybar/style.css`, `config/hypr/theme.conf`, `config/hypr/env.conf`,
`config/dunst/dunstrc`, `system/sddm/dotfiles-ascii/Main.qml`.

Si un archivo que querés editar tiene un `.tpl` al lado, **editá el `.tpl`**.

## Rutas y estado (fuera del repo)

| Ruta | Contenido |
|---|---|
| `~/.local/share/dotfiles` | Symlink al repo (lo crea el instalador) |
| `~/.config/dotfiles/` | Tu `user.conf`, `local.zsh`, `hypr/*.conf`, `webapps.conf`, config de wayvnc |
| `~/.local/state/dotfiles/` | Tema activo (`current_theme.json`), backups, logs |
| `~/.local/share/backgrounds/` | Tus wallpapers |
