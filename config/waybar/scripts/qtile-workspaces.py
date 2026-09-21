#!/usr/bin/env python3
import json
import re
import subprocess
import os

THEME_CSS = os.path.expanduser("~/.config/waybar/theme.css")


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


def run_qtile(*args):
    result = subprocess.run(
        ["qtile", "cmd-obj"] + list(args),
        capture_output=True, text=True
    )
    return result.stdout.strip()


def get_workspaces():
    groups_raw = run_qtile("-o", "cmd", "-f", "get_groups")
    groups = json.loads(groups_raw)

    focused_raw = run_qtile("-o", "group", "-f", "info")
    focused = json.loads(focused_raw)
    focused_name = focused.get("name", "")

    workspaces = []
    names = []
    for name, info in groups.items():
        screen = info.get("screen")
        has_windows = len(info.get("windows", [])) > 0
        is_active = name == focused_name

        workspaces.append({
            "name": name,
            "label": info.get("label", name),
            "active": is_active,
            "occupied": screen is not None or has_windows,
            "urgent": False,
        })
        names.append(f"Workspace {name}")

    return workspaces, names


def format_output(workspaces, names, colors):
    parts = []
    for ws in workspaces:
        if ws["active"]:
            fg = colors.get("primary", "#c62828")
            bg = colors.get("background-alt", "#1a1a1a")
            parts.append(f'<span foreground="{fg}" background="{bg}" font_weight="bold">{ws["label"]}</span>')
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
