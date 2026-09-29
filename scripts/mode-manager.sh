#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# mode-manager.sh — TUI (fzf) para crear/editar/aplicar modos de escritorio
# Se abre desde Settings → MODES → Gestionar modos, en una kitty flotante.
# Un modo es un conjunto de apps, cada una en un workspace; lo aplica
# scripts/mode-switch.sh. Para agregar una app se elige una ventana
# abierta (toma la clase exacta y el comando de su .desktop) o se carga
# a mano. Los modos viven en ~/.config/dotfiles/modes.conf (fuera del
# repo; se crea al guardar el primero). Requiere Hyprland, fzf y jq.
# ──────────────────────────────────────────────────────────
set -uo pipefail

# shellcheck source=/dev/null
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"
CONF="$DOTFILES_CONF_DIR/modes.conf"
EXAMPLE="$DOTFILES_DIR/modes.conf.example"
MODE_SWITCH="$DOTFILES_DIR/scripts/mode-switch.sh"
STATE="$DOTFILES_STATE_DIR/desktop-mode"   # último modo aplicado (lo escribe mode-switch.sh)
MANAGER_CLASS="modes"          # clase de la kitty flotante de este TUI
DEFAULT_ICON="󰕮"
# Terminales: todas comparten clase, así que se identifican por título
TERMINALS='^(kitty|foot|Alacritty|org\.wezfurlong\.wezterm|com\.mitchellh\.ghostty)$'
NEW_MODE="+  Nuevo modo"
NEW_APP="+  Agregar app"

bold=$'\e[1m'; dim=$'\e[2m'; red=$'\e[31m'; green=$'\e[32m'; reset=$'\e[0m'

pause() { read -rsn1 -p "${dim}Tecla para volver...${reset}"; echo; }

ensure_conf() {
    [[ -f "$CONF" ]] && return
    mkdir -p "$(dirname "$CONF")"
    if [[ -r "$EXAMPLE" ]]; then cp "$EXAMPLE" "$CONF"; else : > "$CONF"; fi
}

# Formato de modes.conf: modo|ícono|workspace|match|comando|nombre
# Una línea sin workspace es la cabecera del modo (existe aunque no tenga apps).
entries() { [[ -r "$CONF" ]] && grep -vE '^\s*(#|$)' "$CONF"; }

mode_exists() { entries | awk -F'|' -v m="$1" '$1 == m {f=1} END {exit !f}'; }

mode_icon() {
    entries | awk -F'|' -v m="$1" -v d="$DEFAULT_ICON" \
        '$1 == m && $2 != "" {print $2; f=1; exit} END {if (!f) print d}'
}

# Reescribe CONF con awk (se pasan los -v y el programa)
conf_awk() {
    local tmp
    tmp="$(mktemp)"
    awk -F'|' -v OFS='|' "$@" "$CONF" > "$tmp" && cat "$tmp" > "$CONF"
    rm -f "$tmp"
}

