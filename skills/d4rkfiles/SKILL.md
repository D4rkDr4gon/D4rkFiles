---
name: d4rkfiles
description: Use when the user wants to customize, theme, fix, update or manage their Arch Linux desktop installed from the D4rkFiles dotfiles (Hyprland or Qtile) - changing or creating themes (colors and shape: borders, gaps, blur, shadows, animations, fonts), wallpapers, keybindings (including the keys of the Settings TUI), monitors, workspaces count, night light, firewall, VPN/Tailscale, waybar/polybar, rofi, kitty, dunst, zsh, packages, services, updates, security audits, firmware, diagnostics, backups, the Settings TUI and its sections, or the install itself. Knows the repo layout, the template/theme engine, the safe way to edit each component and how to reload it.
---

# d4rkfiles — gestionar el rice de Arch

Skill para administrar un escritorio Arch instalado con **D4rkFiles** (Hyprland + Qtile). Es la puerta de
entrada: te dice dónde está cada cosa, cómo cambiarla sin romper nada y cómo recargarla. El detalle vive en
la documentación del repo; **leela bajo demanda, no la reescribas de memoria**.

## Dónde está todo

| Qué | Dónde |
|---|---|
| El repo (siempre, sea donde sea que esté clonado) | `~/.local/share/dotfiles` (symlink estable) |
| Tu configuración de usuario | `~/.config/dotfiles/user.conf` |
| Overrides de Hyprland (monitores, atajos propios) | `~/.config/dotfiles/hypr/*.conf` |
| Lo que escribe Settings | `~/.config/dotfiles/hypr/settings.conf` (input, cursor), `autostart.conf`, `workspaces.conf` (cantidad de workspaces) |
| Teclas reasignadas de Settings y las TUIs | `~/.config/dotfiles/keymap.json` (`{id: teclas}`, solo lo cambiado) |
| Temas propios / copias editadas desde Settings | `~/.config/dotfiles/themes/<tema>/theme.json` |
| Generados por Settings dentro del repo (en `.gitignore`) | `config/hypr/hypridle.conf`, `config/hypr/hyprsunset.conf` |
| Alias/funciones propios de zsh | `~/.config/dotfiles/local.zsh` |
| Tema activo, backups, logs | `~/.local/state/dotfiles/` |
| Wallpapers propios | `~/.local/share/backgrounds/` |
| Docs del repo | `~/.local/share/dotfiles/docs/` (`installation`, `customization`, `structure`, `themes`, `keybindings`, `components`, `scripts`, `security`, `troubleshooting`) |

Layout del repo: `config/<app>/` (→ `~/.config/<app>`), `home/zsh/`, `system/`, `scripts/`, `install/`,
`manifest/links.tsv` (qué se enlaza dónde), `themes/`, `assets/`, `tools/`, `skills/`.

## Reglas que no se rompen

1. **Si un archivo tiene un `.tpl` al lado, se edita el `.tpl`.** El otro es generado (está en `.gitignore`) y
   se pisa al cambiar de tema. Regenerar: `theme <tema-activo>` (o `scripts/theme-switch.sh <tema> --render-only`).
2. **Lo del usuario va en `~/.config/dotfiles/`**, no dentro del repo: así `git pull` nunca choca.
3. **Nunca hardcodear** `/home/<usuario>`, nombres, monitores, teclado ni batería. Rutas: `$HOME`, `%h`,
   `$HOME/.local/share/dotfiles`; valores por usuario: `user.conf`.
4. **Nada de secretos en el repo** (tokens, claves, VPN, passwords). Van en variables de entorno o en
   `~/.config/dotfiles/`. Ver `docs/security.md`.
5. **Antes de tocar el sistema, mirar primero**: `./install.sh --dry-run`, `scripts/dotfiles-doctor.sh`.
   El instalador y los enlaces hacen backup (`~/.local/state/dotfiles/backups/<fecha>/`); nada se borra.
6. **Pedir confirmación antes de**: `sudo`, `pacman -Syu`/instalar/quitar paquetes, tocar `/etc` o `/usr`
   (PAM, SDDM, sesiones), cambiar el shell por defecto, o hacer `git push`.
7. Si hay una sesión gráfica viva, recargar con el comando de la tabla de abajo; no reiniciar el WM.

## Recargar cada cosa

| Cambiaste | Recargá con |
|---|---|
| Un tema / colores / fuentes / radio | `theme <nombre>` (regenera plantillas y recarga lo recargable) |
| `hyprland.conf` o `~/.config/dotfiles/hypr/*.conf` | `hyprctl reload` (validar antes: `Hyprland --verify-config -c ~/.config/hypr/hyprland.conf`) |
| waybar / polybar | `scripts/barupdate.sh` |
| dunst | `dunstctl reload` |
| kitty | `theme <activo>` (colores) · `Ctrl+Shift+F5` (config) |
| Qtile | `Super+Ctrl+R` |
| rofi / walker / dunst DND | se leen al abrirse |
| zsh | `exec zsh` |
| Unidades systemd de usuario | `systemctl --user daemon-reload` |
| `~/.config/dotfiles/hypr/workspaces.conf` | `hyprctl reload` (Settings → Workspaces lo hace solo) |
| `config/hypr/hyprsunset.conf` / `hypridle.conf` | `systemctl --user restart hyprsunset` / `hypridle` |
| `~/.config/dotfiles/keymap.json` | se aplica al instante en Settings; las TUIs sueltas al reabrirlas |

