import os

from libqtile.config import Key
from libqtile.lazy import lazy
from libqtile.utils import guess_terminal

# Variables
# mod4 => Windows/super mod1=ALT mod5=ALTGR

from . import user

# lazy.spawn() no usa una shell, asi que "$HOME" no se expande solo:
# resolvemos las rutas reales en tiempo de carga.
HOME = str(user.HOME)
DOTFILES = str(user.DOTFILES)

mod = "mod4"
terminal = user.terminal()
browser = user.browser()
file_manager = user.file_manager()
editor = user.editor()
# theme = "../../../usr/share/rofi/themes/Arc-Dark.rasi"

# Configuring a key "Key(<key press>, <key press>, command, desc="description of command"),"

keys = [
    
    # ============= Aplication shortcuts =============
    # Open Apps
    Key([mod], "f", lazy.spawn(file_manager), desc="opens file system"),
    # Walker (elephant) es Wayland-only (gtk4-layer-shell) — en X11/Qtile
    # seguimos con el buscador combi de rofi (apps+comandos+calc+web, ver
    # docs/design-system.md).
    Key([mod], "space", lazy.spawn(f"sh {HOME}/.config/rofi/scripts/spotlight-launch.sh"), desc="opens app manager"),
    Key([mod], "k", lazy.spawn(f'kitty --class shortcuts --title Shortcuts -e python3 {DOTFILES}/tools/shortcuts_tui.py'), desc="cheatsheet de shortcuts, ver + editar"),
    Key([mod], "b", lazy.spawn(browser), desc="opens browser"),
    Key([mod], "Return", lazy.spawn(terminal), desc="opens terminal"),
    Key([mod, "shift"], "Return", lazy.spawn(f"{HOME}/.config/herdr/launch.sh"), desc="opens herdr"),
    Key([mod], "s", lazy.spawn(editor), desc="Launch editor"),

    # ============= Utilities =============
    
    # Volume control
    Key([], "XF86AudioRaiseVolume", lazy.spawn("pactl set-sink-volume @DEFAULT_SINK@ +5%"), desc="Volume up"),
    Key([], "XF86AudioLowerVolume", lazy.spawn("pactl set-sink-volume @DEFAULT_SINK@ -5%"), desc="Volume down"),
    Key([], "XF86AudioMute", lazy.spawn("pactl set-sink-mute @DEFAULT_SINK@ toggle"), desc="Mute/Unmute audio"),
    Key([], "XF86AudioMicMute", lazy.spawn("pactl set-source-mute @DEFAULT_SOURCE@ toggle"), desc="Mute/Unmute micro"),
    
    # Brightness controls
    Key([], "XF86MonBrightnessUp", lazy.spawn("brightnessctl set +10%"), desc="Brightness up"),
    Key([], "XF86MonBrightnessDown", lazy.spawn("brightnessctl set 10%-"), desc="Brightness down"),
    
    # Take screenshots
    Key([mod, "shift"], "s", lazy.spawn(f"{DOTFILES}/scripts/screenshot.sh"), desc="take screenshot"),
    Key([], "print", lazy.spawn(f"{DOTFILES}/scripts/screenshot.sh"), desc="take screenshot"),
  
    #Clipboard control
    Key([mod], "v", lazy.spawn("copyq toggle"), desc = "clipboard History"),

    # ============= Navigating Shortcuts =============

    # Moving between workspaces
    Key([mod, "shift"], "space", lazy.spawn(f"sh {HOME}/.config/rofi/scripts/settings-menu.sh"), desc="Open settings menu"),

    # Move between tabs and workspaces in qtile
    Key(["mod1"], "Tab", lazy.layout.next(), desc="move between tabs"),
    Key([mod], "Tab", lazy.next_layout(), desc="move between workspaces"),
    Key([mod], "q", lazy.window.kill(), desc="close focussed tab"),
    Key([mod, "shift"], "f", lazy.window.toggle_fullscreen(), desc="fullscreen of focussed tab"),
    Key([mod], "t", lazy.window.toggle_floating(), desc="floating focussed tab"),
    
    # Moving between Monitors (mismos atajos que Hyprland: Mod+. / Mod+,)
    Key([mod], "period", lazy.next_screen(), desc="Mover foco al siguiente monitor"),
    Key([mod], "comma", lazy.prev_screen(), desc="Mover foco al monitor anterior"),

    # ============= Mosaic config Shortcuts =============
    
    # Working with multiple Monitors
    # Key([mod, "shft"], "d", lazy.spawn("display-monitors"), desc="Launch multiple monitor view"),

    # Moving out of range in Columns layout will create new column.
    Key([mod, "shift"], "Left", lazy.layout.shuffle_left(), desc="Move window to the left"),
    Key([mod, "shift"], "Right", lazy.layout.shuffle_right(), desc="Move window to the right"),
    Key([mod, "shift"], "Down", lazy.layout.shuffle_down(), desc="Move window down"),
    Key([mod, "shift"], "Up", lazy.layout.shuffle_up(), desc="Move window up"),
    # Grow windows. If current window is on the edge of screen and direction

    # will be to screen edge - window would shrink.
    Key([mod, "control"], "Left", lazy.layout.grow_left(), desc="Grow window to the left"),
    Key([mod, "control"], "Right", lazy.layout.grow_right(), desc="Grow window to the right"),
    Key([mod, "control"], "Down", lazy.layout.grow_down(), desc="Grow window down"),
    Key([mod, "control"], "Up", lazy.layout.grow_up(), desc="Grow window up"),
    Key([mod], "n", lazy.layout.normalize(), desc="Reset all window sizes"), 

    # ============= qtile internal =============

    # Actions for qtile
    Key([mod, "control"], "r", lazy.reload_config(), lazy.spawn(f"{DOTFILES}/scripts/barupdate.sh"),  desc="reloads qtiles's configuration"),
    Key([mod], "l", lazy.spawn(f"sh {HOME}/.config/rofi/scripts/action-menu.sh"), desc="blocks PC"),

    # =========== qtile stacks ================
    # Moving between stacks 
    Key(["control"], "Tab", lazy.layout.down(), desc="Next window in stack"),
    Key(["control", "shift"], "Tab", lazy.layout.up(), desc="Prev window in stack"),
    #Working wiht stacks
    Key([mod, "mod1"], "s", lazy.layout.add(), desc="Add new stack"),
    Key([mod, "mod1"], "d", lazy.layout.delete(), desc="Delete current stack"),
    Key([mod, "mod1"], "m", lazy.layout.client_to_next(), desc="Move window to next stack"),
    Key([mod, "mod1"], "n", lazy.layout.client_to_previous(), desc="Move window to prev stack"),
    # Para reorganizar ventanas dentro del stack
    Key([mod, "control"], "j", lazy.layout.shuffle_down(), desc="Shuffle window down"),
    Key([mod, "control"], "k", lazy.layout.shuffle_up(), desc="Shuffle window up"),
]
