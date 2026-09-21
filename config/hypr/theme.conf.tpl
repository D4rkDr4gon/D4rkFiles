# Generado desde theme.conf.tpl por scripts/theme-switch.sh — no editar.
# Colores, forma (rounding, blur) y opacidad por app del tema activo.

general {
    col.active_border = rgb(@primary_hex@)
    col.inactive_border = rgb(@chip_battery_hex@)
}

decoration {
    rounding = @radius@

    blur {
        enabled = @blur_enabled@
        size = @blur_size@
        passes = @blur_passes@
    }
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
