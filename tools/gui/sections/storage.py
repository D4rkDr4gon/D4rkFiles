"""Storage (GUI): paridad con StorageView — discos removibles e internos (lsblk), montar/desmontar
particiones removibles (udisksctl, sin root), abrir el punto de montaje y expulsar (desmonta todo y
apaga el dispositivo, con confirmación). Las internas las maneja fstab: solo se muestran."""

from __future__ import annotations

import shutil

from . import _lib as L

UI: dict = {}
STATE: dict = {"parts": {}}


def T():
    return L.tui_module("storage")


def bar(pct: float) -> str:
    k = max(0, min(10, round(pct / 10)))
    return "▓" * k + "░" * (10 - k) + f" {pct:3.0f}%"


def get() -> dict:
    t = T()
    devs = t.disks()
    rem = [d for d in devs if d.get("rm") or d.get("hotplug") or d.get("tran") == "usb"]
    internal = [d for d in devs if d not in rem and d.get("type") == "disk" and not d["name"].startswith(("zram", "loop"))]
    STATE["parts"] = {}
    groups = []
    for label, ds in (("Removable", rem), ("Internal", internal)):
        rows = []
        for d in ds:
            removable = label == "Removable"
            rows.append(L.item(f"disk:{d['path']}", d.get("model") or d["name"], sub=d["path"], right=t.gb(d.get("size")), glyph="󰋊",
                               on=True, actions=[L.action(f"eject:{d['path']}", "Eject", True)] if removable else []))
            for p in d.get("children") or []:
                mounts = [m for m in (p.get("mountpoints") or []) if m]
                mnt = mounts[0] if mounts else None
                use = ""
                if mnt and mnt != "[SWAP]":
                    du = shutil.disk_usage(mnt)
                    use = " · " + bar(du.used * 100 / du.total)
                STATE["parts"][p["path"]] = {"mount": mnt, "disk": d["path"], "removable": removable, "fstype": p.get("fstype")}
                acts = []
                if removable and p.get("fstype"):
                    acts.append(L.action(f"toggle:{p['path']}", "Unmount" if mnt else "Mount"))
                if mnt and mnt != "[SWAP]":
                    acts.append(L.action(f"open:{p['path']}", "Open"))
                rows.append(L.item(f"part:{p['path']}", "└ " + (p.get("label") or p["name"]),
                                   sub=f"{p.get('fstype') or '—'} · {(mnt.replace(str(L.Path.home()), "~", 1) if mnt else "not mounted")}{use}",
                                   right=t.gb(p.get("size")), on=bool(mnt), glyph="", actions=acts))
        groups.append(L.group(label, rows or [L.info(f"none{label}", "None connected", "")]))
    return L.page("Storage", "Mount, open and eject drives (udisksctl) · internal ones are managed by fstab", groups, refresh=5)


def set_value(key, value):
    return L.fail("Unknown setting")


def err(r) -> str:
    out = (r.stderr or r.stdout).strip().splitlines()
    return out[-1] if out else "udisksctl failed"


def act(key: str, text=None):
    op, _, path = key.partition(":")
    parts = STATE["parts"]
    if op in ("part", "toggle"):
        p = parts.get(path)
        if not p:
            return L.ok()
        if not p["removable"]:
            return L.fail("Internal partitions are managed by fstab, not from here")
        if not p["fstype"]:
            return L.fail("No filesystem on that partition")
        r = L.run(["udisksctl", "unmount" if p["mount"] else "mount", "-b", path], timeout=30)
        return L.ok(r.stdout.strip() or "Done") if r.returncode == 0 else L.fail(err(r))
    if op == "open":
        p = parts.get(path)
        if p and p["mount"]:
            L.detach(["xdg-open", p["mount"]])
        return L.ok()
    if op == "disk":
        return L.ok()
    if op == "eject":
        if not any(p["disk"] == path and p["removable"] for p in parts.values()):
            return L.fail("Select a removable drive")
        if not L.yes(text):
            return L.confirm(key, "Eject drive", f"Unmount and power off {path}?", ok_label="Eject")
        for pp, p in parts.items():
            if p["disk"] == path and p["mount"]:
                L.run(["udisksctl", "unmount", "-b", pp], timeout=30)
        r = L.run(["udisksctl", "power-off", "-b", path], timeout=30)
        return L.ok("Safe to remove") if r.returncode == 0 else L.fail(err(r))
    return L.ok()
