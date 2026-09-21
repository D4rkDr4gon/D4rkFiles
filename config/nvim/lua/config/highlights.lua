-- Aplica la paleta custom (config.colors, la que reescribe theme-switch.sh
-- en cada cambio de tema) sobre tokyonight-night.
--
-- Antes este módulo se cargaba desde lua/config/init.lua, que a su vez no
-- lo requería nadie (ni init.lua raíz ni lazy.lua) — código muerto real,
-- nunca se ejecutaba. Ahora se registra desde config/autocmds.lua (que
-- LazyVim sí carga automáticamente en VeryLazy) y además se reaplica en
-- cada evento ColorScheme, para sobrevivir a un `:colorscheme` manual o a
-- un reload de plugins.
--
-- OJO — dos cosas confirmadas en runtime (headless, no adivinadas):
-- 1) No forzamos `:colorscheme` acá: LazyVim aplica el suyo por defecto
--    (`require("tokyonight").load()`, sin style -> "moon") DESPUÉS de
--    cargar este archivo dentro del mismo callback de "VeryLazy", así que
--    cualquier `vim.cmd("colorscheme ...")` puesto acá quedaría pisado.
-- 2) Un autocmd de "ColorScheme" NO alcanza como único mecanismo: LazyVim
--    llama a `require("tokyonight").load()` DIRECTAMENTE (no al comando
--    `:colorscheme`), y es el COMANDO `:colorscheme` el que dispara el
--    evento ColorScheme en Vim/Neovim — la función del plugin sola no lo
--    dispara. Por eso `apply()` nunca corría pese a que el autocmd sí
--    quedaba registrado a tiempo.
-- Solución: `vim.schedule(apply)` — corre en el próximo tick del event
-- loop, después de que termine todo el callback de VeryLazy (incluida la
-- llamada a colorscheme de LazyVim), sin depender de qué mecanismo haya
-- usado el plugin para aplicarse. El autocmd de ColorScheme se deja además
-- como respaldo, por si el usuario cambia de colorscheme a mano más tarde
-- con el comando real `:colorscheme` (ese sí dispara el evento).
local c = require("config.colors")

local function apply()
  local hl = vim.api.nvim_set_hl
  hl(0, "Normal", { bg = c.bg, fg = c.fg })
  hl(0, "NormalFloat", { bg = c.bg_alt, fg = c.fg })
  hl(0, "CursorLine", { bg = c.bg_alt })
  hl(0, "Visual", { bg = c.red_border })
  hl(0, "Search", { bg = c.red, fg = c.bg })
  hl(0, "IncSearch", { bg = c.red, fg = c.bg })
  hl(0, "Pmenu", { bg = c.bg_alt, fg = c.fg })
  hl(0, "PmenuSel", { bg = c.red_border, fg = c.fg })
  hl(0, "LineNr", { fg = c.bg_alt })
  hl(0, "CursorLineNr", { fg = c.red })
  -- Separadores de split "invisibles" (se funden con el fondo) — regla
  -- Flat Minimal: sin líneas de marco marcadas entre paneles.
  hl(0, "VertSplit", { fg = c.bg, bg = c.bg })
  hl(0, "WinSeparator", { fg = c.bg, bg = c.bg })
  hl(0, "StatusLine", { bg = c.bg_alt, fg = c.fg })
  hl(0, "StatusLineNC", { bg = c.bg, fg = c.bg_alt })

  -- Dashboard (snacks.nvim, ver plugins/dashboard.lua) — mismo mecanismo
  -- de re-aplicación que el resto de este archivo, así el ASCII header y
  -- los textos siguen la paleta activa (rojo del tema, no el celeste por
  -- defecto de tokyonight) en cada cambio de tema.
  hl(0, "SnacksDashboardHeader", { fg = c.red, bold = true })
  hl(0, "SnacksDashboardTitle", { fg = c.red, bold = true })
  hl(0, "SnacksDashboardIcon", { fg = c.red_border })
  hl(0, "SnacksDashboardKey", { fg = c.red, bold = true })
  hl(0, "SnacksDashboardDesc", { fg = c.fg })
  hl(0, "SnacksDashboardFooter", { fg = c.fg, italic = true })
  hl(0, "SnacksDashboardSpecial", { fg = c.red_border })
  hl(0, "SnacksDashboardNormal", { bg = c.bg, fg = c.fg })
end

-- LazyVim carga este archivo en momentos distintos según cómo se abra
-- nvim: con un archivo como argumento, "autocmds" (y por lo tanto este
-- módulo) se carga YA, antes de registrar su propio autocmd de "VeryLazy"
-- (así que un autocmd nuestro de "VeryLazy" registrado acá correría
-- ANTES que el de LazyVim, por orden de registro — perdemos igual); sin
-- argumento, se difiere y se carga recién DENTRO del propio callback de
-- "VeryLazy" de LazyVim (así que un autocmd nuestro para ese mismo evento,
-- agregado a mitad de su propio despacho, no llega a dispararse en ese
-- ciclo). Ambos casos confirmados en runtime con `nvim --headless`. La
-- única forma que funciona en los dos casos por igual es un delay real de
-- reloj (no un `vim.schedule`/autocmd, que dependen del orden exacto de
-- callbacks): `vim.defer_fn` unos milisegundos después, tiempo de sobra
-- para que LazyVim ya haya terminado de aplicar su colorscheme por
-- cualquiera de los dos caminos.
vim.defer_fn(apply, 50)

-- Respaldo: si el usuario cambia de colorscheme a mano más tarde con el
-- comando real `:colorscheme` (dispara ColorScheme; `require(x).load()`
-- llamado directo, como hace LazyVim arriba, NO lo dispara).
vim.api.nvim_create_autocmd("ColorScheme", {
  group = vim.api.nvim_create_augroup("dotfiles_highlights", { clear = true }),
  callback = apply,
})

return { apply = apply }
