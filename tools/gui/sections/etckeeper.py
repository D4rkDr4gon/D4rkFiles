"""etckeeper (GUI): paridad con EtckeeperView — /etc versionado con git.

/etc/.git es solo de root (tiene /etc/shadow): se lee con el helper root de la GUI SOLO si ya
está autorizado en esta sesión (nada de polling que pida huella); si no, se muestra la última
foto guardada (la misma caché que la TUI) y "Unlock" autoriza una vez. Instalar, inicializar,
timer, commit, ver diffs y descartar cambios, como en la TUI."""

from __future__ import annotations

import time

from . import _lib as L

UI: dict = {}


def T():
    return L.tui_module("etckeeper")


def git(*args: str) -> tuple[bool, str]:
    return L.root_run([["git", "-C", "/etc", *args]], timeout=30)


def snapshot() -> dict:
    ok, branch = git("rev-parse", "--abbrev-ref", "HEAD")
    changes = []
    for line in git("status", "--porcelain")[1].splitlines():
        if len(line) > 3:
            changes.append({"code": line[:2].strip() or "M", "path": line[3:].split(" -> ")[-1].strip('"')})
    log = []
    for line in git("log", "-n", "200", "--format=%h%x09%at%x09%s")[1].splitlines():
        h, _, rest = line.partition("\t")
        at, _, msg = rest.partition("\t")
        if h and at.isdigit():
            log.append({"hash": h, "time": int(at), "msg": msg})
    return {"time": time.time(), "branch": branch.strip(), "changes": changes, "log": log}


def get() -> dict:
    t = T()
    from dtui import ago
    inst, init = t.installed(), t.initialized()
    live = inst and init and L.root_alive()
    data = snapshot() if live else t.load_cache()
    if live:
        t.save_cache(data)
    rows = []
    if not inst:
        rows.append(L.button("install", "etckeeper", "Not installed · tracks /etc with git, commits before/after every pacman run",
                             "Install"))
    else:
        rows.append(L.button("init", "Repository", "git repo at /etc/.git (root only: it holds /etc/shadow)" if init
                             else "Not initialized · create /etc/.git and make the first commit", "Ready" if init else "Initialize"))
        rows.append(L.info("hook", "pacman hook", "● active" if t.hook_present() else "○ missing (reinstall etckeeper)"))
        rows.append(L.toggle("timer", "Daily auto-commit", "Commits what changed by hand once a day", t.timer_on()))
        if init:
            n = len(data.get("changes", []))
            rows.append(L.info("changes", "Uncommitted changes", (f"{n}" if data else "unknown")
                               + ("" if live else (f" · as of {ago(data['time'])}" if data.get("time") else ""))))
            rows.append(L.button("unlock", "Live view", "Reading /etc/.git needs root" + (" · unlocked" if live else " · showing the last snapshot"),
                                 "Refresh" if live else "Unlock"))
            rows.append(L.button("commit", "Commit", "Commit everything that changed in /etc", "Commit"))
    groups = [L.group("etckeeper", rows)]
    if init:
        codes = t.CODES
        chg = [L.item(f"chg:{c['code']}:{c['path']}", c["path"], sub=codes.get(c["code"], c["code"]), glyph="󰈙",
                      actions=[L.action(f"chg:{c['code']}:{c['path']}", "Diff"), L.action(f"discard:{c['code']}:{c['path']}", "Discard", True)])
               for c in data.get("changes", [])]
        log = [L.item(f"c:{c['hash']}", c["msg"], sub=f"{c['hash']} · {ago(c['time'])}", glyph="󰜘") for c in data.get("log", [])]
        groups += [L.group("Changes", chg or [L.info("none", "Nothing changed", "✓")]), L.group("History", log)]
    return L.page("etckeeper", "/etc versioned with git · never pushed anywhere (it holds password hashes)", groups)


def set_value(key, value):
    if key == "timer":
        return L.root_ok([["systemctl", "enable" if value else "disable", "--now", T().TIMER]], f"Daily auto-commit {'on' if value else 'off'}")
    return L.fail("Unknown setting")


def act(key: str, text=None):
    t = T()
    op, _, arg = key.partition(":")
    if op == "install":
        return L.root_ok([["pacman", "-S", "--needed", "--noconfirm", "etckeeper"]], "etckeeper installed", timeout=600)
    if op == "init":
        if t.initialized():
            return L.ok()
        if not L.yes(text):
            return L.confirm("init", "Initialize /etc", "Create /etc/.git (root only) and make the first commit?\n"
                             "Wi-Fi passwords, pacman keys and regenerated certificates are left out.\n"
                             "Nothing is uploaded anywhere. Files in /etc are not modified.", danger=False, ok_label="Initialize")
        ok, out = L.root_run([["etckeeper", "init"]])
        if not ok:
            return L.fail(out[-160:])
        _ok, cur = L.root_run([["cat", "/etc/.gitignore"]])
        ignore = (cur.rstrip("\n") + "\n\n# Locales: secretos y salida regenerada\n" + "\n".join(t.IGNORE) + "\n")
        steps = [["install", "-m644", L.root_file(ignore), "/etc/.gitignore"],
                 ["git", "-C", "/etc", "rm", "-r", "--cached", "-q", "--ignore-unmatch", *t.IGNORE]]
        ok, out = L.root_run(steps)
        if not ok:
            return L.fail(out[-160:])
        for k, v in (("user.name", "etckeeper"), ("user.email", "etckeeper@localhost")):
            if not git("config", k)[1].strip():
                git("config", k, v)
        return L.root_ok([["etckeeper", "commit", "Initial commit"]], "/etc is now tracked")
    if op == "unlock":
        ok, out = L.root_run([["true"]])
        return L.ok("Unlocked") if ok else L.fail(out or "Authorization cancelled")
    if op == "commit":
        if text is None:
            return L.form("commit", "Commit /etc", [{"name": "msg", "label": "MESSAGE", "text": ""}], ok_label="Commit")
        msg = L.parse_form(text).get("msg", "").strip()
        if not msg:
            return L.form("commit", "Commit /etc", [{"name": "msg", "label": "MESSAGE", "text": ""}], error="Write a message", ok_label="Commit")
        return L.root_ok([["etckeeper", "commit", msg]], "Committed")
    if op == "chg":
        code, _, path = arg.partition(":")
        if code == "??":
            return L.text_view(f"/etc/{path}", f"{path} is new and not tracked yet.\nIt will be added by the next commit.")
        ok, out = git("diff", "HEAD", "--", path)
        return L.text_view(f"/etc/{path}", out or "(no diff)")
    if op == "c":
        ok, out = git("show", "--stat", "--patch", "--format=%h  %an  %ad%n%n%s%n%b", "--date=format:%Y-%m-%d %H:%M", arg)
        return L.text_view(f"commit {arg}", out or "(empty)")
    if op == "discard":
        code, _, path = arg.partition(":")
        if code == "??":
            return L.fail("Untracked file: nothing to restore (delete it by hand if you want)")
        if not L.yes(text):
            return L.confirm(key, "Discard change", f"Overwrite /etc/{path} with the last committed version?\n"
                             "The change you made by hand is lost (unless it is in an older commit).", ok_label="Discard")
        return L.root_ok([["git", "-C", "/etc", "checkout", "HEAD", "--", path]], f"Restored /etc/{path}")
    return L.ok()
