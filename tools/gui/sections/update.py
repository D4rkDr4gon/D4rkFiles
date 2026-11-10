"""Update (GUI): paridad con UpdateView (settings/sections/update.py) y los modos de
scripts/dotfiles-update.sh, sin terminal.

Status: pendientes, última actualización, último snapshot, kernel, CVEs y firmware, con la
acción de cada fila. Actions: los modos del script (all, check, pacman, aur, snapshot,
rollback, clean, orphans, audit, firmware) hechos como pasos de un trabajo en segundo plano con
log en vivo (L.job_start): lo de root va por el helper de la GUI (una huella por sesión) y yay
usa rootshim.py como sudo, así tampoco pide la huella. Pending y Installed (estilo pacseek:
búsqueda, solo explícitos, orden por tamaño, detalles, desinstalar con la lista exacta)."""

from __future__ import annotations

import re
import shutil
import time
from datetime import datetime

from . import _lib as L

UI: dict = {}
STATE: dict = {"explicit": False, "size": False, "inst": [], "inst_t": 0.0, "sec": None, "sec_t": 0.0, "snaps": None}
TABS = [("status", "Status"), ("pending", "Pending"), ("installed", "Installed")]
KEEP_SNAPSHOTS, KEEP_PKG_VERSIONS, JOURNAL_MAX, SNAP_TAG = 5, 2, "500M", "dotfiles-update"


def T():
    return L.tui_module("update")


def ago(t):
    from dtui import ago as a
    return a(t)


# ════════════════════════════════════════════════════════════════
#  páginas
# ════════════════════════════════════════════════════════════════

def security(force: bool = False, wait: bool = False):
    """arch-audit y fwupd salen a la red (segundos): en un hilo; mientras, "checking…"."""
    import threading
    if force or STATE["sec"] is None or time.time() - STATE["sec_t"] > 900:
        STATE["sec_t"] = time.time()

        def job():
            t = T()
            STATE["sec"] = (t.audit_status(), t.firmware_status())
        if wait:
            job()
        else:
            threading.Thread(target=job, daemon=True).start()
    return STATE["sec"] or (("checking…", ""), ("checking…", ""))


def page_status() -> list:
    t = T()
    data = t.pending()
    up, snap, kern = t.last_upgrade(), t.last_snapshot(), t.kernel_status()
    (aud, _), (fw, _) = security()
    n = len(data.get("pkgs", []))
    rows = [L.button("st:all", "Pending", (data.get("error") or (f"{n} packages" if n else "✓ up to date"))
                     + f" · checked {ago(data.get('time', 0))}", "Update all" if n else "Run"),
            L.button("st:check", "Last full update", f"{ago(up)} · {datetime.fromtimestamp(up):%Y-%m-%d %H:%M}" if up
                     else "never (no -Syu in the log)", "Check"),
            L.button("st:snapshot", "Last snapshot", (f"{ago(snap[1])} · {snap[0]}" if snap[1] else snap[0]) if snap else "none yet",
                     "Create"),
            L.info("kernel", "Kernel", kern[0]),
            L.button("st:audit", "Security", aud, "Audit"),
            L.button("st:firmware", "Firmware", fw, "Check")]
    groups = L.job_group("update") + [L.group("System status", rows)]
    for title, acts in t.ACTIONS:
        groups.append(L.group(title, [L.button(f"mode:{k}", name, desc, "Run", danger=k in ("rollback", "orphans"))
                                      for k, _icon, name, desc in acts]))
    groups.append(L.group("Refresh", [L.button("refresh", "Check again", "Pending packages, CVEs and firmware", "Refresh")]))
    if STATE["snaps"] is not None:
        groups.insert(1, L.group("Rollback · Timeshift snapshots", [
            L.item(f"snap:{name}", name, sub=desc, glyph="󰄄",
                   actions=[L.action(f"restore:{name}", "Restore", True), L.action(f"delsnap:{name}", "Delete", True)])
            for name, desc in STATE["snaps"]] + [L.button("snaps:close", "Done", "", "Close")]))
    return groups


