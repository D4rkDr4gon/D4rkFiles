#!/usr/bin/env bash
# Menú de actualización (Settings → UPDATE): cada opción corre
# scripts/dotfiles-update.sh en una ventana de kitty aparte, porque necesita
# terminal para sudo (huella/contraseña) y para mostrar el progreso.

UPDATE_SH="${DOTFILES_DIR:-$HOME/.local/share/dotfiles}/scripts/dotfiles-update.sh"
CLASS="dotfiles-update"

items=$(printf "󰍉  CHECK\n󰚰  FULL UPDATE\n󰄄  SNAPSHOT\n󰑗  ROLLBACK\n󰣇  PACMAN\n󰏗  AUR (YAY)\n󰃢  CLEAN\n󰆴  ORPHANS\n")
# lines = cantidad de opciones, para que se vean todas sin scroll
choice=$(printf '%s\n' "$items" \
    | rofi -dmenu -p "Update" -theme "$HOME/.config/rofi/theme.rasi" \
        -theme-str "listview { lines: $(wc -l <<<"$items"); }" \
        -theme-str 'entry { placeholder: "Snapshot, update o limpieza..."; }')
[[ -z "$choice" ]] && exit 0

case "$choice" in
    *"CHECK")       mode=check;    title="Pendientes" ;;
    *"FULL UPDATE") mode=all;      title="Update completo" ;;
    *"SNAPSHOT")    mode=snapshot; title="Snapshot" ;;
    *"ROLLBACK")    mode=rollback; title="Snapshots" ;;
    *"PACMAN")      mode=pacman;   title="Update pacman" ;;
    *"AUR (YAY)")   mode=aur;      title="Update AUR" ;;
    *"CLEAN")       mode=clean;    title="Limpieza" ;;
    *"ORPHANS")     mode=orphans;  title="Huérfanos" ;;
    *) exit 0 ;;
esac

exec kitty --class "$CLASS" --title "$title" \
    bash -c '"$0" "$1"; echo; read -rp "Enter para cerrar..." _' "$UPDATE_SH" "$mode"
