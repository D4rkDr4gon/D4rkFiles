# Atajos

`Super` es el modificador (`Mod`). Los atajos de Hyprland y Qtile se parecen pero **no son
idénticos**; las diferencias están marcadas. `Super+K` abre una cheatsheet interactiva con
todos los atajos (y permite reasignar su combinación).

## Aplicaciones (ambas sesiones)

| Atajo | Acción |
|---|---|
| `Super+Return` | Terminal (`TERMINAL`) |
| `Super+Shift+Return` | herdr (multiplexor de terminal) en kitty |
| `Super+Space` | Buscador de apps (rofi) |
| `Super+Shift+Space` | Menú Settings (temas, workspaces, fondos, notificaciones, monitores, updates) |
| `Super+B` | Navegador (`BROWSER`) |
| `Super+F` | Gestor de archivos (`FILE_MANAGER`) |
| `Super+S` | Editor (`EDITOR_GUI`) |
| `Super+K` | Cheatsheet de atajos |
| `Super+V` | Historial del portapapeles (Hyprland: cliphist + rofi · Qtile: CopyQ) |
| `Super+L` | Menú de acciones: bloquear, suspender, reiniciar, apagar, salir |
| `Print` / `Super+Shift+S` | Captura de pantalla (región; Wayland: guarda y copia) |
| `Super+Ctrl+R` | Recargar barra (y la config del WM) |

## Ventanas

| Atajo | Hyprland | Qtile |
|---|---|---|
| Cerrar | `Super+Q` | `Super+Q` |
| Pantalla completa | `Super+Shift+F` (`Super+M` también) | `Super+Shift+F` |
| Flotante | `Super+T` | `Super+T` |
| Mover ventana | `Super+Shift+H/J/K/L` | `Super+Shift+←↓↑→` |
| Redimensionar | `Super+Ctrl+H/J/K/L` (±30 px) | `Super+Ctrl+←↓↑→` |
| Siguiente foco | `Super+Tab` (`cyclenext`) | `Alt+Tab` (`layout.next`) |
| Cambiar de layout | — | `Super+Tab` |
| Normalizar / alternar split | `Super+N` (`togglesplit`) | `Super+N` (`normalize`) |
| Arrastrar / redimensionar con mouse | `Super+clic izq. / der.` | `Super+clic izq. / der.` (ventanas flotantes) |
| Alt+Tab con previews | `Alt+Tab` (hyprshell) | — |
| Overview de workspaces | `Super+W` o 3 dedos hacia arriba | — |

## Workspaces (1–6)

| Atajo | Acción |
|---|---|
| `Super+1…6` | Ir al workspace (lo trae al monitor actual, como Qtile) |
| `Super+Shift+1…6` | Mover la ventana al workspace |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Hyprland: workspace siguiente / anterior · Qtile: foco abajo / arriba en el layout |
| `Super+-` | Hyprland: ir a un workspace vacío |
| gesto de 3 dedos ←→ | Hyprland: cambiar de workspace |

## Monitores

| Atajo | Acción |
|---|---|
| `Super+.` / `Super+,` | Foco al monitor siguiente / anterior |
| `Super+Shift+.` / `Super+Shift+,` | Hyprland: mover la ventana al monitor siguiente / anterior |

## Multimedia

`XF86Audio{Raise,Lower}Volume`, `Mute`, `MicMute` y `XF86MonBrightness{Up,Down}` en ambas sesiones;
`XF86AudioPlay/Next/Prev` solo en Hyprland. En Hyprland se muestran con el OSD de swayosd.

## kitty

| Atajo | Acción |
|---|---|
| `Ctrl+Shift+Enter` | Nueva ventana (split) |
| `Ctrl+Shift+Space` | Nueva pestaña |
| `Ctrl+Shift+W` | Cerrar pestaña |
| `Ctrl+Shift+N` | Renombrar pestaña |
| `Ctrl+Shift+←↓↑→` | Redimensionar el split |
| `Ctrl+V` | Pegar |

Layouts: `tall`, `stack`, `fat`, `grid`.

## herdr

Prefijo `Ctrl+Space`, luego: `c` nueva pestaña · `n`/`p` siguiente/anterior · `-` split · `1…9`
pestaña · `Shift+1…9` workspace · `a` siguiente agente · `Alt+g` lazygit · `Alt+e` nvim ·
`Alt+t` btop · `Alt+d` lazydocker · `Alt+o` opencode.

## Personalizar

Editá `config/hypr/hyprland.conf` o `config/qtile/modules/keys.py`, o agregá los tuyos en
`~/.config/dotfiles/hypr/*.conf` (ver [customization.md](customization.md)).