def page_pending() -> list:
    t = T()
    data = t.pending()
    pkgs = sorted(data.get("pkgs", []), key=lambda p: (not t.IMPORTANT.match(p["name"]), p["src"] != "repo", p["name"]))
    q = (UI.get("search") or "").lower()
    rows = [L.item(f"pend:{p['name']}", p["name"], sub=f"{p['old']} → {p['new']}", right=p["src"],
                   on=bool(t.IMPORTANT.match(p["name"])), glyph="󰏔") for p in pkgs if not q or q in p["name"].lower()]
    head = [L.info("n", "Pending", f"{len(pkgs)} · checked {ago(data.get('time', 0))}" + (f" · {data['error']}" if data.get("error") else "")),
            L.button("mode:all", "Full update", "Snapshot → pacman → AUR → clean", "Update"),
            L.button("refresh", "Check again", "", "Check")]
    return L.job_group("update") + [L.group("Pending", head), L.group("Packages", rows or [L.info("none", "Nothing to update", "✓")])]


def page_installed() -> list:
    if not STATE["inst"] or time.time() - STATE["inst_t"] > 120:
        STATE["inst"], STATE["inst_t"] = T().installed_pkgs(), time.time()
    inst = STATE["inst"]
    q = (UI.get("search") or "").strip().lower()
    rows = [p for p in inst if (not STATE["explicit"] or p["explicit"]) and (not q or q in p["name"].lower() or q in p["desc"].lower())]
    rows.sort(key=(lambda p: -p["size"]) if STATE["size"] else (lambda p: p["name"]))
    total = sum(p["size"] for p in rows) / 1024 ** 3
    head = [L.info("n", "Installed", f"{len(rows)}{'' if len(rows) == len(inst) else f' of {len(inst)}'} · {total:.1f} GiB"),
            L.toggle("explicit", "Installed by hand only", "Hide dependencies", STATE["explicit"]),
            L.toggle("bysize", "Sort by size", "Biggest first", STATE["size"])]
    items = [L.item(f"pkg:{p['name']}", p["name"], sub=f"{p['version']} · {p['desc'][:90]}",
                    right=p["size_h"].replace(" ", "").replace("iB", "") + (" · AUR" if p["src"] == "AUR" else ""),
                    on=p["explicit"], glyph="󰏗",
                    actions=[L.action(f"pkg:{p['name']}", "Details"), L.action(f"rm:{p['name']}", "Uninstall", True)])
             for p in rows[:400]]
    if len(rows) > 400:
        items.append(L.info("more", f"… {len(rows) - 400} more", "search to narrow it down"))
    return L.job_group("update") + [L.group("Packages", head), L.group("List", items)]


def get() -> dict:
    tab = UI.get("tab") or "status"
    try:
        groups = {"status": page_status, "pending": page_pending, "installed": page_installed}[tab]()
    except Exception as e:  # noqa: BLE001
        groups = [L.group("Error", [L.info("err", "Couldn't load", str(e)[:140])])]
    p = L.page("Update", "Root steps ask for your fingerprint once per GUI session", groups,
               refresh=2 if L.job_running("update") else 0)
    p.update(tabs=[{"key": k, "label": lbl} for k, lbl in TABS], tab=tab,
             search={"installed": "Search installed packages…", "pending": "Filter pending…"}.get(tab, ""))
    return p


def set_value(key, value):
    if key == "explicit":
        STATE["explicit"] = bool(value)
    elif key == "bysize":
        STATE["size"] = bool(value)
    return L.ok()


# ════════════════════════════════════════════════════════════════
#  modos del script
# ════════════════════════════════════════════════════════════════

