-- LazyVim usa snacks.nvim para el dashboard. Se pisa solo `dashboard.preset.header`
-- (merge de opts, no reemplaza el resto de snacks: bigfile/notifier/etc.) con el
-- arte del proyecto (assets/banner-art.txt, el mismo del prompt de zsh y de la
-- pantalla de bloqueo). Sin ese archivo queda el header por defecto de LazyVim.
--
-- Colores del header y de los textos: NO se tocan acá. Los define
-- config/highlights.lua (grupos SnacksDashboard*), que sigue al tema activo.
local function banner()
  local root = vim.env.DOTFILES_DIR or (vim.fn.expand("~") .. "/.local/share/dotfiles")
  local f = io.open(root .. "/assets/banner-art.txt", "r")
  if not f then
    return nil
  end
  local art = f:read("*a")
  f:close()
  return art
end

return {
  "snacks.nvim",
  opts = {
    dashboard = {
      preset = {
        header = banner(),
      },
    },
  },
}
