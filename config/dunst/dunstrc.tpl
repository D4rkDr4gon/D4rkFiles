[global]
    ### Display ###
    monitor = 0
    follow = mouse
    width = 350
    notification_limit = 5
    origin = top-right
    offset = (30, 50)
    indicate_hidden = yes
    shrink = no
    transparency = 0
    separator_height = 2
    padding = 16
    horizontal_padding = 16
    frame_width = 0
    sort = yes
    idle_threshold = 120

    ### Text ###
    font = @font_mono@ 10
    line_height = 4
    markup = full
    format = "<b>%s</b>\n%b"
    alignment = left
    vertical_alignment = center
    show_age_threshold = 60
    word_wrap = yes
    ellipsize = middle
    ignore_newline = no

    ### Duplicates ###
    stack_duplicates = true
    hide_duplicate_count = false
    show_indicators = yes

    ### Icons ###
    icon_position = left
    min_icon_size = 32
    max_icon_size = 64
    icon_path = /usr/share/icons/Adwaita/32x32/status/:/usr/share/icons/Adwaita/32x32/devices/:/usr/share/icons/hicolor/32x32/apps/

    ### History ###
    sticky_history = yes
    history_length = 20

    ### Shortcuts ###
    close = mod4+shift+period
    close_all = mod4+shift+comma
    history = mod4+period

    ### Misc ###
    browser = /usr/bin/firefox
    always_run_script = true
    title = Dunst
    class = Dunst
    corner_radius = @radius@
    ignore_dbusclose = false
    force_xwayland = false

[urgency_low]
    background = "@chip_battery@"
    foreground = "@text_muted@"
    timeout = 10
    highlight = "@chip_wlan@"

[urgency_normal]
    background = "@chip_battery@"
    foreground = "@foreground@"
    timeout = 15
    highlight = "@primary@"

[urgency_critical]
    background = "@chip_battery@"
    foreground = "@foreground@"
    timeout = 0
    highlight = "@status_error@"

# Reglas de No Molestar y apps silenciadas: dunstrc.d/50-dnd.conf, generado por
# config/rofi/scripts/dnd-menu.sh (dunst carga dunstrc.d/*.conf automáticamente).
