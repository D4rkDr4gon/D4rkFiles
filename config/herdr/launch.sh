#!/usr/bin/env bash
# Abre Herdr. El binario ya detecta automáticamente si hay un servidor
# corriendo y se conecta a él, o arranca una sesión nueva si no hay
# ninguna (auto_detect_launch) — no hace falta lógica de attach propia.
# Pensado para bindearse a SUPER+SHIFT+RETURN (Hyprland y Qtile).
set -e

exec kitty --title herdr -e herdr
