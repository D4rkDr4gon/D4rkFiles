-- Generado desde theme.lua.tpl por scripts/theme-switch.sh — no editar.
-- Colores, forma (borde, gaps, rounding, opacidad, blur, sombra, animaciones) y
-- opacidad por app del tema activo. Campos y defaults: docs/themes.md.

hl.config({
    general = {
        col = {
            active_border   = @active_border@,
            inactive_border = "rgb(@chip_battery_hex@)",
        },
        border_size = @border_size@,
        gaps_in     = @gaps_in@,
        gaps_out    = @gaps_out@,
    },
    decoration = {
        rounding         = @radius@,
        inactive_opacity = @inactive_opacity@,
        dim_inactive     = @dim_inactive@,
        dim_strength     = @dim_strength@,
        blur = {
            enabled    = @blur_enabled@,
            size       = @blur_size@,
            passes     = @blur_passes@,
            noise      = @blur_noise@,
            contrast   = @blur_contrast@,
            brightness = @blur_brightness@,
            vibrancy   = @blur_vibrancy@,
            popups     = @blur_popups@,
        },
        shadow = {
            enabled      = @shadow_enabled@,
            range        = @shadow_range@,
            render_power = @shadow_power@,
            color        = "@shadow_color@",
        },
    },
})

-- Animaciones: preset del tema (smooth | snappy | bouncy | off) + el borde, que
-- gira en loop con border_style = rotating.
dofile(os.getenv("HOME") .. "/.config/hypr/animations/@animations@.lua")
@borderangle_anim@

-- Opacidad por app. Kitty usa la base; rofi un poco menos; el resto un poco más.
local function opacity(class, value)
    hl.window_rule({ match = { class = "^(" .. class .. ")$" }, opacity = value .. " override" })
end
opacity("kitty", "@opacity@")
opacity("rofi", "@opacity_rofi@")
for _, class in ipairs({ "obsidian", "sublime_text", "Thunar", "dunst", "remmina", "spotify" }) do
    opacity(class, "@opacity_secondary@")
end

-- TUIs flotantes: siempre casi opacos para que se lean con cualquier tema.
for _, class in ipairs({ "claude-agents", "cliamp", "bluetui", "impala", "vpn-tui",
                         "shortcuts", "hyprmon", "dotfiles-update" }) do
    opacity(class, "@opacity_tui@")
end
