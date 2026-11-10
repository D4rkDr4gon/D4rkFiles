"""Repositories (GUI): paridad con ReposView — clones de GitHub (estado, fetch, fetch de todos,
pull --ff-only, commit con filtro de secretos, push con confirmación, ramas, rama nueva, stash,
stash pop, diff, log, PRs/issues, abrir en GitHub, terminal), repos de la cuenta sin clonar
(clonar) y crear uno nuevo en GitHub desde una carpeta. Misma lógica (git y gh) que la TUI.

Al tocar un repo se abre su ficha arriba con todas las acciones."""

from __future__ import annotations

import re
import shutil
import threading
import time
from pathlib import Path

from . import _lib as L

UI: dict = {}
STATE: dict = {"repos": [], "remote": [], "me": "", "t": 0.0, "scanning": False, "open": "", "busy": ""}


def T():
    return L.tui_module("repos")


def scan(wait: bool = False):
    if STATE["scanning"]:
        return

    def job():
        STATE["scanning"] = True
        try:
            t = T()
            repos = t.scan_repos()
            for r in repos:
                r.update(t.repo_state(r["path"]))
            me = t.gh_user()
            STATE.update(repos=repos, remote=t.gh_repos() if me else [], me=me, t=time.time())
        finally:
            STATE["scanning"] = False
    if wait:
        job()
    else:
        threading.Thread(target=job, daemon=True).start()


def state_text(r: dict) -> str:
    parts = []
    if r["changes"]:
        parts.append(f"{r['changes']} uncommitted")
    if r["ahead"]:
        parts.append(f"{r['ahead']} to push")
    if r["behind"]:
        parts.append(f"{r['behind']} to pull")
    if not r["upstream"]:
        parts.append("no upstream")
    return (" · ".join(parts) or "✓ clean") + f" ({r['branch']})"


def detail(path: Path) -> list:
    t = T()
    r = next((x for x in STATE["repos"] if x["path"] == path), None) or {"slug": path.name, **t.repo_state(path), "path": path}
    st = t.git(path, "status", "--short", "--branch").stdout.splitlines()
    log = t.git(path, "log", "--oneline", "-5").stdout.splitlines()
    stash = t.git(path, "stash", "list").stdout.splitlines()
    rows = [L.info("state", "State", state_text(r)), L.info("path", "Path", str(path).replace(str(Path.home()), "~"))]
    rows += [L.info(f"st{i}", "Changed" if i == 0 else "", ln) for i, ln in enumerate(st[1:9])]
    if len(st) > 9:
        rows.append(L.info("stmore", "", f"… and {len(st) - 9} more"))
    rows += [L.info(f"log{i}", "Recent" if i == 0 else "", ln) for i, ln in enumerate(log)]
    if stash:
        rows.append(L.info("stash", "Stashes", str(len(stash))))
    p = str(path)
    acts = [L.button(f"commit:{p}", "Commit", "Message and what to stage", "Commit"),
            L.button(f"pull:{p}", "Pull", "Fast-forward only", "Pull"),
            L.button(f"push:{p}", "Push", "Asks to confirm; never forced", "Push"),
            L.button(f"fetch:{p}", "Fetch", "All remotes, prune", "Fetch"),
            L.button(f"branch:{p}", "Branches", "Switch branch", "Pick"),
            L.button(f"newbranch:{p}", "New branch", "", "Create"),
            L.button(f"stash:{p}", "Stash", "Including untracked", "Stash"),
            L.button(f"pop:{p}", "Stash pop", "", "Pop"),
            L.button(f"diff:{p}", "Diff", "Against HEAD, with untracked files", "Show"),
            L.button(f"log:{p}", "Log", "Graph of the last 60 commits", "Show"),
            L.button(f"prs:{p}", "PRs & issues", "gh", "Show"),
            L.button(f"web:{p}", "Open on GitHub", "", "Open"),
            L.button(f"term:{p}", "Terminal here", "kitty", "Open"),
            L.button("close", "Close", "", "Close")]
    return [L.group(f"{r['slug']}", rows), L.group("Actions", acts)]