# modo<TAB>ícono  modo<TAB>resumen de workspaces
list_modes() {
    entries | awk -F'|' '
        !($1 in icon) { order[++n] = $1; icon[$1] = "" }
        $2 != "" && icon[$1] == "" { icon[$1] = $2 }
        $3 != "" {
            app = ($6 != "") ? $6 : $5; sub(/ .*/, "", app); sub(/.*\//, "", app)
            sum[$1] = sum[$1] (sum[$1] == "" ? "" : "  ") $3 ":" app
        }
        END {
            for (i = 1; i <= n; i++) {
                m = order[i]
                printf "%s\t%s  %s\t%s\n", m, (icon[m] == "" ? "󰕮" : icon[m]), m,
                    (sum[m] == "" ? "(sin apps)" : sum[m])
            }
        }'
}

# nro de línea<TAB>WS n<TAB>nombre<TAB>match  (apps de un modo, por workspace)
list_apps() {
    [[ -r "$CONF" ]] || return 0
    awk -F'|' -v m="$1" '
        /^[[:space:]]*(#|$)/ { next }
        $1 == m && $3 != "" {
            app = ($6 != "") ? $6 : $5; sub(/ .*/, "", app); sub(/.*\//, "", app)
            printf "%d\tWS %s\t%s\t%s\n", NR, $3, app, $4
        }' "$CONF" | sort -t$'\t' -k2,2V
}

# Escapa un texto para usarlo como regex literal. El | se reemplaza por "."
# porque es el separador de modes.conf.
regex_escape() { sed -e 's/[][\.*^$+?(){}/\\]/\\&/g' -e 's/|/./g' <<<"$1"; }

# Exec y Name del .desktop de una clase (por StartupWMClass o por nombre
# de archivo), sin los códigos %u/%F/... (ni el flag que los precede,
# ej. "--url -- %u"). Imprime "exec<TAB>nombre".
desktop_for_class() {
    local class="${1,,}" dir f base wm
    for dir in "${XDG_DATA_HOME:-$HOME/.local/share}/applications" \
               "$HOME/.local/share/flatpak/exports/share/applications" \
               /var/lib/flatpak/exports/share/applications /usr/share/applications; do
        for f in "$dir"/*.desktop; do
            [[ -r "$f" ]] || continue
            base="$(basename "$f" .desktop)"
            wm="$(grep -m1 '^StartupWMClass=' "$f" | cut -d= -f2-)"
            [[ "${wm,,}" == "$class" || "${base,,}" == "$class" ]] || continue
            awk -F= '
                /^\[/ { main = ($0 == "[Desktop Entry]") }
                main && /^Exec=/ && !e { sub(/^Exec=/, ""); e = $0 }
                main && /^Name=/ && !n { sub(/^Name=/, ""); n = $0 }
                END { gsub(/ (--?[a-zA-Z-]+ )?(-- )?%[a-zA-Z]/, "", e); printf "%s\t%s\n", e, n }' "$f"
            return 0
        done
    done
    return 1
}

read_workspace() {
    local ws="${1:-}"
    while true; do
        read -rep "Workspace (1-9): " -i "$ws" ws
        [[ -z "$ws" ]] && return 1
        [[ "$ws" =~ ^[1-9]$ ]] && { printf '%s' "$ws"; return 0; }
        echo "${red}Tiene que ser un número del 1 al 9${reset}"
    done
}

read_mode_name() {
    local name="${1:-}" orig="${1:-}"
    while true; do
        read -rep "Nombre del modo: " -i "$name" name
        name="${name//|/}"
        [[ -z "$name" ]] && return 1
        if [[ "$name" != "$orig" ]] && mode_exists "$name"; then
            echo "${red}Ya existe un modo llamado \"$name\"${reset}"; continue
        fi
        printf '%s' "$name"; return 0
    done
}

create_mode() {
    clear
    echo "${bold}Nuevo modo${reset}  ${dim}(vacío para cancelar)${reset}"
    echo
    local name icon
    name="$(read_mode_name)" || return
    read -rep "Ícono (Nerd Font, opcional): " -i "$DEFAULT_ICON" icon
    icon="${icon//|/}"
    ensure_conf
    printf '%s|%s||||\n' "$name" "$icon" >> "$CONF"
    edit_mode "$name"
}

rename_mode() {
    local old="$1" name icon
    clear
    echo "${bold}Renombrar $old${reset}  ${dim}(vacío para cancelar)${reset}"
    echo
    name="$(read_mode_name "$old")" || return
    read -rep "Ícono: " -i "$(mode_icon "$old")" icon
    icon="${icon//|/}"
    # El ícono queda solo en la primera línea del modo
    conf_awk -v o="$old" -v n="$name" -v i="$icon" \
        '$1 == o { $1 = n; $2 = (done ? "" : i); done = 1 } { print }'
    [[ "$(cat "$STATE" 2>/dev/null)" == "$old" ]] && echo "$name" > "$STATE"
}

delete_mode() {
    local mode="$1" ok
    clear
    read -rn1 -p "¿Borrar el modo ${bold}$mode${reset}? Las apps no se cierran. [s/N] " ok; echo
    [[ "$ok" =~ ^[sS]$ ]] || return
    conf_awk -v m="$mode" '/^[[:space:]]*#/ || $1 != m'
    echo "${green}✓ $mode borrado${reset}"; pause
}

# Guarda una app en el modo (append al final de CONF)
save_app() {
    local mode="$1" ws="$2" match="$3" cmd="$4" name="$5"
    printf '%s||%s|%s|%s|%s\n' "$mode" "$ws" "$match" "$cmd" "${name//|/}" >> "$CONF"
    echo "${green}✓ $name → workspace $ws${reset}"
}

add_app() {
    local mode="$1" pick
    pick="$( { printf '%s\t%s\t\t\t\n' "-" "✎  Cargar a mano"
               hyprctl clients -j | jq -r --arg me "$MANAGER_CLASS" '
                   .[] | select(.class != "" and .class != $me)
                   | [.pid, "WS \(.workspace.id)", .class, .title] | @tsv'; } \
        | fzf --reverse --no-sort --delimiter=$'\t' --with-nth=2,3,4 --tabstop=4 \
            --prompt="Agregar a $mode > " --info=hidden \
            --header=$'Elegí una ventana abierta · esc volver\n')" || return

    local pid class title match cmd name info
    IFS=$'\t' read -r pid _ class title <<<"$pick"
    clear
    echo "${bold}Agregar app a $mode${reset}  ${dim}(vacío para cancelar)${reset}"
    echo

    if [[ "$pid" == "-" ]]; then
        read -rep "Nombre: " name; [[ -z "$name" ]] && return
        read -rep "Comando: " cmd; [[ -z "$cmd" ]] && return
        echo "${dim}match = class:<regex> o title:<regex> (ver hyprctl clients)${reset}"
        read -rep "Match: " -i "class:^$(regex_escape "$(basename "${cmd%% *}")")$" match
        [[ "$match" =~ ^(class|title): ]] || { echo "${red}El match empieza con class: o title:${reset}"; pause; return; }
    else
        if [[ "$class" =~ $TERMINALS ]]; then
            match="title:^$(regex_escape "$title")$"
            name="$title"
        else
            match="class:^$(regex_escape "$class")$"
            name="$class"
        fi
        if [[ ! "$class" =~ $TERMINALS ]] && info="$(desktop_for_class "$class")"; then
            cmd="${info%%$'\t'*}"
            [[ -n "${info#*$'\t'}" ]] && name="${info#*$'\t'}"
        else
            # Sin .desktop (o terminal): el comando con que se lanzó el proceso
            cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | sed 's/ $//')"
        fi
        read -rep "Nombre: " -i "$name" name; [[ -z "$name" ]] && return
        read -rep "Comando: " -i "$cmd" cmd; [[ -z "$cmd" ]] && return
        echo "  ${bold}Match${reset}   $match"
    fi

    local ws
    ws="$(read_workspace)" || return
    save_app "$mode" "$ws" "$match" "${cmd//|/}" "$name"
    pause
}

edit_app() {
    local line="$1" field="$2" label="$3" value
    value="$(sed -n "${line}p" "$CONF" | cut -d'|' -f"$field")"
    clear
    if [[ "$field" == 3 ]]; then
        value="$(read_workspace "$value")" || return
    else
        read -rep "$label: " -i "$value" value
        value="${value//|/}"
        [[ -z "$value" ]] && return
    fi
    conf_awk -v l="$line" -v f="$field" -v v="$value" 'NR == l { $f = v } { print }'
}

remove_app() {
    local line="$1" name="$2" ok
    clear
    read -rn1 -p "¿Quitar ${bold}$name${reset} del modo? [s/N] " ok; echo
    [[ "$ok" =~ ^[sS]$ ]] || return
    conf_awk -v l="$line" 'NR != l'
}

edit_mode() {
    local mode="$1" out key line
    while mode_exists "$mode"; do
        out="$( { printf '%s\t%s\t\t\n' "-" "$NEW_APP"; list_apps "$mode"; } \
            | fzf --reverse --no-sort --delimiter=$'\t' --with-nth=2,3 --tabstop=4 \
                --prompt="$(mode_icon "$mode")  $mode > " --info=hidden \
                --header=$'enter workspace · ctrl-e comando · ctrl-n nombre · ctrl-d quitar · esc volver\n' \
                --expect=ctrl-e,ctrl-n,ctrl-d)" || return

        key="$(sed -n 1p <<<"$out")"
        line="$(sed -n 2p <<<"$out")"
        [[ -z "$line" ]] && return
        local nr name
        IFS=$'\t' read -r nr _ name _ <<<"$line"

        if [[ "$nr" == "-" ]]; then
            [[ -z "$key" ]] && add_app "$mode"
            continue
        fi
        case "$key" in
            ctrl-e) edit_app "$nr" 5 "Comando" ;;
            ctrl-n) edit_app "$nr" 6 "Nombre" ;;
            ctrl-d) remove_app "$nr" "$name" ;;
            *)      edit_app "$nr" 3 "Workspace" ;;
        esac
    done
}

command -v hyprctl &>/dev/null || { echo "${red}Los modos requieren Hyprland${reset}"; pause; exit 1; }

while true; do
    out="$( { printf '%s\t%s\t\n' "-" "$NEW_MODE"; list_modes; } \
        | fzf --reverse --no-sort --delimiter=$'\t' --with-nth=2,3 --tabstop=4 \
            --prompt="Modos > " --info=hidden \
            --header=$'enter editar · ctrl-a aplicar · ctrl-r renombrar · ctrl-d borrar · esc salir\n' \
            --expect=ctrl-a,ctrl-r,ctrl-d)" || exit 0

    key="$(sed -n 1p <<<"$out")"
    line="$(sed -n 2p <<<"$out")"
    [[ -z "$line" ]] && exit 0
    mode="${line%%$'\t'*}"

    if [[ "$mode" == "-" ]]; then
        [[ -z "$key" ]] && create_mode
        continue
    fi
    case "$key" in
        ctrl-a) setsid -f bash "$MODE_SWITCH" "$mode" >/dev/null 2>&1; exit 0 ;;
        ctrl-r) rename_mode "$mode" ;;
        ctrl-d) delete_mode "$mode" ;;
        *)      edit_mode "$mode" ;;
    esac
done
