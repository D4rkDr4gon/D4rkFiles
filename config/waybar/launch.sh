#!/usr/bin/env bash
# Reinicia waybar (lo usa theme-switch.sh y el autostart).
pkill -x waybar 2>/dev/null

while pgrep -x waybar >/dev/null; do sleep 0.2; done

setsid -f waybar >/dev/null 2>&1
