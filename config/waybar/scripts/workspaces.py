#!/usr/bin/env python3
"""Indicador de workspaces de waybar (custom/workspaces): delega en
hypr/scripts/hypr-workspaces.py y, si falla, devuelve un JSON de error."""
import os
import subprocess

SCRIPT = os.path.expanduser("~/.config/hypr/scripts/hypr-workspaces.py")

if not os.path.exists(SCRIPT):
    print('{"text": "⚠️", "tooltip": "Script not found: %s", "class": "error"}' % SCRIPT, end="")
else:
    r = subprocess.run(["python3", SCRIPT], capture_output=True, text=True)
    print(r.stdout, end="")
    if r.returncode != 0:
        print('{"text": "⛔", "tooltip": "Workspace error", "class": "error"}', end="")
