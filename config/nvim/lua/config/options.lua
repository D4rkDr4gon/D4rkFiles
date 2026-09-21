-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here

-- Regla "Flat Minimal" (ver docs/design-system.md): línea activa resaltada
-- con relleno (no un marco), y separadores de split sin línea de contraste
-- marcada — coherente con el resto del sistema (dunst/rofi/waybar, sin
-- bordes, solo fondos planos).
vim.opt.cursorline = true
vim.opt.fillchars:append({ vert = " ", vertright = " ", vertleft = " " })
