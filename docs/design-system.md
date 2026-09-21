# Sistema de diseño ("Flat Minimal")

Reglas que siguen todas las apps tematizadas. Están pensadas para que un tema
nuevo (solo colores + un par de valores de forma) se vea coherente en todo el
escritorio sin tocar ninguna config a mano.

## Principios

1. **Sin bordes decorativos.** La jerarquía sale de superficies y espacio, no de marcos.
   Excepción: el borde de ventana de Hyprland (color de foco).
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
6. **Buscador único.** `Mod+Space` abre rofi; walker queda para Settings → APPS
   (ver [components.md](components.md#rofi-y-walker)).

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