## Qué hacer ante cada pedido

- **"Cambiá / creá un tema", "poné otro wallpaper"** → `references/recetas.md#temas-y-wallpapers` y `docs/themes.md`.
- **"Agregá / cambiá un atajo"** → `docs/keybindings.md`; Hyprland: `config/hypr/hyprland.conf` (o un `.conf` propio en
  `~/.config/dotfiles/hypr/`), Qtile: `config/qtile/modules/keys.py`. `Super+K` abre la cheatsheet.
- **"Configurá mis monitores"** → `references/recetas.md#monitores`.
- **Casi todo tiene una sección en Settings** (`Super+Shift+Space`, `tools/settings/settings_tui.py`): antes de editar a mano,
  ofrecé la sección que lo hace (y que valida). Tabla completa: `docs/settings.md`.
- **"Cambiá el borde / gaps / sombra / animaciones / blur / tamaño de fuente"** → campos de forma del tema
  (`references/recetas.md#forma-del-tema`); Settings → Appearance y Fonts & cursor los editan sobre una copia del tema.
- **"Quiero N workspaces"** → Settings → Workspaces o `references/recetas.md#workspaces`.
- **"Prendé / programá la luz nocturna"** → Settings → Displays (`references/recetas.md#luz-nocturna`).
- **"Prendé el firewall" / "abrí un puerto"** → Settings → Firewall (`references/recetas.md#firewall`). Avisá que al
  prenderlo se cortan KDE Connect, VNC y lo que no esté permitido en la zona.
- **"Cambiá la tecla X de Settings"** → Settings → Shortcuts → Settings (`references/recetas.md#teclas-de-las-tuis`).
- **"¿Tengo vulnerabilidades?" / "actualizá el firmware"** → `dotfiles-update audit` / `firmware` (`references/recetas.md#seguridad-y-firmware`).
- **"Desinstalá X" / "¿qué ocupa más?"** → Settings → Update → `v` (Installed, estilo pacseek) o `references/recetas.md#paquetes`.
- **"Configurá Tailscale"** → Settings → VPN, panel Tailscale, `n` (`references/recetas.md#tailscale`).
- **"Instalá / sacá un paquete"** → `references/recetas.md#paquetes`.
- **"Actualizá el sistema"** → `dotfiles-update` (snapshot de Timeshift + `pacman -Syu` + AUR + limpieza). Ver `docs/scripts.md`.
- **"Algo no anda" / "revisá mi instalación"** → `scripts/dotfiles-doctor.sh` y `references/recetas.md#diagnostico`.
- **"Cambiá cómo se ve waybar / rofi / kitty / dunst…"** → el archivo en `config/<app>/` (su `.tpl` si existe); mantené la
  regla de `docs/design-system.md` (un solo radio, sin bordes decorativos, colores por tokens).
- **"Cambiá mi nombre / apps por defecto / teclado"** → `~/.config/dotfiles/user.conf`, luego `theme <activo>`.
  Claves en `docs/customization.md`.
- **"Volvé a mi config anterior"** → `~/.local/state/dotfiles/backups/<fecha>/` (conservan la ruta relativa; es un `mv`).
- **"Reinstalá / reenlazá"** → `./install.sh --only links` (o `--only configure`, `--dry-run` primero).

## Si el cambio es al repo (no solo a la máquina)

Trabajá en el clone (`readlink -f ~/.local/share/dotfiles`). Antes de commitear:

```bash
scripts/dotfiles-doctor.sh links configs repo   # 0 errores y 0 avisos
scripts/check-docs.sh                           # docs sin rutas ni enlaces rotos
shellcheck --severity=warning <scripts tocados>
```

**TUIs y secciones de Settings:** una sección nueva es un archivo en `tools/settings/sections/` con su `DView`, importado en
`tools/settings/settings_tui.py` y agregado a `CATEGORIES` y a `section_views()`. Usá las piezas de `tools/dtui.py` (`Panel`,
`Table` + `set_rows`, `Card`, popups, barras); todo lo que llame a procesos va en `@work(thread=True)` (nunca uses
`self.loading` como bandera: es una propiedad de Textual); textos visibles en inglés; dale `description` a cada `Binding`
(quedan reasignables solas). Rutas desde `tools/settings/sections/common.py` (`CONF_DIR`, `STATE`, `HYPR_USER_DIR`…),
nunca `/home/<usuario>`. Probá headless (`app.run_test()` + `save_screenshot`) con `DTUI_KEYMAP`, `XDG_CONFIG_HOME` y
`XDG_STATE_HOME` apuntando a un directorio temporal. Detalle: `docs/design-system.md#tuis` y `docs/settings.md`.

Si agregás un `.tpl`, agregá su salida a `.gitignore`. Si agregás un paquete, va en `install/packages/*.txt`
(los `*.aur.txt` son del AUR). Si agregás un enlace, en `manifest/links.tsv`. Actualizá `docs/` si el cambio se ve.

## Antes de responder

Si algo de esta skill contradice lo que ves en el sistema (versiones, rutas, paquetes renombrados), **confiá en el
sistema** y en `docs/`, y avisá al usuario de la discrepancia. Ante la duda, leé el archivo real antes de editarlo.
