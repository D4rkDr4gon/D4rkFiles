#!/usr/bin/env python3
"""
Workspace indicator for Hyprland → Waybar.
Reemplaza a qtile-workspaces.py cuando se está ejecutando Hyprland.

Usa hyprctl para obtener el estado de los workspaces y emite el mismo
formato JSON que qtile-workspaces.py para mantener compatibilidad con Waybar.
"""
import json
import re
import subprocess
import os
import sys

THEME_CSS = os.path.expanduser("~/.config/waybar/theme.css")

WORKSPACE_NAMES = {
    1: "  ",
    2: "  ",
    3: "  ",
    4: "  ",
    5: "  ",
    6: "  "
}


def load_theme_colors():
    colors = {
        "primary": "#c62828",
        "background-alt": "#1a1a1a",
        "foreground": "#c5c8c6",
        "foreground-alt": "#8a8a8a",
        "alert": "#ff4444",
    }
    try:
        with open(THEME_CSS) as f:
            for line in f:
                m = re.match(r"@define-color\s+(\S+)\s+#?([0-9a-fA-F]+)", line)
                if m:
                    colors[m.group(1)] = "#" + m.group(2)
    except FileNotFoundError:
        pass
    return colors


def hyprctl_json(*args):
    result = subprocess.run(
        ["hyprctl"] + list(args) + ["-j"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def get_workspaces():
    """Obtener workspaces via hyprctl"""
    try:
        workspaces_raw = hyprctl_json("workspaces")
        active_raw = hyprctl_json("activeworkspace")
    except Exception:
        return [], []

    if not workspaces_raw or not isinstance(workspaces_raw, list):
        return [], []

    active_name = active_raw.get("name", "") if active_raw else ""
    active_id = active_raw.get("id", -1) if active_raw else -1

    workspaces = []
    names = []

    for i in range(1, 7):  # Workspaces 1-6
        label = WORKSPACE_NAMES.get(i, str(i))

        # Buscar info del workspace i
        ws_info = None
        for ws in workspaces_raw:
            if ws.get("id") == i:
                ws_info = ws
                break

        is_active = (active_id == i or active_name == str(i))
        has_windows = ws_info is not None and ws_info.get("windows", 0) > 0

        workspaces.append({
            "name": str(i),
            "label": label,
            "active": is_active,
            "occupied": has_windows,
            "urgent": False,
        })
        names.append(f"Workspace {i}")

    return workspaces, names


def format_output(workspaces, names, colors):
    parts = []
    for ws in workspaces:
        if ws["active"]:
            fg = colors.get("primary", "#c62828")
            bg = colors.get("background-alt", "#1a1a1a")
            parts.append(
                f'<span foreground="{fg}" background="{bg}" font_weight="bold">{ws["label"]}</span>'
            )
        elif ws["occupied"]:
            fg = colors.get("foreground", "#c5c8c6")
            parts.append(f'<span foreground="{fg}">{ws["label"]}</span>')
        else:
            fg = colors.get("foreground-alt", "#555555")
            parts.append(f'<span foreground="{fg}">{ws["label"]}</span>')

    text = " ".join(parts)
    output = {
        "text": text,
        "tooltip": " | ".join(names),
        "class": "workspaces",
    }
    return json.dumps(output)


if __name__ == "__main__":
    colors = load_theme_colors()
    workspaces, names = get_workspaces()
    print(format_output(workspaces, names, colors))
