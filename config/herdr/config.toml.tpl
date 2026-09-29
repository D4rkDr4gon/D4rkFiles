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

# --- Plugins (los instala la etapa "herdr" del instalador) --------------------
# herdr-pet (nikok6/herdr-pet): mascota animada sobre los paneles de agentes
[[keys.command]]
key = "prefix+shift+p"
type = "plugin_action"
command = "pet.toggle"
description = "pet: toggle"

[[keys.command]]
key = "prefix+shift+o"
type = "plugin_action"
command = "pet.settings"
description = "pet: settings"

# herdr-plugin-manager (speardragon/herdr-plugin-manager): gestor de plugins +
# marketplace en popup (prefix+p ya es previous_tab)
[[keys.command]]
key = "prefix+shift+m"
type = "plugin_action"
command = "ray.plugin-manager.open"
description = "plugin manager"

# herdr-agent-usage (levi-qiao/herdr-agent-usage): cuota/contexto de Claude y
# opencode en el sidebar (filas en [ui.sidebar.agents])
[[keys.command]]
key = "prefix+shift+r"
type = "plugin_action"
command = "herdr-agent-usage.refresh"
description = "refresh all agent quotas"

[[keys.command]]
key = "prefix+shift+q"
type = "plugin_action"
command = "herdr-agent-usage.open-settings"
description = "open agent quota settings"

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
agent_panel_sort = "spaces" # herdr-agent-usage

[ui.toast]
delivery = "herdr"
delay_seconds = 1

# Filas de cuota de herdr-agent-usage (formato "gauges"). Los comentarios
# "# herdr-agent-usage" son las marcas con las que el plugin reconoce y
# desinstala sus filas: no borrarlos. Colores del tema activo.
[ui.sidebar]

[ui.sidebar.agents]
row_gap = 0 # herdr-agent-usage
rows = [[{ token = "$quota_group", bold = true, dim = false }], [{ token = "$quota_icon", fg = "@foreground@", bold = false, dim = false, rules = [{ contains = "⁠", fg = "@status_ok@" }, { contains = "⁡", fg = "@status_warn@" }, { contains = "⁢", fg = "@status_error@" }] }, { token = "$quota_provider_model", fg = "@foreground@", bold = true, dim = false }], [{ token = "$quota_model", fg = "@foreground@", bold = false, dim = false }], [{ token = "$quota_error", fg = "@status_warn@", bold = false, dim = false }], [{ token = "$quota_context_normal", fg = "@status_ok@", bold = false, dim = false }, { token = "$quota_context_warning", fg = "@status_warn@", bold = false, dim = false }, { token = "$quota_context_danger", fg = "@status_error@", bold = false, dim = false }], [{ token = "$quota_nest_gap", bold = false, dim = false }]] # herdr-agent-usage-row

# Protocolo gráfico de kitty (lo necesita herdr-pet para dibujar la mascota)
[experimental]
kitty_graphics = true
