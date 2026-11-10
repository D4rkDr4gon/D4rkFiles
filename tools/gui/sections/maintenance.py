"""Maintenance (GUI): paridad con MaintenanceView (settings/sections/maintenance.py).

Health (limpieza de la caché de pacman, descargas a medias, earlyoom), Config files (.pacnew /
.pacsave: diff, fusionar, conservar el actual, usar el nuevo) y Failed units (logs, reiniciar,
enmascarar, olvidar). Datos de la TUI; root por el helper de la GUI. Fusionar es interactivo:
abre nvim -d con sudo en una kitty y, al cerrarla, pregunta si borrar el .pacnew."""

from __future__ import annotations

import shutil
import subprocess

from . import _lib as L

UI: dict = {}
STATE: dict = {"files": [], "units": [], "health": {}}


def T():
    return L.tui_module("maintenance")


def tilde(p) -> str:
    return L.settings_common().tilde(p)


def get() -> dict:
    t = T()
    from dtui import ago, human
    size, count, leftovers = t.cache_info()
    h = {"paccache": t.unit_enabled("paccache.timer"), "cache": (size, count), "leftovers": leftovers,
         "earlyoom": shutil.which("earlyoom") is not None, "earlyoom_on": t.unit_active("earlyoom"),
         "oom_kill": t.last_oom_kill(), "pacman_busy": t.PACMAN_LOCK.exists()}
    files, units = t.config_files(), t.failed_units()
    STATE.update(health=h, files=files, units=units)
    rows = [L.toggle("paccache", "Package cache cleanup", f"Weekly, keeps the last 3 versions · now {human(size)} in {count} files",
                     h["paccache"])]
    if leftovers:
        rows.append(L.button("leftovers", "Leftover downloads", f"{len(leftovers)} half-finished pacman downloads (download-*)",
                             "Delete", danger=True))
    if not h["earlyoom"]:
        rows.append(L.button("earlyoom", "Out-of-memory guard", "Not installed · kills the biggest app when memory runs out instead "
                             "of freezing the session", "Install"))
    else:
        k = h["oom_kill"]
        rows.append(L.toggle("earlyoom", "Out-of-memory guard", (f"Last kill: {k[1]} {ago(k[0])}" if k else "Nothing killed yet")
                             + " · avoids Hyprland, waybar, kitty · prefers browsers/electron", h["earlyoom_on"]))
    if h["pacman_busy"]:
        rows.append(L.info("busy", "pacman is running", "wait before cleaning"))
    frows = []
    for d in files:
        chg = f"+{d['plus']} −{d['minus']}" if d["readable"] and d["target_exists"] else \
            ("no file" if not d["target_exists"] else "root only")
        frows.append(L.item(f"diff:{d['path']}", tilde(d["target"]), sub=f".{d['kind']} · {chg} · {ago(d['mtime']) if d['mtime'] else '—'}",
                            glyph="󰈙", actions=[L.action(f"diff:{d['path']}", "Diff"), L.action(f"merge:{d['path']}", "Merge"),
                                               L.action(f"keep:{d['path']}", "Keep current"),
                                               L.action(f"usenew:{d['path']}", "Use new", True)]))
    urows = [L.item(f"logs:{u['scope']}:{u['unit']}", u["unit"], sub=f"{u['scope']} · {u['desc']}", glyph="󰒏",
                    actions=[L.action(f"logs:{u['scope']}:{u['unit']}", "Logs"), L.action(f"restart:{u['scope']}:{u['unit']}", "Restart"),
                             L.action(f"forget:{u['scope']}:{u['unit']}", "Forget"),
                             L.action(f"mask:{u['scope']}:{u['unit']}", "Mask", True)]) for u in units]
    return L.page("Maintenance", "Changes ask for your fingerprint once per GUI session", [
        L.group("Health", rows),
        L.group(f"Config files to review · {len(files)}" if files else "Config files", frows or [L.info("none", "Nothing to review", "✓")]),
        L.group(f"Failed units · {len(units)}" if units else "Failed units", urows or [L.info("none", "All good", "✓")])])


def set_value(key, value):
    if key in ("paccache", "earlyoom"):
        unit = "paccache.timer" if key == "paccache" else "earlyoom"
        verb = "enable" if value else "disable"
        return L.root_ok([["systemctl", verb, "--now", unit]], {"paccache": "Package cache cleanup", "earlyoom": "Out-of-memory guard"}[key]
                         + (" on" if value else " off"))
    return L.fail("Unknown setting")


def ctl(u: dict, *args: str) -> tuple[bool, str]:
    if u["scope"] == "user":
        r = L.run(["systemctl", "--user", *args])
        return r.returncode == 0, r.stderr.strip()
    return L.root_run([["systemctl", *args]])


