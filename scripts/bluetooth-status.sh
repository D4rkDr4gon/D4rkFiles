#!/usr/bin/env bash

if rfkill list bluetooth 2>/dev/null | grep -q "Soft blocked: yes"; then
    echo "󰂲"
elif bluetoothctl show 2>/dev/null | grep -q "Powered: no"; then
    echo "󰂲"
elif bluetoothctl devices Connected 2>/dev/null | grep -q .; then
    echo "󰂰"
else
    echo "󰂯"
fi