def prune_snapshots() -> str:
    ok, out = L.root_run([["timeshift", "--list"]])
    names = sorted(re.findall(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", "\n".join(ln for ln in out.splitlines() if SNAP_TAG in ln)))
    old = names[:-KEEP_SNAPSHOTS] if len(names) > KEEP_SNAPSHOTS else []
    msgs = []
    for name in old:
        ok, o = L.root_run([["timeshift", "--delete", "--snapshot", name, "--scripted"]])
        msgs.append(f"{'Deleted' if ok else 'Could not delete'} old snapshot {name}")
    return "\n".join(msgs) or f"Keeping the last {KEEP_SNAPSHOTS} pre-update snapshots"


def snapshot_steps() -> list:
    if not shutil.which("timeshift"):
        return [(lambda: (_ for _ in ()).throw(RuntimeError("timeshift is not installed")), "Snapshot")]
    comment = f"{SNAP_TAG} pre-update {datetime.now():%Y-%m-%d %H:%M}"
    return [("root", ["timeshift", "--create", "--comments", comment, "--tags", "D", "--scripted"], "Snapshot (Timeshift)"),
            (prune_snapshots, "Old snapshots")]


def clean_steps() -> list:
    steps = []
    if shutil.which("paccache"):
        steps += [("root", ["paccache", f"-rk{KEEP_PKG_VERSIONS}"], "Old package versions"),
                  ("root", ["paccache", "-ruk0"], "Uninstalled packages")]
    if shutil.which("yay"):
        steps.append(("user", ["yay", "-Sc", "--noconfirm"], "yay cache"))
    steps.append(("root", ["journalctl", f"--vacuum-size={JOURNAL_MAX}"], "Journal"))
    steps.append((lambda: ("Orphans: " + " ".join(L.run(["pacman", "-Qdtq"]).stdout.split())) if L.run(["pacman", "-Qdtq"]).stdout.strip()
                  else "No orphan packages", "Orphans"))
    return steps


def post_checks() -> str:
    out = []
    pac = L.tui_module("maintenance").config_files()
    out.append(("Config files to review (Maintenance):\n" + "\n".join(d["path"] for d in pac)) if pac else "No .pacnew/.pacsave pending")
    import platform
    from pathlib import Path
    if not Path(f"/usr/lib/modules/{platform.release()}").is_dir():
        out.append("Kernel updated: reboot to use it")
    aud = T().audit_status()[0]
    out.append(f"Security: {aud}")
    return "\n".join(out)


def after(force_sec: bool):
    def done(_ok):
        T().pending(force=True)
        if force_sec:
            security(force=True)
        STATE["inst_t"] = 0
    return done


def run_mode(mode: str, text=None):
    t = T()
    if L.job_running("update"):
        return L.fail("An update job is already running")
    if mode == "check":
        data = t.pending(force=True)
        body = "\n".join(f"{p['name']:<32} {p['old']} → {p['new']}  [{p['src']}]" for p in data["pkgs"]) or "Nothing pending"
        return L.text_view("Pending updates", (data.get("error") + "\n\n" if data.get("error") else "") + body)
    if mode == "audit":
        if not shutil.which("arch-audit"):
            return L.fail("arch-audit is not installed")
        allv, fix = L.run(["arch-audit"], timeout=60), L.run(["arch-audit", "-u"], timeout=60)
        security(force=True)
        return L.text_view("Security audit (arch-audit)", f"Fixed by updating ({len(fix.stdout.splitlines())}):\n{fix.stdout or '—'}\n\n"
                           f"All known ({len(allv.stdout.splitlines())}):\n{allv.stdout or '✓ none'}")
    if mode == "rollback":
        if not shutil.which("timeshift"):
            return L.fail("timeshift is not installed")
        ok, out = L.root_run([["timeshift", "--list"]])
        if not ok:
            return L.fail("Could not list snapshots")
        snaps = []
        for ln in out.splitlines():
            m = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\s+(.*)$", ln)
            if m:
                snaps.append((m.group(1), m.group(2).strip()))
        STATE["snaps"] = list(reversed(snaps))
        UI["tab"] = "status"
        return L.ok(f"{len(snaps)} snapshots")
    if mode == "orphans":
        orphans = L.run(["pacman", "-Qdtq"]).stdout.split()
        if not orphans:
            return L.ok("No orphan packages")
        if not L.yes(text):
            return L.confirm("mode:orphans", "Remove orphans", "Packages nobody needs:\n  " + "\n  ".join(orphans[:30])
                             + (f"\n  … +{len(orphans) - 30}" if len(orphans) > 30 else ""), ok_label="Remove")
        return L.job_start("update", "Orphans", [("root", ["pacman", "-Rns", "--noconfirm", *orphans], "Remove orphans")], after(False))
    if mode == "firmware":
        if not shutil.which("fwupdmgr"):
            return L.fail("fwupd is not installed")
        if L.yes(text):
            return L.job_start("update", "Firmware", [("root", ["fwupdmgr", "update", "-y", "--no-reboot-check"], "Install firmware")],
                               after(True))
        ok, _out = L.root_run([["fwupdmgr", "refresh", "--force"]], timeout=180)
        r = L.run(["fwupdmgr", "get-updates"], timeout=60)
        security(force=True)
        if r.returncode != 0 or "No updates" in (r.stdout + r.stderr) or "no updates" in (r.stdout + r.stderr).lower():
            return L.text_view("Firmware", ("" if ok else "Could not download LVFS metadata\n\n") + (r.stdout or r.stderr or "No updates"))
        return L.confirm("mode:firmware", "Install firmware updates?", r.stdout[-1800:], danger=False, ok_label="Install")
    steps = {"pacman": [("root", ["pacman", "-Syu", "--noconfirm"], "Pacman (-Syu)")],
             "aur": [("aur", ["yay", "-Sua", "--noconfirm"], "AUR (yay -Sua)")] if shutil.which("yay") else [],
             "snapshot": snapshot_steps(), "clean": clean_steps()}.get(mode)
    if mode == "all":
        steps = (snapshot_steps() if shutil.which("timeshift") else []) + [("root", ["pacman", "-Syu", "--noconfirm"], "Pacman (-Syu)")] \
            + ([("aur", ["yay", "-Sua", "--noconfirm"], "AUR (yay -Sua)")] if shutil.which("yay") else []) + clean_steps() \
            + [(post_checks, "Review")]
        if not L.yes(text):
            n = len(t.pending().get("pkgs", []))
            return L.confirm("mode:all", "Full update", f"Snapshot → pacman → AUR → clean ({n} packages pending).\n"
                             "Runs in the background; the log shows here.", danger=False, ok_label="Update")
    if not steps:
        return L.fail("Nothing to run (missing tool?)")
    title = {"all": "Full update", "pacman": "Pacman", "aur": "AUR", "snapshot": "Snapshot", "clean": "Clean"}.get(mode, mode)
    return L.job_start("update", title, steps, after(mode in ("all", "pacman", "aur")))


def act(key: str, text=None):
    t = T()
    op, _, arg = key.partition(":")
    if op == "mode":
        return run_mode(arg, text)
    if op == "st":
        return run_mode(arg, text)
    if op == "refresh":
        t.pending(force=True)
        security(force=True)
        return L.ok("Checked")
    if op == "log":
        return L.text_view(L.JOBS.get(arg, {}).get("title", "Log"), L.job_text(arg) or "(empty)")
    if op == "snaps":
        STATE["snaps"] = None
        return L.ok()
    if op == "snap":
        return L.ok()
    if op == "restore":
        if not L.yes(text):
            return L.confirm(key, f"Restore {arg}?", "Timeshift restores the system to that snapshot and the machine REBOOTS.\n"
                             "Everything changed since then in the system (not in /home) is lost.", ok_label="Restore and reboot")
        return L.job_start("update", "Rollback", [("root", ["timeshift", "--restore", "--snapshot", arg, "--scripted", "--yes"],
                                                    f"Restore {arg}")])
    if op == "delsnap":
        if not L.yes(text):
            return L.confirm(key, f"Delete snapshot {arg}?", "It can't be undone.", ok_label="Delete")
        ok, out = L.root_run([["timeshift", "--delete", "--snapshot", arg, "--scripted"]])
        if ok and STATE["snaps"]:
            STATE["snaps"] = [s for s in STATE["snaps"] if s[0] != arg]
        return L.ok(f"Deleted {arg}") if ok else L.fail(out[-160:])
    if op == "pend":
        return L.ok()
    p = next((x for x in STATE["inst"] if x["name"] == arg), None)
    if op == "pkg" and p:
        deps = " ".join(re.split(r"[<>=]", d)[0] for d in p["depends"]) or "—"
        body = (f"{p['name']} {p['version']}\n{p['desc']}\n{p['url'] if p['url'] != 'None' else ''}\n\n"
                f"{p['size_h']} · {'explicitly installed' if p['explicit'] else 'installed as a dependency'} · {p['src']} · {p['date']}\n\n"
                f"Depends on:  {deps}\nRequired by: {' '.join(p['required']) or '—'}")
        return L.text_view(p["name"], body)
    if op == "rm" and p:
        r = L.run(["pacman", "-Rs", "--print", "--print-format", "%n %v", p["name"]])
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().splitlines()
            return L.fail(msg[-1] if msg else f"{p['name']} can't be removed")
        targets = r.stdout.strip().splitlines()
        if not L.yes(text):
            warn = f"\n⚠ {p['name']} is a core package: removing it can leave the system unbootable.\n" if t.CRITICAL.match(p["name"]) else ""
            shown = "\n".join(f"  {x}" for x in targets[:15]) + (f"\n  … +{len(targets) - 15} more" if len(targets) > 15 else "")
            return L.confirm(key, f"Uninstall {p['name']}", f"pacman -Rns will remove {len(targets)} package"
                             f"{'s' if len(targets) != 1 else ''}:\n{shown}\n{warn}", ok_label="Uninstall")
        ok, out = L.root_run([["pacman", "-Rns", "--noconfirm", p["name"]]], timeout=900)
        STATE["inst_t"] = 0
        t.pending(force=False)
        return L.ok(f"Removed {p['name']}" + (f" (+{len(targets) - 1})" if len(targets) > 1 else "")) if ok else \
            L.fail(out.splitlines()[-1][:160] if out else f"Could not remove {p['name']}")
    return L.ok()