def act(key: str, text=None):
    t = T()
    op, _, arg = key.partition(":")
    h = STATE["health"]
    if op == "leftovers":
        if h.get("pacman_busy"):
            return L.fail("pacman is running: try again when it finishes")
        dirs = [str(t.PKG_CACHE / n) for n in h.get("leftovers", [])]
        if not dirs:
            return L.ok()
        if not L.yes(text):
            return L.confirm(key, "Delete leftover downloads", f"Delete {len(dirs)} half-finished pacman download folders?", ok_label="Delete")
        return L.root_ok([["rm", "-rf", "--", *dirs]], f"Deleted {len(dirs)} leftover folders")
    if op == "earlyoom":
        conf = L.root_file("# Generado por Settings → Maintenance (dotfiles). Ver `man earlyoom`.\n"
                           f'EARLYOOM_ARGS="{t.EARLYOOM_ARGS}"\n')
        return L.root_ok([["pacman", "-S", "--needed", "--noconfirm", "earlyoom"], ["install", "-m644", conf, str(t.EARLYOOM_CONF)],
                          ["systemctl", "enable", "--now", "earlyoom"]], "earlyoom installed and watching", timeout=900)

    d = next((x for x in STATE["files"] if x["path"] == arg), None)
    if op == "diff" and d:
        if not d["target_exists"]:
            body = (f"{d['target']} no longer exists: the package was removed and pacman kept your copy.\n\n"
                    "Keep current deletes the .pacsave · Use new puts it back in place")
        elif not d["readable"]:
            ok, a = L.root_run([["cat", d["target"]]])
            ok2, b = L.root_run([["cat", d["path"]]]) if ok else (False, "")
            if not (ok and ok2):
                return L.fail("Only root can read one of the files")
            import difflib
            body = "\n".join(difflib.unified_diff(a.splitlines(), b.splitlines(), "current", "new", lineterm="")) or "(identical)"
        else:
            body = L.run(["diff", "-u", d["target"], d["path"]]).stdout or "(identical: Keep current deletes the copy)"
        if d["target_exists"]:
            body = (f"--- current  {d['target']}\n+++ new      {d['path']}\n\n"
                    "Lines with - are yours (or the old default) and would be lost with Use new;\n"
                    "lines with + are what the package brings now. Merge does it by hand.\n\n" + body)
        return L.text_view(f"Diff · {tilde(d['target'])}", body)
    if op == "merge" and d:
        if not d["target_exists"]:
            return L.fail("Nothing to merge with: Use new puts the .pacsave back")
        if L.yes(text):
            return L.root_ok([["rm", "-f", d["path"]]], f"Merged {tilde(d['target'])}")
        editor = "nvim" if shutil.which("nvim") else "vim"
        subprocess.run(["kitty", "--title", f"Merge · {tilde(d['target'])}", "-e", "sh", "-c",
                        f"echo 'Left = current file, right = {d['kind']}. Copy what you want into the LEFT one (do / dp), "
                        f"save with :wqa'; sleep 1; sudo {editor} -d \"$0\" \"$1\"", d["target"], d["path"]])
        return L.confirm(key, "Merged?", f"Delete {tilde(d['path'])} now that it is merged?", danger=False, ok_label="Delete it")
    if op == "keep" and d:
        if not L.yes(text):
            return L.confirm(key, "Keep the current file", f"Delete {tilde(d['path'])} and keep {tilde(d['target'])} as it is?",
                             ok_label="Keep current")
        return L.root_ok([["rm", "-f", d["path"]]], f"Kept the current {tilde(d['target'])}")
    if op == "usenew" and d:
        if not d["target_exists"]:
            cmds, msg = [["mv", d["path"], d["target"]]], f"Put {tilde(d['path'])} back as {tilde(d['target'])}?"
        else:
            cmds = [["cp", "-a", d["target"], d["target"] + ".pacold"], ["mv", d["path"], d["target"]]]
            msg = (f"Replace {tilde(d['target'])} with the new version?\nYour current one is kept as {tilde(d['target'])}.pacold. "
                   "Lines you added are lost: check the diff first.")
        if not L.yes(text):
            return L.confirm(key, "Use the new file", msg, ok_label="Use new")
        return L.root_ok(cmds, f"Using the new {tilde(d['target'])}")

    scope, _, unit = arg.partition(":")
    u = next((x for x in STATE["units"] if x["scope"] == scope and x["unit"] == unit), None)
    if not u:
        return L.ok()
    extra = ["--user"] if scope == "user" else []
    if op == "logs":
        r = L.run(["journalctl", *extra, "-b", "-u", unit, "-n", "120", "--no-pager"])
        st = L.run(["systemctl", *extra, "status", unit, "--no-pager", "-n", "0"])
        return L.text_view(f"Logs · {unit}", (st.stdout + "\n" + (r.stdout or r.stderr)).strip() or "(empty)")
    if op == "restart":
        ok, out = ctl(u, "restart", unit)
        return L.ok(f"Restarted {unit}") if ok else L.fail(out[:160] or "systemctl failed")
    if op == "forget":
        ok, out = ctl(u, "reset-failed", unit)
        return L.ok(f"{unit}: failure cleared (it comes back if it fails again)") if ok else L.fail(out[:160] or "systemctl failed")
    if op == "mask":
        tpl = t.template_of(unit)
        target = tpl or unit
        if not L.yes(text):
            return L.confirm(key, "Mask unit", f"Mask {target}? It will never start again (systemctl unmask {target} undoes it)."
                             + (f"\nIt is a template: every {tpl.split('@')[0]}@… instance is masked." if tpl else ""), ok_label="Mask")
        ok, out = ctl(u, "mask", target)
        if ok:
            ok, out = ctl(u, "reset-failed", *[x["unit"] for x in STATE["units"] if x["scope"] == scope
                                               and (t.template_of(x["unit"]) or x["unit"]) == target])
        return L.ok(f"Masked {target}") if ok else L.fail(out[:160] or "systemctl failed")
    return L.ok()
