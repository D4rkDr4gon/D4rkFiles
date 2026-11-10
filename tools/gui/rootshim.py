#!/usr/bin/env python3
"""rootshim.py — `sudo` de reemplazo para yay mientras la GUI corre una actualización del AUR
(`yay --sudo rootshim.py`). Pasa el comando (solo pacman) al helper root de la GUI por un socket
del usuario que existe solo durante ese trabajo (DOTFILES_GUI_ROOTSOCK). Así yay no pide la
huella otra vez ni necesita terminal."""

import json
import os
import socket
import sys

args = sys.argv[1:]
while args and args[0].startswith("-"):          # flags de sudo (-v, --) se ignoran
    if args[0] in ("-v", "--validate"):
        sys.exit(0)
    args = args[1:]
if not args:
    sys.exit(0)
path = os.environ.get("DOTFILES_GUI_ROOTSOCK", "")
if not path:
    sys.exit("rootshim: no GUI root socket")
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(path)
f = s.makefile("rw")
f.write(json.dumps({"argv": args}) + "\n")
f.flush()
res = json.loads(f.readline() or '{"rc": 1, "out": "no answer"}')
sys.stdout.write((res.get("out") or "") + "\n")
sys.exit(res.get("rc", 1))
