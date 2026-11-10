"""Backup (GUI): paridad con BackupView — carpetas de proton-backup/folders.conf con su estado en
vivo (subiendo con %, tamaño, velocidad y ETA; en cola; al día; error; cancelado), detalle (local,
remota, exclusiones, última subida, resultado), actividad reciente de runner.log, subir una o todas,
cancelar (con confirmación), agregar/editar/quitar carpetas con la validación de la TUI (editar
local o remota borra el manifiesto para comparar todo de nuevo), log por carpeta e iniciar sesión
en Proton Drive (en una kitty). Mientras sube, editar está bloqueado como en la TUI."""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from . import _lib as L

UI: dict = {}


def B():
    p = str(L.TOOLS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import backup_tui
    return backup_tui


def human(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def ago(ts) -> str:
    try:
        d = int(time.time()) - int(ts)
    except (TypeError, ValueError):
        return "never"
    for n, u in ((86400, "d"), (3600, "h"), (60, "min")):
        if d >= n:
            return f"{d // n} {u} ago"
    return "just now"


def duration(s) -> str:
    try:
        s = int(float(s))
    except (TypeError, ValueError):
        return "?"
    return f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def write_conf(folders) -> None:
    b = B()
    try:
        comments = [ln for ln in b.CONF.read_text().splitlines() if ln.lstrip().startswith("#")]
    except OSError:
        comments = []
    b.CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = b.CONF.with_suffix(".conf.tmp")
    tmp.write_text("\n".join(comments + [f.line() for f in folders]) + "\n")
    os.replace(tmp, b.CONF)


def folder_row(f) -> dict:
    b = B()
    st, pr = b.kv(b.STATE / f"{f.id}.status"), b.kv(b.STATE / f"{f.id}.progress")
    state, msg = st.get("state", ""), st.get("msg", "")
    if state == "uploading" and pr.get("pct"):
        right = f"{int(pr.get('pct', 0))}%"
        sub = f"{human(pr.get('done'))} of {human(pr.get('total'))} · {human(pr.get('speed'))}/s · {duration(pr.get('eta'))}"
        if pr.get("current"):
            sub += f" · {pr['current']}"
    elif state in b.ACTIVE:
        right, sub = "working", msg
    elif state == "queued":
        right, sub = "queued", ""
    elif state == "error":
        right, sub = "✗ error", msg
    elif state == "cancelled":
        right, sub = "■ cancelled", msg
    else:
        right = "✓ up to date" if st.get("last_ok") else "never uploaded"
        sub = msg
    last = (f"last {time.strftime('%d/%m/%Y %H:%M', time.localtime(int(st['last_ok'])))} ({ago(st['last_ok'])}) · "
            f"{st.get('last_files', '?')} files · {human(st.get('last_bytes'))}") if st.get("last_ok") else "never uploaded"
    detail = f"{f.local} → {f.remote} · excludes {f.excl or '—'} · {last}"
    run_ = b.running()
    acts = [] if run_ else [L.action(f"one:{f.id}", "Upload"), L.action(f"edit:{f.id}", "Edit"), L.action(f"rm:{f.id}", "Remove", True)]
    acts.append(L.action(f"log:{f.id}", "Log"))
    return L.item(f"one:{f.id}", f.name, sub=(sub + " · " if sub else "") + detail, right=right, glyph=f.icon or b.DEFAULT_ICON,
                  on=state == "ok" or (not state and bool(st.get("last_ok"))), actions=acts)


def activity(folders) -> list:
    b = B()
    try:
        lines = (b.STATE / "runner.log").read_text().splitlines()[-12:]
    except OSError:
        lines = []
    names = {f.id: f.name for f in folders}
    out = []
    for i, ln in enumerate(reversed(lines)):
        m = re.match(r"\d{4}-(\d\d)-(\d\d) (\d\d:\d\d):\d\d (.*)", ln)
        if not m:
            continue
        msg = re.sub(r"\((\d+) bytes\)", lambda x: f"({human(x.group(1))})", m.group(4))
        m2 = re.match(r"\[([^\]]+)\] (.*)", msg)
        who = names.get(m2.group(1), m2.group(1)) if m2 else ""
        out.append(L.info(f"a{i}", f"{m.group(2)}/{m.group(1)} {m.group(3)}" + (f" · {who}" if who else ""), m2.group(2) if m2 else msg))
    return out


def get() -> dict:
    b = B()
    folders = b.read_conf()
    run_ = b.running()
    if run_:
        n = len(folders)
        cur = next(((i, f) for i, f in enumerate(folders, 1) if b.kv(b.STATE / f"{f.id}.status").get("state") in b.ACTIVE), None)
        head = f"Uploading {cur[1].name} ({cur[0]}/{n})" if cur else "Preparing"
        ctl = [L.button("cancel", head, "What's already uploaded stays in Proton Drive", "Cancel", danger=True)]
    else:
        lasts = [b.kv(b.STATE / f"{f.id}.status").get("last_ok") for f in folders]
        head = ("No folders yet" if not folders else "Some folders are not backed up" if not all(lasts)
                else f"All backed up · oldest {ago(min(int(x) for x in lasts))}")
        ctl = [L.button("all", "Update all", head, "Upload")] if folders else [L.info("none", "Backup", head)]
    ctl += [L.button("add", "Add folder", "Local folder → Proton Drive", "Add"),
            L.button("login", "Sign in to Proton Drive", "proton-drive auth login, in a terminal", "Sign in")]
    act = activity(folders)
    return L.page("Backup", "Proton Drive · incremental", [
        L.group("Backup", ctl), L.group("Folders", [folder_row(f) for f in folders] or [L.info("nof", "No folders", "Add one")]),
        L.group("Activity", act or [L.info("noact", "No activity yet", "")])], refresh=2 if run_ else 5)


def set_value(key, value):
    return L.fail("Unknown setting")


def fields(v: dict) -> list:
    b = B()
    return [{"name": "local", "label": "LOCAL FOLDER", "text": v.get("local", str(Path.home()) + "/")},
            {"name": "name", "label": "NAME (empty = folder name)", "text": v.get("name", "")},
            {"name": "icon", "label": "ICON (NERD FONT)", "text": v.get("icon", b.DEFAULT_ICON)},
            {"name": "remote", "label": f"PROTON DRIVE FOLDER (empty = {b.REMOTE_BASE}/<name>)", "text": v.get("remote", "")},
            {"name": "excl", "label": "EXCLUDE (space separated; with / it's relative to the root)", "text": v.get("excl", b.DEFAULT_EXCL)}]


def check(v: dict, me: str = "") -> str:
    b = B()
    if not v["name"]:
        return "The name is missing"
    if "|" in "".join(v.values()):
        return "| can't be used"
    if any(f.name == v["name"] and f.id != me for f in b.read_conf()):
        return f"There is already a folder called {v['name']}"
    if not Path(v["local"]).expanduser().is_dir():
        return f"Folder not found: {v['local']}"
    if not v["remote"].startswith("/my-files/"):
        return "The remote folder must start with /my-files/"
    return ""


def normalize(v: dict) -> dict:
    b = B()
    v = {k: str(v.get(k, "")).strip() for k in ("local", "name", "icon", "remote", "excl")}
    v["local"] = str(Path(v["local"]).expanduser().resolve()) if v["local"] else ""
    if not v["name"]:
        v["name"] = Path(v["local"]).name if v["local"] else ""
    if not v["remote"]:
        v["remote"] = f"{b.REMOTE_BASE}/{v['name']}"
    v["icon"] = v["icon"] or b.DEFAULT_ICON
    return v


def act(key: str, text=None):
    b = B()
    op, _, arg = key.partition(":")
    folders = b.read_conf()
    f = next((x for x in folders if x.id == arg), None)
    if op == "log" and f:
        try:
            last = (b.STATE / f"{f.id}.last.log").read_text() or "(empty)"
        except OSError:
            last = "(none yet)"
        try:
            hist = "\n".join([ln for ln in (b.STATE / "runner.log").read_text().splitlines() if f"[{f.id}]" in ln][-200:]) or "(empty)"
        except OSError:
            hist = "(empty)"
        return L.text_view(f"Log · {f.name}", f"Last upload\n\n{last}\n\nHistory\n\n{hist}")
    if op == "login":
        L.detach(["kitty", "--class", "proton-login", "--title", "Proton Drive", "-e", "sh", "-c",
                  "echo 'Sign in to Proton Drive'; echo; proton-drive auth login; printf '\\nPress enter to close…'; read _"])
        return L.ok()
    if op == "cancel":
        if not b.running():
            return L.ok()
        if not L.yes(text):
            return L.confirm("cancel", "Cancel upload", "What's already uploaded stays in Proton Drive; next time\n"
                             "it resumes from what was missing. Cancel?", ok_label="Cancel upload")
        b.backup("cancel")
        return L.ok("Upload cancelled")
    if b.running() and op in ("one", "all", "edit", "rm", "add", "addf", "editf"):
        return L.fail("An upload is in progress: wait for it to finish or cancel it")
    if op == "all":
        b.backup("start")
        return L.ok("Uploading all folders")
    if op == "one" and f:
        b.backup("start", f.id)
        return L.ok(f"Uploading {f.name}")
    if op == "add":
        if text is None:
            return L.form("add", "Add folder", fields({}), hint="Name and destination are filled in automatically if left empty.")
        v = normalize(L.parse_form(text))
        if err := check(v):
            return L.form("add", "Add folder", fields(v), error=err)
        fid, base, n = b.slug(v["name"]), b.slug(v["name"]), 2
        while any(x.id == fid for x in folders):
            fid, n = f"{base}-{n}", n + 1
        write_conf(folders + [b.Folder(fid, v["icon"], v["name"], v["local"], v["remote"], v["excl"])])
        return L.ok(f"{v['name']} added: Upload sends it")
    if op == "edit" and f:
        cur = {"local": f.local, "name": f.name, "icon": f.icon, "remote": f.remote, "excl": f.excl}
        if text is None:
            return L.form(key, f"Edit {f.name}", fields(cur))
        v = normalize(L.parse_form(text))
        if err := check(v, f.id):
            return L.form(key, f"Edit {f.name}", fields(v), error=err)
        for g in folders:
            if g.id == f.id:
                g.icon, g.name, g.local, g.remote, g.excl = v["icon"], v["name"], v["local"], v["remote"], v["excl"]
        write_conf(folders)
        if v["local"] != f.local or v["remote"] != f.remote:
            for ext in ("files", "dirs"):
                (b.STATE / f"{f.id}.{ext}").unlink(missing_ok=True)
            return L.ok("Saved: the next upload checks the whole folder")
        return L.ok("Saved")
    if op == "rm" and f:
        if not L.yes(text):
            return L.confirm(key, "Remove folder", f"{f.name} will no longer be backed up.\n"
                             f"The copy in Proton Drive ({f.remote}) is left untouched. Remove?", ok_label="Remove")
        write_conf([g for g in folders if g.id != f.id])
        for ext in ("files", "dirs", "status", "progress", "last.log", "failed"):
            (b.STATE / f"{f.id}.{ext}").unlink(missing_ok=True)
        return L.ok(f"{f.name} removed")
    return L.ok()
