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
| Quiero volver a mi config anterior | Está en `~/.local/state/dotfiles/backups/<fecha>/`. |