def get() -> dict:
    if not STATE["t"] and not STATE["scanning"]:
        scan(wait=True)
    elif time.time() - STATE["t"] > 300:
        scan()
    me = STATE["me"].lower()
    q = (UI.get("search") or "").lower()
    repos = [r for r in STATE["repos"] if not q or q in r["slug"].lower()]
    mine = sorted((r for r in repos if r["slug"].split("/")[0].lower() == me), key=lambda r: r["slug"].lower())
    others = sorted((r for r in repos if r not in mine), key=lambda r: r["slug"].lower())
    cloned = {r["slug"].lower() for r in STATE["repos"]}
    missing = sorted((g for g in STATE["remote"] if g["nameWithOwner"].lower() not in cloned and (not q or q in g["nameWithOwner"].lower())),
                     key=lambda g: g["nameWithOwner"].lower())

    def local(r, short):
        p = str(r["path"])
        return L.item(f"open:{p}", r["slug"].split("/", 1)[1] if short else r["slug"], sub=state_text(r) + " · " + p.replace(str(Path.home()), "~"),
                      on=not (r["changes"] or r["ahead"] or r["behind"]), glyph="",
                      actions=[L.action(f"commit:{p}", "Commit"), L.action(f"pull:{p}", "Pull"), L.action(f"push:{p}", "Push")])

    groups = []
    if STATE["open"]:
        try:
            groups += detail(Path(STATE["open"]))
        except Exception as e:  # noqa: BLE001
            STATE["open"] = ""
            groups.append(L.group("Error", [L.info("err", "Couldn't read the repository", str(e)[:120])]))
    sub = ("gh is not logged in: only local clones (run `gh auth login`)" if not STATE["me"] else
           f"{len(mine)} mine · {len(missing)} not cloned · {len(others)} third-party · ahead/behind as of the last fetch")
    groups.append(L.group("Repositories", [
        L.info("sum", "Summary", ("scanning… · " if STATE["scanning"] else "") + (STATE["busy"] + " · " if STATE["busy"] else "") + sub),
        L.button("fetchall", "Fetch all", "Updates ahead/behind of every clone", "Fetch"),
        L.button("rescan", "Rescan", "Look for clones again", "Rescan"),
        L.button("clone", "Clone", "Pick one of your repos not cloned yet", "Clone"),
        L.button("create", "New on GitHub", "Create a repository from a local folder", "Create")]))
    if mine:
        groups.append(L.group(f"Mine · {STATE['me']}", [local(r, True) for r in mine]))
    if missing:
        groups.append(L.group("On GitHub, not cloned", [
            L.item(f"remote:{g['nameWithOwner']}", g["nameWithOwner"].split("/", 1)[1],
                   sub=("private · " if g.get("isPrivate") else "") + f"pushed {g.get('pushedAt', '?')[:10]} · {(g.get('description') or '')[:60]}",
                   glyph="", actions=[L.action(f"cloneone:{g['nameWithOwner']}", "Clone"), L.action(f"webs:{g['nameWithOwner']}", "Open"),
                                       L.action(f"prss:{g['nameWithOwner']}", "PRs")]) for g in missing]))
    if others:
        groups.append(L.group("Third-party clones", [local(r, False) for r in others]))
    p = L.page("Repositories", "git and gh with your session · nothing is forced", groups, refresh=3 if STATE["scanning"] or STATE["busy"] else 0)
    p["search"] = "Filter repositories…"
    return p


def set_value(key, value):
    return L.fail("Unknown setting")


def refresh_one(path: Path):
    st = T().repo_state(path)
    for r in STATE["repos"]:
        if r["path"] == path:
            r.update(st)


def op(path: Path, args: list[str], ok_msg: str, timeout: float = 120):
    r = T().git(path, *args, timeout=timeout)
    refresh_one(path)
    if r.returncode == 0:
        return L.ok(ok_msg)
    return L.text_view(f"git {args[0]} failed · {path.name}", (r.stderr + r.stdout).strip() or "(no output)")


def slug_of(val: str) -> str:
    return next((r["slug"] for r in STATE["repos"] if str(r["path"]) == val), "")


def commit_form(path: Path, staged: bool, shown: str, vals=None, error=""):
    v = vals or {"message": "", "stage": "staged" if staged else "all"}
    return L.form(f"commitsave:{path}", f"Commit · {path.name}", [
        {"name": "message", "label": "MESSAGE", "text": v.get("message", "")},
        {"name": "stage", "label": "STAGE", "text": v.get("stage", "all"),
         "choices": [["all changes (git add -A)", "all"], ["only what is already staged", "staged"]]}], error=error, hint=shown, ok_label="Commit")


