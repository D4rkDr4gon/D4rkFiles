# Generado desde theme.conf.tpl por scripts/theme-switch.sh — no editar.
# Colores, forma (borde, gaps, rounding, opacidad, blur, sombra, animaciones) y
# opacidad por app del tema activo. Campos y defaults: docs/themes.md.

general {
    col.active_border = @active_border@
    col.inactive_border = rgb(@chip_battery_hex@)
    border_size = @border_size@
    gaps_in = @gaps_in@
    gaps_out = @gaps_out@
}

decoration {
    rounding = @radius@
    inactive_opacity = @inactive_opacity@
    dim_inactive = @dim_inactive@
    dim_strength = @dim_strength@

    blur {
        enabled = @blur_enabled@
        size = @blur_size@
        passes = @blur_passes@
        noise = @blur_noise@
        contrast = @blur_contrast@
        brightness = @blur_brightness@
        vibrancy = @blur_vibrancy@
        popups = @blur_popups@
    }

    shadow {
        enabled = @shadow_enabled@
        range = @shadow_range@
        render_power = @shadow_power@
        color = @shadow_color@
    }
}

# Animaciones: preset del tema (smooth | snappy | bouncy | off) + el borde, que
# gira en loop con border_style = rotating.
source = ~/.config/hypr/animations/@animations@.conf
animations {
    animation = @borderangle_anim@
}

# Opacidad por app. Kitty usa la base; rofi un poco menos; el resto un poco más.
windowrule = match:class ^(kitty)$, opacity @opacity@ override
windowrule = match:class ^(rofi)$, opacity @opacity_rofi@ override
windowrule = match:class ^(obsidian)$, opacity @opacity_secondary@ override
windowrule = match:class ^(sublime_text)$, opacity @opacity_secondary@ override
windowrule = match:class ^(Thunar)$, opacity @opacity_secondary@ override
windowrule = match:class ^(dunst)$, opacity @opacity_secondary@ override
windowrule = match:class ^(remmina)$, opacity @opacity_secondary@ override
windowrule = match:class ^(spotify)$, opacity @opacity_secondary@ override

# TUIs flotantes: siempre casi opacos para que se lean con cualquier tema.
windowrule = match:class ^(claude-agents)$, opacity @opacity_tui@ override
windowrule = match:class ^(cliamp)$, opacity @opacity_tui@ override
windowrule = match:class ^(bluetui)$, opacity @opacity_tui@ override
windowrule = match:class ^(impala)$, opacity @opacity_tui@ override
windowrule = match:class ^(vpn-tui)$, opacity @opacity_tui@ override
windowrule = match:class ^(shortcuts)$, opacity @opacity_tui@ override
windowrule = match:class ^(hyprmon)$, opacity @opacity_tui@ override
windowrule = match:class ^(dotfiles-update)$, opacity @opacity_tui@ override
