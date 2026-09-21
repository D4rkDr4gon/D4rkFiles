#!/usr/bin/env python3
"""
Dual-WM workspace indicator for Waybar.
Detecta si estamos en Hyprland o Qtile y delega al script correspondiente.

Misma salida JSON para mantener compatibilidad con Waybar.
"""
import os
import subprocess
import sys

HYPRLAND_SCRIPTS = os.path.expanduser("~/.config/hypr/scripts")
QTILE_SCRIPTS = os.path.expanduser("~/.config/waybar/scripts")


def is_hyprland():
    return "HYPRLAND_INSTANCE_SIGNATURE" in os.environ


def is_qtile():
    try:
        result = subprocess.run(
            ["pgrep", "-x", "qtile"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def main():
    if is_hyprland():
        script = os.path.join(HYPRLAND_SCRIPTS, "hypr-workspaces.py")
    elif is_qtile():
        script = os.path.join(QTILE_SCRIPTS, "qtile-workspaces.py")
    else:
        # Fallback: intentar qtile
        script = os.path.join(QTILE_SCRIPTS, "qtile-workspaces.py")

    if os.path.exists(script):
        result = subprocess.run(["python3", script], capture_output=True, text=True)
        print(result.stdout, end="")
        if result.returncode != 0:
            print(
                '{"text": "⛔", "tooltip": "Workspace error", "class": "error"}',
                end="",
            )
    else:
        print(
            '{"text": "⚠️", "tooltip": f"Script not found: {script}", "class": "error"}',
            end="",
        )


if __name__ == "__main__":
    main()
