-- Statusline real (antes no había ninguno activo — lua/plugins/example.lua
-- traía un lualine de muestra pero deshabilitado). Estilo "Flat Minimal"
-- explícito: sin separadores powerline, colores tomados de config.colors
-- (la misma paleta que theme-switch.sh reescribe con sed en cada cambio de
-- tema), así el statusline sigue al tema sin necesitar un target nuevo.
return {
  "nvim-lualine/lualine.nvim",
  event = "VeryLazy",
  opts = function()
    local c = require("config.colors")

    local dotfiles_theme = {
      normal = {
        a = { bg = c.red_border, fg = c.bg, gui = "bold" },
        b = { bg = c.bg_alt, fg = c.fg },
        c = { bg = c.bg, fg = c.fg },
      },
      insert = { a = { bg = c.red, fg = c.bg, gui = "bold" } },
      visual = { a = { bg = c.fg, fg = c.bg, gui = "bold" } },
      replace = { a = { bg = c.red, fg = c.bg, gui = "bold" } },
      command = { a = { bg = c.red_border, fg = c.bg, gui = "bold" } },
      inactive = {
        a = { bg = c.bg, fg = c.bg_alt },
        b = { bg = c.bg, fg = c.bg_alt },
        c = { bg = c.bg, fg = c.bg_alt },
      },
    }

    return {
      options = {
        theme = dotfiles_theme,
        globalstatus = true,
        component_separators = "",
        section_separators = "",
      },
      sections = {
        lualine_a = { "mode" },
        lualine_b = { "branch", "diff", "diagnostics" },
        lualine_c = { { "filename", path = 1 } },
        lualine_x = { "filetype" },
        lualine_y = { "progress" },
        lualine_z = { "location" },
      },
    }
  end,
}