def act(key: str, text=None):
    t = T()
    o, _, arg = key.partition(":")
    v = L.parse_form(text) if text and text.startswith("{") else {}
    if o == "rescan":
        scan()
        return L.ok("Scanning…")
    if o == "close":
        STATE["open"] = ""
        return L.ok()
    if o == "open":
        STATE["open"] = "" if STATE["open"] == arg else arg
        return L.ok()
    if o == "fetchall":
        def job():
            STATE["busy"] = f"fetching {len(STATE['repos'])} repositories"
            for r in STATE["repos"]:
                t.git(r["path"], "fetch", "--all", "--prune", "--quiet", timeout=60)
                r.update(t.repo_state(r["path"]))
            STATE["busy"] = ""
        threading.Thread(target=job, daemon=True).start()
        return L.ok("Fetching all repositories…")
    if o == "remote":
        return L.ok()
    if o in ("webs", "web"):
        slug = arg if o == "webs" else slug_of(arg)
        if slug:
            L.detach(["xdg-open", f"https://github.com/{slug}"])
        return L.ok("Opened in the browser")
    if o in ("prss", "prs"):
        slug = arg if o == "prss" else slug_of(arg)
        if not slug or not shutil.which("gh"):
            return L.fail("Select a repository (gh needed)")
        prs = L.run(["gh", "pr", "list", "-R", slug, "--limit", "20"], timeout=30)
        issues = L.run(["gh", "issue", "list", "-R", slug, "--limit", "20"], timeout=30)
        return L.text_view(f"{slug} · PRs & issues", "Pull requests\n" + (prs.stdout or "(none)\n") + "\nIssues\n" + (issues.stdout or "(none)\n"))
    if o in ("clone", "cloneone"):
        cloned = {r["slug"].lower() for r in STATE["repos"]}
        missing = [g for g in STATE["remote"] if g["nameWithOwner"].lower() not in cloned]
        if o == "clone":
            if not missing:
                return L.ok("Everything on GitHub is already cloned" if STATE["me"] else "gh is not logged in")
            if text is None:
                return L.form("clone", "Clone from GitHub", [{"name": "slug", "label": "REPOSITORY", "text": missing[0]["nameWithOwner"],
                                                              "choices": [g["nameWithOwner"] for g in missing]}], ok_label="Next")
            arg = v.get("slug", "")
        return L.form(f"clonedo:{arg}", f"Clone · {arg}", [{"name": "dest", "label": "INTO", "text": str(t.clone_base() / arg.split("/", 1)[-1])}],
                      ok_label="Clone")
    if o == "clonedo":
        dest = Path(v.get("dest", "")).expanduser()
        if dest.exists():
            return L.form(key, f"Clone · {arg}", [{"name": "dest", "label": "INTO", "text": v.get("dest", "")}], error=f"{dest} already exists",
                          ok_label="Clone")
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = L.run(["gh", "repo", "clone", arg, str(dest)], timeout=600, env=t.GIT_ENV)
        if r.returncode != 0:
            return L.text_view(f"Clone failed · {arg}", (r.stderr + r.stdout).strip() or "(no output)")
        scan()
        outside = not any(str(dest).startswith(str(root)) for root in t.repo_roots())
        return L.ok(f"Cloned into {dest}" + (" (outside the scanned roots: it won't be listed)" if outside else ""))
    if o == "create":
        if not shutil.which("gh") or not STATE["me"]:
            return L.fail("gh is not logged in (gh auth login)")
        fields = lambda x: [{"name": "dir", "label": "LOCAL FOLDER", "text": x.get("dir", str(t.clone_base()))},  # noqa: E731
                            {"name": "name", "label": "NAME", "text": x.get("name", "")},
                            {"name": "visibility", "label": "VISIBILITY", "text": x.get("visibility", "private"), "choices": ["private", "public"]},
                            {"name": "description", "label": "DESCRIPTION", "text": x.get("description", "")}]
        if text is None:
            return L.form("create", "New repository on GitHub", fields({}), ok_label="Next")
        d, name = Path(v.get("dir", "")).expanduser(), v.get("name", "").strip()
        err = ("That folder does not exist" if not d.is_dir() else "Name: letters, numbers, . _ -" if not re.fullmatch(r"[\w.-]+", name)
               else "You already have a repository with that name"
               if any(g["nameWithOwner"].lower() == f"{STATE['me']}/{name}".lower() for g in STATE["remote"])
               else "That folder already has an origin remote" if (d / ".git").exists() and t.git(d, "remote", "get-url", "origin").returncode == 0
               else "")
        if err:
            return L.form("create", "New repository on GitHub", fields(v), error=err, ok_label="Next")
        STATE["pending_create"] = v
        return L.confirm("createdo", "Create on GitHub", f"Create the {v['visibility']} repository {STATE['me']}/{name} from {d}?\n"
                         "It is created empty: commit and push afterwards.", danger=False, ok_label="Create")
    if o == "createdo":
        v = STATE.pop("pending_create", None)
        if not v or not L.yes(text):
            return L.ok()
        d, name = Path(v["dir"]).expanduser(), v["name"].strip()
        if not (d / ".git").exists():
            t.git(d, "init", "-b", "main")
        cmd = ["gh", "repo", "create", name, f"--{v['visibility']}", "--source", str(d), "--remote", "origin"]
        if v.get("description", "").strip():
            cmd += ["--description", v["description"].strip()]
        r = L.run(cmd, timeout=60, env=t.GIT_ENV)
        if r.returncode != 0:
            return L.text_view(f"Create failed · {name}", (r.stderr + r.stdout).strip() or "(no output)")
        scan()
        return L.ok(f"Created {STATE['me']}/{name}")

    path = Path(arg)
    if o == "fetch":
        return op(path, ["fetch", "--all", "--prune"], f"Fetched {path.name}")
    if o == "pull":
        return op(path, ["pull", "--ff-only"], f"Pulled {path.name}")
    if o == "push":
        r = next((x for x in STATE["repos"] if x["path"] == path), None) or t.repo_state(path)
        if r["upstream"] and not r["ahead"]:
            return L.ok("Nothing to push")
        args = ["push"] if r["upstream"] else ["push", "-u", "origin", r["branch"]]
        if not L.yes(text):
            what = f"{r['ahead']} commit(s)" if r["upstream"] else f"the new branch {r['branch']}"
            return L.confirm(key, f"Push {path.name}", f"Push {what} of {r['branch']} to origin?", danger=False, ok_label="Push")
        return op(path, args, f"Pushed {path.name}")
    if o == "commit":
        status = t.git(path, "status", "--short").stdout.splitlines()
        if not status:
            return L.ok("Nothing to commit")
        staged = any(ln[0] not in " ?" for ln in status)
        shown = "\n".join(status[:6]) + (f"\n… and {len(status) - 6} more" if len(status) > 6 else "")
        return commit_form(path, staged, shown)
    if o == "commitsave":
        status = t.git(path, "status", "--short").stdout.splitlines()
        staged = any(ln[0] not in " ?" for ln in status)
        shown = "\n".join(status[:6])
        msg = v.get("message", "").strip()
        if not msg:
            return commit_form(path, staged, shown, v, "The commit message is missing")
        if v.get("stage") == "staged" and not staged:
            return commit_form(path, staged, shown, v, "Nothing is staged: choose “all changes”")
        if v.get("stage") == "all" and (bad := t.risky_files(path)):
            return commit_form(path, staged, shown, v, "Looks like secrets, not staged: " + ", ".join(bad[:3]) + " (add to .gitignore or stage by hand)")
        if v.get("stage") == "all":
            r = t.git(path, "add", "-A")
            if r.returncode != 0:
                return L.text_view("git add failed", (r.stderr + r.stdout).strip())
        return op(path, ["commit", "-m", msg], f"Committed in {path.name}")
    if o == "branch":
        cur = t.git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        local = t.git(path, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split()
        remote = [b.removeprefix("origin/") for b in t.git(path, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").stdout.split()
                  if b not in ("origin", "origin/HEAD")]
        choices = [[("● " if b == cur else "") + b, b] for b in local] + [[f"{b} (origin only)", b] for b in remote if b not in local]
        return L.form(f"branchdo:{path}", f"Branches · {path.name}", [{"name": "b", "label": "BRANCH", "text": cur, "choices": choices}],
                      ok_label="Switch")
    if o == "branchdo":
        b = v.get("b", "")
        cur = t.git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        return op(path, ["checkout", b], f"On {b}") if b and b != cur else L.ok()
    if o == "newbranch":
        return L.form(f"newbranchdo:{path}", f"New branch · {path.name}", [{"name": "name", "label": "NAME", "text": ""}], ok_label="Create")
    if o == "newbranchdo":
        name = v.get("name", "").strip()
        if not re.fullmatch(r"[\w./-]+", name) or name.startswith("-"):
            return L.form(key, f"New branch · {path.name}", [{"name": "name", "label": "NAME", "text": name}], error="Use letters, numbers, . _ - /",
                          ok_label="Create")
        return op(path, ["checkout", "-b", name], f"Created {name}")
    if o == "stash":
        if not t.git(path, "status", "--short").stdout.strip():
            return L.ok("Nothing to stash")
        return op(path, ["stash", "push", "-u", "-m", "settings"], "Stashed (Stash pop brings it back)")
    if o == "pop":
        return op(path, ["stash", "pop"], "Stash restored")
    if o == "diff":
        stat = t.git(path, "diff", "HEAD", "--stat").stdout
        diff = t.git(path, "diff", "HEAD").stdout
        untracked = t.git(path, "ls-files", "--others", "--exclude-standard").stdout
        body = (stat or "(no tracked changes)\n") + "\n" + diff[:30000] + ("\n… (diff cut at 30000 characters)" if len(diff) > 30000 else "")
        return L.text_view(f"{path.name} · diff", body + (f"\n\nUntracked:\n{untracked}" if untracked else ""))
    if o == "log":
        return L.text_view(f"{path.name} · log", t.git(path, "log", "--oneline", "--graph", "--decorate", "-60").stdout or "(no commits)")
    if o == "term":
        L.detach(["kitty", "--directory", str(path)])
        return L.ok()
    return L.ok()
