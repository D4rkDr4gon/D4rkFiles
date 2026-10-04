# Sistema de diseño ("Flat Minimal")

Reglas que siguen todas las apps tematizadas. Están pensadas para que un tema
nuevo (solo colores + un par de valores de forma) se vea coherente en todo el
escritorio sin tocar ninguna config a mano.

## Principios

1. **Sin bordes decorativos.** La jerarquía sale de superficies y espacio, no de marcos.
   Excepciones: el borde de ventana de Hyprland (color de foco) y los paneles de las TUIs
   (ver [TUIs](#tuis)).
2. **Un solo radio.** `radius` del tema se usa en Hyprland, waybar, dunst, rofi, OSDs,
   gtklock, etc. Los contenedores externos usan `radius + 4` (token `@radius_outer@`).
3. **El acento es un relleno de estado, no decoración.** `primary` marca selección,
   foco y progreso; nunca se usa como línea suelta.
4. **Una sola rampa de superficies.** `chip_battery → chip_bluetooth → chip_wlan →
   chip_audio` (de más oscura a más clara) es la misma en dunst, rofi, kitty, HyprFM,
   Firefox… El fondo de reposo de un panel es `chip_battery`; hover/borde suave,
   `chip_bluetooth`.
5. **Jerarquía de texto derivada.** No hay grises fijos: el texto atenuado se calcula
   mezclando `foreground` y `background` (`@text_muted@` 45%, `@text_dim@` 20%,
   `@text_sub@` 75%).
6. **Buscador único.** `Mod+Space` abre rofi; walker queda como alternativa
   (ver [components.md](components.md#rofi-y-walker)).

## TUIs

Las TUIs del repo (`tools/`: Settings, modos, webapps, VPN, atajos, portapapeles, agentes IA) se
ven iguales entre sí y como `impala`/`bluetui`. Todas se arman con
[`tools/dtui.py`](../tools/dtui.py) (Python + Textual), que toma los colores de
`~/.local/state/dotfiles/current_theme.json`; una TUI nueva usa esas piezas y no define colores
propios. **Los textos visibles van en inglés** (comentarios y docs, en español).

Cada TUI es una **vista** (`DView`) más un envoltorio de una línea (`ViewApp(XView).run()`):
la misma vista se abre suelta (waybar, atajos) o como sección de
[Settings](settings.md). Por eso una vista no busca widgets de la app: publica sus atajos con
`hints()` + `update_hints()`, usa `self.app.push_screen`/`notify_ok`/`suspend`, declara el widget
inicial en `FOCUS` y pausa sus timers con `visible_now` cuando su sección no se ve.

| Pieza | Regla |
|---|---|
| `Panel` | Borde redondeado con el título sobre el borde y un subtítulo de estado abajo a la derecha. El panel con foco va en `primary`; el resto, borde y título atenuados |
| `Table` | Selección de fila completa (`chip_audio` + negrita con foco, `chip_battery` sin foco); la fila seleccionada conserva los colores de cada celda |
| `KeyHints` | Línea fija al pie: tecla en `primary` + acción atenuada; cambia según el panel con foco |
| Popups | `FormModal`, `ConfirmModal`, `PickModal`, `TextModal`: centrados, borde en `primary`, campos de una línea sin borde |
| Barras | `meter10` para uso (`▓▓▓░░░░░░░`, verde/amarillo/rojo a 50/80 %), `charge10` para cargas (verde desde 50 %), `bar` para volumen/brillo |
| Imágenes | `ImagePreview` (protocolo gráfico de kitty vía `python-textual-image`; sin el paquete, un texto) |
| Navegación | `tab` cambia de panel, `j`/`k` o flechas mueven, `enter` es la acción principal, `q`/`esc` salen; con un popup abierto las teclas de atrás no hacen nada |
| Estados | `●` activo (`status_ok`), `○` inactivo, `✗` error (`status_error`), `✓` al día |

## Arquitectura del buscador único

Qtile usa `rofi -show combi` con los modos `spotlight`, `drun` y `run`; Hyprland usa `drun`.
`config/rofi/scripts/spotlight-fallback.sh` es el modo "script" que rofi invoca **solo al confirmar con
Enter un texto sin coincidencias** (`ROFI_RETV=2`), no en cada tecla. Por eso es una
cascada que actúa al confirmar: (1) comando existente en el `PATH` (con argumentos) → lo
ejecuta; (2) expresión matemática → copia el resultado y notifica; (3) cualquier otra cosa →
búsqueda web. Un resultado "en vivo" mientras se escribe no es posible con este mecanismo.

## Opacidad por niveles

`opacity` del tema es la base (kitty). Rofi usa `base − 0.05`; las apps "secundarias"
(Thunar, Sublime, dunst, Obsidian…) `base + 0.05`. Con opacidad ≥ 0.98 todo pasa a 1.0.
Los TUI flotantes van siempre en 0.97 para que se lean con cualquier tema.

## Identidad

El banner (`assets/banner-art.txt`), el dragón (`assets/dragon.txt`) y el logo de waybar
(`config/waybar/logo.png`) son la identidad del proyecto y se ven igual en la terminal, la
pantalla de bloqueo, el login y el dashboard de Neovim. Lo único que cambia por usuario es
el nombre y el título.

Ver [themes.md](themes.md) para el formato de `theme.json` y la lista de tokens.
