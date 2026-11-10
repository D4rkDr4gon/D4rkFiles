"""Default apps: aplicaciones predeterminadas por categoría (xdg-mime)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import _lib as L

CATEGORIES = [
    ("browser", "Web browser", ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]),
    ("files", "File manager", ["inode/directory"]),
    ("text", "Text editor", ["text/plain", "text/markdown", "application/x-shellscript"]),
    ("pdf", "PDF viewer", ["application/pdf"]),
    ("image", "Image viewer", ["image/png", "image/jpeg", "image/webp", "image/gif"]),
    ("video", "Video player", ["video/mp4", "video/x-matroska", "video/webm"]),
    ("audio", "Music player", ["audio/mpeg", "audio/flac", "audio/ogg"]),
    ("mail", "Email", ["x-scheme-handler/mailto"]),
]
APP_DIRS = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications",
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"), Path("/usr/share/applications")]


def desktop_apps() -> dict[str, dict]:
    apps: dict[str, dict] = {}
    for d in APP_DIRS:
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            if f.name in apps:
                continue
            try:
                main = f.read_text(errors="ignore").split("\n[", 1)[0]
            except OSError:
                continue
            if re.search(r"^(NoDisplay|Hidden)=true", main, re.M):
                continue
            nm = re.search(r"^Name=(.+)$", main, re.M)
            mt = re.search(r"^MimeType=(.+)$", main, re.M)
            apps[f.name] = {"name": nm.group(1).strip() if nm else f.stem,
                            "mimes": set(filter(None, mt.group(1).split(";"))) if mt else set()}
    return apps


def current_default(mime: str) -> str:
    return L.run(["xdg-mime", "query", "default", mime]).stdout.strip()


def get() -> dict:
    apps = desktop_apps()
    rows = []
    for key, label, mimes in CATEGORIES:
        cur = current_default(mimes[0])
        names = sorted({a["name"] for a in apps.values() if a["mimes"] & set(mimes)}, key=str.lower)
        cname = apps.get(cur, {}).get("name", cur or "not set")
        if cname not in names:
            names.insert(0, cname)
        rows.append(L.choice(key, label, ", ".join(mimes)[:70], cname, names))
    return L.page("Default apps", "xdg-mime · ~/.config/mimeapps.list", [L.group("Categories", rows)])


def set_value(key: str, value):
    cat = next((c for c in CATEGORIES if c[0] == key), None)
    if not cat:
        return L.fail("Unknown category")
    apps = desktop_apps()
    did = next((d for d, a in apps.items() if a["name"] == value and a["mimes"] & set(cat[2])), None)
    if not did:
        return L.fail("App not found")
    L.run(["xdg-mime", "default", did, *cat[2]])
    if key == "browser":
        L.run(["xdg-settings", "set", "default-web-browser", did])
    return L.ok(f"{cat[1]}: {value}")


def act(key, text=None):
    return L.ok()
