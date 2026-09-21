# ==============================================================================
# Herdr — Configuración custom
# Gestionado por dotfiles ($DOTFILES/herdr/config.toml)
# Los colores de [theme.custom] son generados por scripts/theme-switch.sh
# a partir del tema activo en themes/<tema>/theme.json (incluye los colores
# de estado status_ok/status_warn/status_error) — no editar a mano los
# valores de color, se pisan en cada "theme <nombre>".
# ==============================================================================

onboarding = false

[keys]
prefix = "ctrl+space"

# Navegación de tabs/paneles
new_tab = "prefix+c"
next_tab = ["prefix+n", "ctrl+alt+]"]
previous_tab = ["prefix+p", "ctrl+alt+["]
split_horizontal = "prefix+minus"
switch_tab = "prefix+1..9"
switch_workspace = "prefix+shift+1..9"
focus_agent = "prefix+alt+1..9"
next_agent = "prefix+a"

# Comandos custom
[[keys.command]]
key = "prefix+alt+g"
type = "popup"
command = "lazygit"
description = "run lazygit"
width = "80%"
height = "80%"

[[keys.command]]
key = "prefix+alt+e"
type = "popup"
command = "nvim"
description = "quick nvim editor"
width = "80%"
height = "80%"

[[keys.command]]
key = "prefix+alt+o"
type = "popup"
command = "opencode"
description = "run opencode"
width = "80%"
height = "80%"

[[keys.command]]
key = "prefix+alt+t"
type = "popup"
command = "btop"
description = "resource monitor"
width = "70%"
height = "70%"

[[keys.command]]
key = "prefix+alt+d"
type = "popup"
command = "lazydocker"
description = "run lazydocker"
width = "80%"
height = "80%"

[theme]
name = "terminal"

[theme.custom]
sidebar_bg = "@background@"
active_row_bg = "@chip_bluetooth@"
selection_bg = "@secondary@"
panel_bg = "reset"
accent = "@primary@"
green = "@status_ok@"
blue = "@chip_audio@"
red = "@status_error@"
yellow = "@status_warn@"

[terminal]
default_shell = ""
shell_mode = "auto"
new_cwd = "follow"

[ui]
tab_bar_position = "bottom"
status_indicators = "symbols"
window_title = "herdr: {workspace}"

[ui.toast]
delivery = "herdr"
delay_seconds = 1
