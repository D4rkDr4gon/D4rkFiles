#!/usr/bin/env bash

SETTINGS_DIR="$(cd "$(dirname "$0")" && pwd)"
DOTFILES="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}"
# shellcheck source=/dev/null
source "$DOTFILES/scripts/lib/env.sh"
THEMES_DIR="$DOTFILES/themes"
THEME_SWITCH="$DOTFILES/scripts/theme-switch.sh"
CURRENT_THEME="$DOTFILES_STATE_DIR/current_theme.json"

show_main_menu() {
    local items
    items=$(printf "  THEMES\n  WORKSPACES\n󰏓  APPS\n  SEARCH\n  BACKGROUNDS\n  NOTIFICATIONS\n  SHORTCUTS\n󰍹  DISPLAYS\n󰚰  UPDATE\n")
    # lines = cantidad de opciones, para que se vean todas sin scroll
    printf '%s\n' "$items" \
        | rofi -dmenu -p "Settings" -theme "$HOME/.config/rofi/theme.rasi" \
            -theme-str "listview { lines: $(wc -l <<<"$items"); }" \
            -theme-str 'entry { placeholder: "Choose an option..."; }'
}

list_themes() {
    local names=()
    local dirs=()

    for theme_dir in "$THEMES_DIR"/*/; do
        [[ -d "$theme_dir" ]] || continue
        local json="$theme_dir/theme.json"
        [[ -f "$json" ]] || continue
        local name
        name=$(jq -r '.name // "unknown"' "$json" 2>/dev/null)
        local icon
        icon=$(jq -r '.icon // ""' "$json" 2>/dev/null)
        local dir_name
        dir_name=$(basename "$theme_dir")
        names+=("${icon:+$icon  }$name")
        dirs+=("$dir_name")
    done

    while true; do
        local selection
        selection=$(printf '%s\n' "${names[@]}" | rofi -dmenu -p "Themes" \
            -theme "$HOME/.config/rofi/theme.rasi" \
            -theme-str 'entry { placeholder: "Select a theme..."; }')

        [[ -z "$selection" ]] && exit 0

        local selected_dir=""
        local selected_name="$selection"
        for i in "${!names[@]}"; do
            if [[ "${names[$i]}" == "$selection" ]]; then
                selected_dir="${dirs[$i]}"
                break
            fi
        done
        [[ -z "$selected_dir" ]] && exit 0

        local preview_path="$THEMES_DIR/$selected_dir/preview.png"
        local has_preview=false
        [[ -f "$preview_path" ]] && has_preview=true

        local action
        if $has_preview; then
            local tmpdir
            tmpdir=$(mktemp -d)
            local thumbnail="$tmpdir/preview.jpg"
            convert "$preview_path" -resize 800x400^ -gravity north -extent 800x400 "$thumbnail" 2>/dev/null

            action=$(printf "✓  APPLY\n←  GO BACK\n" | rofi -dmenu -p "$selected_name" \
                -theme "$HOME/.config/rofi/theme.rasi" \
                -theme-str 'window { background-image: url("'"$thumbnail"'"); background-color: rgba(0,0,0,0.15); width: 800; }' \
                -theme-str 'mainbox { padding: 400px 0 0; background-color: transparent; }' \
                -theme-str 'inputbar { enabled: false; }' \
                -theme-str 'listview { background-color: rgba(10,10,10,0.75); margin: 0 12px 12px; border-radius: 16px; lines: 2; fixed-height: false; }' \
                -theme-str 'element { padding: 12px 16px; border-radius: 12px; }' \
                -theme-str 'element selected { background-color: rgba(51,51,51,0.95); }')

            rm -rf "$tmpdir"
        else
            action=$(printf "✓  APPLY\n←  GO BACK\n" | rofi -dmenu -p "$selected_name" \
                -theme "$HOME/.config/rofi/theme.rasi" \
                -theme-str 'entry { placeholder: "No preview available. Apply?"; }')
        fi

        if [[ "$action" == "✓  APPLY" ]]; then
            bash "$THEME_SWITCH" "$selected_dir"
            exit 0
        fi
    done
}

list_workspaces() {
    bash "$SETTINGS_DIR/workspace-switcher.sh"
}

web_search() {
    bash "$SETTINGS_DIR/web-search.sh"
}

list_backgrounds() {
    local files=()
    local names=()
    local d f base
    local -a dirs
    IFS=: read -ra dirs <<<"$WALLPAPER_DIRS"
    for d in "${dirs[@]}"; do
        for f in "$d"/*.{jpg,jpeg,png,webp}; do
            [[ -f "$f" ]] || continue
            base=$(basename "$f")
            files+=("$f")
            names+=("${base%.*}")
        done
    done
    if ((${#files[@]} == 0)); then
        notify-send "Fondos de pantalla" "No hay imágenes en: $WALLPAPER_DIRS" -t 4000
        exit 0
    fi

    while true; do
        local selection
        selection=$(printf '%s\n' "${names[@]}" | rofi -dmenu -p "Backgrounds" \
            -theme "$HOME/.config/rofi/theme.rasi" \
            -theme-str 'entry { placeholder: "Select a wallpaper..."; }')

        [[ -z "$selection" ]] && exit 0

        local selected_path=""
        for i in "${!names[@]}"; do
            if [[ "${names[$i]}" == "$selection" ]]; then
                selected_path="${files[$i]}"
                break
            fi
        done
        [[ -z "$selected_path" ]] && exit 0

        local tmpdir
        tmpdir=$(mktemp -d)
        local thumbnail="$tmpdir/preview.jpg"
        convert "$selected_path" -resize 800x400^ -gravity center -extent 800x400 "$thumbnail" 2>/dev/null

        local action
        action=$(printf "✓  APPLY\n←  GO BACK\n" | rofi -dmenu -p "" \
            -theme "$HOME/.config/rofi/theme.rasi" \
            -theme-str 'window { background-image: url("'"$thumbnail"'"); background-color: rgba(0,0,0,0.15); width: 800; }' \
            -theme-str 'mainbox { padding: 400px 0 0; background-color: transparent; }' \
            -theme-str 'inputbar { enabled: false; }' \
            -theme-str 'listview { background-color: rgba(10,10,10,0.75); margin: 0 12px 12px; border-radius: 16px; lines: 2; fixed-height: false; }' \
            -theme-str 'element { padding: 12px 16px; border-radius: 12px; }' \
            -theme-str 'element selected { background-color: rgba(51,51,51,0.95); }')

        rm -rf "$tmpdir"

        if [[ "$action" == "✓  APPLY" ]]; then
            # El wallpaper activo vive en el estado del tema (Qtile lo lee de ahí).
            if command -v jq &>/dev/null && [[ -f "$CURRENT_THEME" ]]; then
                local tmp
                tmp=$(mktemp)
                jq --arg wp "$selected_path" '.wallpaper = $wp' "$CURRENT_THEME" > "$tmp" && \
                    mv "$tmp" "$CURRENT_THEME"
            fi

            if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
                # Hyprland: aplicar wallpaper via hyprpaper
                pgrep -x hyprpaper >/dev/null || { setsid -f hyprpaper >/dev/null 2>&1; sleep 0.3; }
                hyprctl hyprpaper wallpaper ",$selected_path"
            else
                if command -v betterlockscreen &>/dev/null; then
                    betterlockscreen -u "$selected_path" >> /tmp/betterlockscreen.log 2>&1 || true
                fi

                qtile cmd-obj -o cmd -f reload_config 2>/dev/null || true
            fi

            bash "$DOTFILES/scripts/barupdate.sh" 2>/dev/null || true
            notify-send "Fondo de pantalla" "Cambiado a $selection" -t 2000
            exit 0
        fi
    done
}

main() {
    local choice
    choice=$(show_main_menu)
    [[ -z "$choice" ]] && exit 0

    case "$choice" in
        "  THEMES"|THEMES)
            list_themes
            ;;
        "  WORKSPACES"|WORKSPACES)
            list_workspaces
            ;;
        "󰏓  APPS"|APPS)
            # Walker en Hyprland, el combi de rofi en Qtile/X11 (Walker no corre
            # bajo X11). Mod+Space usa rofi drun en ambos (ver docs/components.md).
            if [ -n "$HYPRLAND_INSTANCE_SIGNATURE" ]; then
                walker
            else
                bash "$SETTINGS_DIR/spotlight-launch.sh"
            fi
            ;;
        "  SEARCH"|SEARCH)
            web_search
            ;;
        "  BACKGROUNDS"|BACKGROUNDS)
            list_backgrounds
            ;;
        "  NOTIFICATIONS"|NOTIFICATIONS)
            bash "$SETTINGS_DIR/notification-center.sh"
            ;;
        "  SHORTCUTS"|SHORTCUTS)
            bash "$HOME/.config/waybar/scripts/shortcuts-launch.sh"
            ;;
        "󰍹  DISPLAYS"|DISPLAYS)
            bash "$HOME/.config/waybar/scripts/hyprmon-launch.sh"
            ;;
        *"UPDATE")
            bash "$SETTINGS_DIR/update-menu.sh"
            ;;
        *)
            exit 0
            ;;
    esac
}

main
