#!/usr/bin/env python3
"""Módulo waybar "custom/claude-agents": uso de los proveedores de IA activos
en ~/.config/dotfiles/agents.conf (los mismos que muestra la TUI de agentes).

Texto: ícono + el % de la ventana de 5 h más alto entre los activos (Claude
Code, Codex) o de la cuota más usada (Antigravity). Tooltip: una línea por
proveedor. Liviano a propósito (sin Textual): waybar lo corre cada 30 s.
Las fuentes de datos son las de tools/agents_tui.py.
"""
import json
import os
import time
from pathlib import Path

HOME = Path.home()
CONF = Path(os.environ.get("AGENTS_PROVIDERS") or Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "dotfiles" / "agents.conf")
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
AGY_CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "agents" / "agy"
ICON = "󰚩"


def enabled():
    try:
        return {k.strip() for k, _, v in (l.partition("=") for l in CONF.read_text().splitlines())
                if not k.startswith("#") and v.strip() == "on"}
    except OSError:
        return {"claude", "opencode"}


def claude():
    try:
        u = json.loads((HOME / ".claude" / "usage-cache.json").read_text())
    except (OSError, ValueError):
        return None
    f, s = u.get("five_hour_pct"), u.get("seven_day_pct")
    return None if f in (None, "") else (float(f), None if s in (None, "") else float(s))


def codex():
    base = CODEX_HOME / "sessions"
    files = []
    for i in range(7):
        d = time.localtime(time.time() - i * 86400)
        day = base / f"{d.tm_year:04d}" / f"{d.tm_mon:02d}" / f"{d.tm_mday:02d}"
        if day.is_dir():
            files += day.glob("rollout-*.jsonl")
    for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        limits = None
        for line in f.read_text(errors="replace").splitlines():
            if '"token_count"' in line and '"rate_limits"' in line:
                try:
                    limits = json.loads(line)["payload"].get("rate_limits") or limits
                except (ValueError, KeyError):
                    pass
        if limits:
            w = {}
            for k in ("primary", "secondary"):
                x = limits.get(k) or {}
                mins = int(x.get("window_minutes") or 0)
                if x:
                    w["5h" if mins <= 360 else "7d"] = float(x.get("used_percent") or 0)
            if "5h" in w or "7d" in w:
                return (w.get("5h", w.get("7d")), w.get("7d"))
    return None


def antigravity():
    best = None
    for f in sorted(AGY_CACHE.glob("*.json") if AGY_CACHE.is_dir() else [], key=os.path.getmtime, reverse=True):
        try:
            quota = json.loads(f.read_text())["payload"].get("quota") or {}
        except (OSError, ValueError, KeyError):
            continue
        used = [(1 - float(q["remaining_fraction"])) * 100 for q in quota.values() if "remaining_fraction" in q]
        if used:
            best = (max(used), None)
            break
    return best


on = enabled()
rows, top = [], None
for pid, name, fn, labels in (("claude", "Claude Code", claude, ("5h", "7d")),
                              ("codex", "Codex", codex, ("5h", "7d")),
                              ("antigravity", "Antigravity", antigravity, ("quota", None))):
    if pid not in on:
        continue
    v = fn()
    if v is None:
        rows.append(f"{name}: no data")
        continue
    main, second = v
    top = main if top is None else max(top, main)
    rows.append(f"{name}: {labels[0]} {main:.0f}%" + (f" · {labels[1]} {second:.0f}%" if labels[1] and
                                                       second is not None else ""))
if "opencode" in on:
    rows.append("opencode: context per session (open the panel)")

text = f"{ICON} {top:.0f}%" if top is not None else ICON
cls = "normal" if top is None or top < 50 else "warning" if top < 80 else "critical"
tooltip = "AI agents\n" + ("\n".join(rows) if rows else "no providers enabled") + "\nClick to open the panel"
print(json.dumps({"text": text, "tooltip": tooltip, "class": cls}, ensure_ascii=False))
