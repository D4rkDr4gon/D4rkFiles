#!/usr/bin/env bash
# Workspace switcher for Qtile + Waybar
# Usage: qtile-workspace-switch.sh next|prev

# El socket de Qtile depende del display Wayland de la sesión (no siempre wayland-0).
ACTION="${1:-}" WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" python3 -c "
import json, subprocess, sys, os

SOCKET = os.path.expanduser('~/.cache/qtile/qtilesocket.' + os.environ['WAYLAND_DISPLAY'])

def r(*args):
    r = subprocess.run(['qtile', 'cmd-obj', '-s', SOCKET] + list(args), capture_output=True, text=True)
    return r.stdout.strip()

groups = json.loads(r('-o', 'cmd', '-f', 'get_groups'))
names = list(groups.keys())
focused = json.loads(r('-o', 'group', '-f', 'info'))
focused_name = focused.get('name', '')
idx = names.index(focused_name) if focused_name in names else 0

action = os.environ['ACTION']
if action == 'next':
    idx = (idx + 1) % len(names)
elif action == 'prev':
    idx = (idx - 1) % len(names)
else:
    sys.exit(1)

from libqtile.command.client import CommandClient
from libqtile.command.graph import CommandGraphRoot
from libqtile.command.interface import IPCCommandInterface
from libqtile.ipc import Client

ipc_client = Client(SOCKET)
root = IPCCommandInterface(ipc_client)
cmd = CommandClient(root)
obj = cmd.navigate('group', names[idx])
obj.call('toscreen')
"
