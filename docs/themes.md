# Temas

El motor de temas es `scripts/theme-switch.sh` (alias `theme`):

```bash
theme                    # lista los temas
theme nord               # aplica un tema
theme --current          # tema activo
theme nord --render-only # solo regenera archivos del HOME (sin recargar apps, wallpaper ni el login de SDDM)
theme nord --restart-firefox
```

También desde `Super+Shift+Space → THEMES` (con preview).

## Cómo funciona

1. Lee `themes/<tema>/theme.json` y calcula los **tokens** (colores, forma y derivados).
2. Renderiza **todas las plantillas** `*.tpl` de `config/`, `home/` y `system/` a su archivo
   hermano sin `.tpl` (ignorado por git).
3. Escribe el estado del tema en `~/.local/state/dotfiles/current_theme.json` (Qtile y las
   TUIs lo leen) y aplica los temas de apps externas (Firefox, HyprFM, cliamp, SDDM).
4. Cambia el wallpaper y recarga lo que se puede recargar (Hyprland, dunst, kitty, waybar,
   swayosd, herdr…).

Nada versionado se edita: si cambiás de tema, `git status` sigue limpio.

## `theme.json`

Obligatorios: `name`, `wallpaper` (nombre de archivo), `primary`, `secondary`, `background`,
`foreground`, `chip_battery`, `chip_bluetooth`, `chip_wlan`, `chip_audio` (rampa de
superficies, de oscura a clara), `status_ok`, `status_warn`, `status_error`. Todos los
colores son `#rrggbb`.

Opcionales (defaults entre paréntesis): `radius` (10), `opacity` (0.80), `blur_enabled` (true),
`blur_size` (6), `blur_passes` (2), `font_mono` (Hack Nerd Font), `icon_theme` (Papirus-Dark),
`opencode_theme`, `icon`. Se editan en Settings → Appearance y Fonts & cursor.

Forma extendida (opcionales; los defaults son los valores de siempre, así que un tema que no los
define se ve igual):

| Campo | Qué hace | Default |
|---|---|---|
| `border_size` | Grosor del borde de ventana | `2` |
| `border_style` | `solid` = `primary` · `gradient` = `primary` → `secondary` · `rotating` = el gradiente gira | `solid` |
| `border_angle` | Ángulo del gradiente (grados) | `45` |
| `gaps_in` / `gaps_out` | Gaps entre ventanas / contra el borde de pantalla | `4` / `8` |
| `inactive_opacity` | Opacidad de las ventanas sin foco | `0.95` |
| `dim_inactive` / `dim_strength` | Oscurecer las ventanas sin foco y cuánto | `false` / `0.5` |
| `blur_noise` / `blur_contrast` / `blur_brightness` / `blur_vibrancy` | Ajuste fino del blur | `0.0117` / `0.8916` / `1.0` / `0.1696` |
| `blur_popups` | Blur también en menús y tooltips | `false` |
| `shadow_enabled` / `shadow_range` / `shadow_power` | Sombra: on/off, alcance (px), caída 1–4 | `true` / `8` / `3` |
| `shadow_style` | `dark` = gris casi negro · `glow` = halo del `primary` | `dark` |
| `animations` | Preset `smooth` · `snappy` · `bouncy` · `off` (`config/hypr/animations/<preset>.conf`) | `smooth` |
| `font_size` | Tamaño base: kitty = N, rofi y workspaces de waybar = N−1, waybar, dunst y GTK = N−3 | `13` |
| `font_ui` | Fuente de interfaz GTK (también por `gsettings`); vacío = `Sans 10` | vacío |

Todo eso llega a Hyprland por `config/hypr/theme.conf.tpl` (que se carga antes que
`hyprland.conf`, por eso `hyprland.conf` ya no define gaps, borde, sombra ni animaciones).

`wallpaper` se busca por nombre en `EXTRA_WALLPAPER_DIRS`, `~/.local/share/backgrounds` y
`assets/wallpapers`. Una ruta absoluta también funciona, pero el doctor avisa (no es portable).

### Tokens derivados

`@text_muted@`, `@text_dim@`, `@text_sub@` (mezclas de primer plano y fondo),
`@radius_outer@` (radio + 4), `@opacity_secondary@`, `@opacity_rofi@`, `@opacity_tui@`,
`@ansi_*` (paleta de 16 colores de kitty), `@primary_hex@`/`@secondary_hex@`/`@background_hex@`/`@foreground_hex@`/`@chip_battery_hex@`/`@chip_bluetooth_hex@`
(sin `#`; los usan Hyprland y `config/hypr/hyprtoolkit.conf.tpl`, el diálogo de polkit), `@radius_half@` (radio / 2),
`@background_r/g/b`, `@font_mono_alt@` (variante "Mono" de Hack para gtklock y SDDM),
`@active_border@` (sólido o gradiente), `@shadow_color@`, `@borderangle_anim@`,
`@font_size_m1@` / `@font_size_m3@` (tamaño base −1 / −3), `@gtk_font@` (`font_ui` + tamaño, o `Sans 10`)
y `@font_ui_or_mono@` (`font_ui`, o `font_mono` si el tema no define una; la usan los widgets de escritorio).

