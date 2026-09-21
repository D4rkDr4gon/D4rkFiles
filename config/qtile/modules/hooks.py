import os
import subprocess
import threading
from libqtile import hook

from . import user


OPACITY_RULES = {
    "obsidian": 0.92,
    "sublime_text": 0.92,
    "subl": 0.92,
    "thunar": 0.92,
    "Thunar": 0.92,
    "rofi": 0.75,
    "dunst": 0.85,
    "kitty": 0.85,
    "electron": 0.85,
}


def _apply_opacity(client, opacity):
    try:
        client.set_opacity(opacity)
    except Exception:
        pass


@hook.subscribe.client_new
def float_and_opacity(client):
    wm_class = " ".join(client.get_wm_class() or [])
    if "firefox" in wm_class:
        if client.floating:
            client.disable_floating()
        if client.maximized:
            client.toggle_maximized()
    for app, opacity in OPACITY_RULES.items():
        if app in wm_class:
            threading.Timer(0.3, _apply_opacity, args=[client, opacity]).start()
            break


# Ventanas que deben aparecer flotando en una posicion/tamaño fijo,
# ancladas a una esquina de la pantalla (widgets tipo popup).
# (ancho, alto, margen desde el borde derecho, margen desde el borde superior)
FLOAT_GEOMETRY = {
    "claude-agents": (900, 760, 16, 40),
    "shortcuts": (900, 620, 16, 40),
}


def _apply_floating_geometry(client, width, height, margin_right, margin_top):
    try:
        if not client.floating:
            client.enable_floating()
        screen = client.qtile.current_screen
        client.set_size_floating(width, height)
        x = screen.x + screen.width - width - margin_right
        y = screen.y + margin_top
        client.set_position_floating(x, y)
        client.bring_to_front()
    except Exception:
        pass


@hook.subscribe.client_new
def float_widgets(client):
    wm_class = " ".join(client.get_wm_class() or [])
    for key, geometry in FLOAT_GEOMETRY.items():
        if key in wm_class:
            threading.Timer(0.15, _apply_floating_geometry, args=[client, *geometry]).start()
            break


@hook.subscribe.startup_once
def autostart():
    home = os.path.expanduser('~')
    is_wayland = 'WAYLAND_DISPLAY' in os.environ

    if is_wayland:
        processes = [
            ['bash', home + '/.config/waybar/launch.sh'],
            ['dunst'],
            ['copyq'],
        ]
    else:
        subprocess.Popen(['xset', 's', 'off'])
        subprocess.Popen(['xset', '-dpms'])

        processes = [
            ['nitrogen', '--restore'],
            ['bash', home + '/.config/polybar/launch.sh'],
            ['picom'],
            ['dunst'],
        ]

    for p in processes:
        try:
            subprocess.Popen(p)
        except Exception as e:
            print(f"Error al iniciar {p}: {e}")

    subprocess.Popen(['bash', str(user.DOTFILES / 'scripts' / 'welcome.sh')])
