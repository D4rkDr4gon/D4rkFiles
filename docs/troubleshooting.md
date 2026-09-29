# Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| Hyprland muestra `source= globbing error: found no match` | Falta `~/.config/dotfiles/hypr/*.conf`. Corré `./install.sh --only configure` (crea `local.conf`). |
| Un archivo de config "vuelve" a su valor anterior al cambiar de tema | Estás editando un archivo generado. Editá su `.tpl` ([structure.md](structure.md#archivos-generados)). |
| `theme` dice `wallpaper '…' no encontrado` | La imagen no está en `assets/wallpapers`, `~/.local/share/backgrounds` ni `EXTRA_WALLPAPER_DIRS`. |
| Falta un archivo generado (`colors.conf`, `style.css`…) | `scripts/theme-switch.sh <tema> --render-only` |
| El doctor dice "no es un link al repo" | Había una config previa: `./install.sh --only links` la respalda y crea el link. |
| Fuentes o iconos raros en un tema | Instalá `install/packages/base.txt` (fuentes `InputMono*`, breeze, adwaita…). |
| Widgets de waybar vacíos (batería) | En equipos sin batería el módulo se oculta; es normal. |
| `walker` no abre | Necesita `elephant.service` (`systemctl --user enable --now elephant`) y los paquetes AUR de `hyprland.aur.txt`. |
| Cursor invisible o con parpadeo (NVIDIA/VM) | Agregá `env = WLR_NO_HARDWARE_CURSORS,1` en `~/.config/dotfiles/hypr/local.conf`. |
| El login manager no muestra "Hyprland (dotfiles)" | `./install.sh --only system` (pregunta antes de copiar la sesión a `/usr/share/wayland-sessions`). |
| El widget **Agentes IA** no muestra el uso de Claude | Lo escribe la statusline de Claude Code. Si ya tenías una propia, el instalador no la reemplaza: apuntá `statusLine` de `~/.claude/settings.json` a `~/.claude/statusline-command.sh` ([ai-skill.md](ai-skill.md#statusline-y-widget-agentes-ia)). |
| El widget de VPN dice "Sin perfiles VPN configurados" | Es lo esperado: no viene ningún perfil. Importá el tuyo ([customization.md](customization.md#vpn)). |
| El click del medio en una notificación no lleva a la app | Solo funciona en Hyprland y con notificaciones que traen acción (navegadores, Discord, Telegram…); un `notify-send` simple solo se cierra. |
| Instalé herdr, Claude Code u opencode después de los dotfiles | `./install.sh --only herdr` (plugins de herdr) y `./install.sh --only links` (skill de IA y statusline). |
| La skill `d4rkfiles` no aparece en Claude Code / opencode | `./install.sh --only links` y verificá con `scripts/dotfiles-doctor.sh links`. |
| Un modo de escritorio no mueve una app | La clase de ventana no coincide: en el gestor de modos, borrá la app y agregala de nuevo desde la lista de ventanas abiertas. |
| Quiero volver a mi config anterior | Está en `~/.local/state/dotfiles/backups/<fecha>/`. |
| Algo más | `scripts/dotfiles-doctor.sh -v` revisa enlaces, paquetes, servicios, configs y secretos. Si no lo resuelve, abrí un [issue](https://github.com/D4rkDr4gon/D4rkFiles/issues). |