También hay tokens del usuario (de `user.conf` y autodetección): `@user_display_name@`,
`@user_title@`, `@terminal@`, `@browser@`, `@file_manager@`, `@editor_gui@`, `@kb_layout@`,
`@dotfiles@`, `@home@`, `@banner_xml@`, `@banner_qml@`, `@hw_cursor_env@`.

## Plantillas

Un archivo `algo.ext.tpl` con `@token@` dentro se renderiza a `algo.ext`. Para tematizar
una app nueva:

1. Copiá su config a `config/<app>/archivo.tpl` y reemplazá los colores por tokens.
2. Agregá la salida (`/config/<app>/archivo`) a `.gitignore` (el CI lo exige).
3. `theme <tema-actual>` y comprobá el resultado. Un token inexistente se avisa por stderr.

## Crear un tema

```bash
cp -r themes/nord themes/mi-tema
# editá themes/mi-tema/theme.json (name, colores) y poné "wallpaper": "mi-tema.jpg"
scripts/gen-assets.sh mi-tema      # genera assets/wallpapers/mi-tema.jpg y su preview.png
theme mi-tema
```

`gen-assets.sh` crea un wallpaper original (degradado con la paleta) y una preview; si
preferís tu imagen, ponela en `~/.local/share/backgrounds/` y usá su nombre.

## Temas propios

`~/.config/dotfiles/themes/<id>/theme.json` (fuera del repo) tiene prioridad sobre
`themes/<id>/`: `theme <id>` usa tu copia si existe. Ahí guardan
[Settings](settings.md) → Theme editor (temas nuevos o editados), Appearance (radio, opacidad,
blur) y Fonts & cursor (fuente e íconos): si el tema activo es del repo, primero lo copian. Para
volver al original, borrá tu copia y aplicá el tema de nuevo.

**Desde un wallpaper**: Theme editor → `w` elige una imagen (de tus carpetas de wallpapers o
cualquier archivo) y arma los colores (`tools/settings/sections/wallpalette.py`): fondo = el oscuro
más frecuente llevado a ~12 % de luz, rampa `chip_*` mezclando fondo y texto, `primary` = el color
más vivo y presente con contraste ≥ 4.5 contra el fondo, `secondary` = otro tono a más de 30° y
verde/ámbar/rojo de estado con la saturación del acento. Conserva la forma del tema base; `n` lo
guarda en `~/.config/dotfiles/themes/<id>/` con un `preview.png` (el wallpaper con la paleta abajo).

## Temas incluidos

| Id | Nombre | Primary | Fondo | Fuente | Iconos |
|---|---|---|---|---|---|
| `atom-dark` | ATOM DARK | `#61afef` | `#282c34` | Hack Nerd Font | Papirus-Dark |
| `brown-earth` | BROWN EARTH | `#b6896d` | `#1d1a22` | InputMonoEx Nerd Font | AdwaitaLegacy |
| `catppuccin-mocha` | CATPPUCCIN MOCHA | `#89b4fa` | `#1e1e2e` | InputMonoNarrow Nerd Font | Papirus-Dark |
| `chill-lofi` | CHILL LOFI | `#c9d3a8` | `#28181b` | InputMono Nerd Font | Papirus-Light |
| `ciberpunk` | CIBERPUNK | `#ff2a6d` | `#0d0f1a` | InputMonoCompressed Nerd Font | HighContrast |
| `data-center` | DATA CENTER | `#04f9a9` | `#0a1517` | InputMonoCondensed Nerd Font | breeze-dark |
| `everforest` | EVERFOREST | `#a7c080` | `#2d353b` | InputMono Nerd Font | Papirus-Dark |
| `gray-terminal` | GRAY TERMINAL | `#808080` | `#0d0d0d` | Hack Nerd Font | HighContrast |
| `green-geek` | GREEN GEEK | `#00ff41` | `#0a0a0a` | InputMonoNarrow Nerd Font | Papirus-Dark |
| `gruvbox` | GRUVBOX | `#d79921` | `#282828` | InputMonoCompressed Nerd Font | Papirus |
| `kanagawa-dragon` | KANAGAWA DRAGON | `#8ba4b0` | `#181616` | InputMonoNarrow Nerd Font | breeze |
| `nord` | NORD | `#81a1c1` | `#2e3440` | InputMono Nerd Font | breeze-dark |
| `oxocarbon-dark` | OXOCARBON DARK | `#be95ff` | `#161616` | InputMonoCondensed Nerd Font | HighContrast |
| `purple-sky` | PURPLE SKY | `#9b59b6` | `#0d0d1a` | InputMonoEx Nerd Font | Papirus |
| `red-dark` | RED DARK | `#c62828` | `#0f0f10` | Hack Nerd Font | Papirus-Dark |
| `solarized-dark` | SOLARIZED DARK | `#268bd2` | `#002b36` | InputMonoCondensed Nerd Font | Adwaita |
| `tokyo-night` | TOKYO NIGHT | `#7aa2f7` | `#1a1b26` | InputMono Nerd Font | breeze-dark |

Las fuentes `InputMono*` las instala `ttf-input-nerd`; los iconos, `papirus-icon-theme`,
`breeze-icons`, `adwaita-icon-theme-legacy` y `gnome-themes-extra` (todos en `install/packages/base.txt`).
