# Atajos

`Super` es el modificador (`Mod`). Los atajos están en `config/hypr/hyprland.lua`. `Super+K` abre una cheatsheet interactiva con
todos los atajos (y permite reasignar su combinación).

## Aplicaciones

| Atajo | Acción |
|---|---|
| `Super+Return` | Terminal (`TERMINAL`) |
| `Super+Shift+Return` | herdr (multiplexor de terminal) en kitty |
| `Super+Space` | Lanzador: apps, cuenta en vivo, comandos y búsqueda web; `tab` + `f` marca favoritas (`tools/launcher_tui.py`, [components.md](components.md#lanzador)) |
| `Super+Shift+Space` | Settings: TUI con todas las opciones del entorno ([settings.md](settings.md)) |
| `Super+B` | Navegador (`BROWSER`) |
| `Super+F` | Gestor de archivos (`FILE_MANAGER`) |
| `Super+S` | Editor (`EDITOR_GUI`) |
| `Super+K` | Cheatsheet de atajos |
| `Super+Shift+M` | Modos de escritorio ([customization.md](customization.md#modos-de-escritorio)) |
| `Super+Shift+D` | Modo Focus: No Molestar + oculta los widgets que distraen (música, clima, teléfono, dinero); `scripts/focus-mode.sh` |
| `Super+V` | Historial del portapapeles (cliphist + `tools/clipboard_tui.py`) |
| `Super+E` | Selector de emojis (lanzador, modo `emoji`): busca por nombre en inglés y copia |
| `Super+G` | Gestor de gastos (`tools/expenses_tui.py`, [customization.md](customization.md#gestor-de-gastos)) |
| `Super+Y` | Spotify (`tools/spotify_tui.py`, [customization.md](customization.md#spotify)) |
| `Super+L` | Menú de sesión: bloquear, suspender, salir, reiniciar, apagar (lanzador, modo `power`) |
| `Print` / `Super+Shift+S` | Captura de pantalla (región: guarda y copia) |
| `Super+Ctrl+R` | Recargar barra (y la config del WM) |

## Ventanas

| Acción | Atajo |
|---|---|
| Cerrar | `Super+Q` |
| Pantalla completa | `Super+Shift+F` (`Super+M` también) |
| Flotante | `Super+T` |
| Mover ventana | `Super+Shift+H/J/K/L` |
| Redimensionar | `Super+Ctrl+H/J/K/L` (±30 px) |
| Siguiente foco | `Super+Tab` (`cyclenext`) |
| Alternar split | `Super+N` (`togglesplit`) |
| Arrastrar / redimensionar con mouse | `Super+clic izq. / der.` |
| Alt+Tab con previews | `Alt+Tab` (hyprshell) |
| Overview de workspaces | `Super+W` o 3 dedos hacia arriba |

## Workspaces

Hay atajos para los workspaces 1–9 (la cantidad, de 1 a 10, se cambia en Settings →
Workspaces).

| Atajo | Acción |
|---|---|
| `Super+1…N` | Ir al workspace (lo trae al monitor actual); el 10 es `Super+0` |
| `Super+Shift+1…N` | Mover la ventana al workspace |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Workspace siguiente / anterior (da la vuelta en 1..N) |
| `Super+-` | Ir a un workspace vacío |
| gesto de 3 dedos ←→ | Cambiar de workspace |

## Monitores

| Atajo | Acción |
|---|---|
| `Super+.` / `Super+,` | Foco al monitor siguiente / anterior |
| `Super+Shift+.` / `Super+Shift+,` | Mover la ventana al monitor siguiente / anterior |

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

Plugins (etapa `herdr` del instalador): `Shift+m` gestor de plugins · `Shift+p`/`Shift+o`
mascota (mostrar/ajustes) · `Shift+r`/`Shift+q` cuotas de agentes (refrescar/ajustes).

## Personalizar

Editá `config/hypr/hyprland.lua`, o agregá los tuyos en
`~/.config/dotfiles/hypr/*.conf` o `*.lua` (ver [customization.md](customization.md)).

## Teclas de Settings y las TUIs

Las teclas dentro de Settings y de las TUIs (VPN, Modes, Webapps…) se reasignan en
Settings → Shortcuts → Settings y se guardan en `~/.config/dotfiles/keymap.json`. Detalle en
[settings.md](settings.md#teclas-reasignables).
