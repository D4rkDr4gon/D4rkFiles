"""Repositories — gestión de repos de GitHub: los clones locales (estado, fetch, pull,
commit, push, ramas, stash, diff, log), los repos de tu cuenta que todavía no clonaste
(clonar) y crear uno nuevo en GitHub desde una carpeta.

Usa git y gh (con tu sesión: `gh auth status`). Nada se hace a escondidas:
- commit: pide el mensaje, y con "all changes" se niega a agregar archivos que parecen secretos;
- push y crear en GitHub piden confirmación; nunca se fuerza un push;
- pull es `--ff-only` (si hay que mergear o rebasear, se hace a mano);
- git no puede quedarse esperando una contraseña (GIT_TERMINAL_PROMPT=0): si falla, se ve el error.

Busca clones en $HOME y EXTRA_REPO_DIRS de user.conf (hasta 5 niveles) con remoto en GitHub.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from common import detach, run, user_conf
from dtui import THEME, ConfirmModal, DView, Field, FormModal, Panel, PickModal, Table, TextModal, css
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static

# Qué saltear para que el escaneo sea instantáneo
REPO_SKIP = ("node_modules", ".cache", "SteamLibrary", "VMs", ".local", ".cargo", ".rustup", "go")
GITHUB_RE = re.compile(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$")
# Archivos que no se agregan con "all changes": probablemente contengan secretos
SECRET_RE = re.compile(r"(^|/)(\.env(\..*)?|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|.*\.(pem|key|p12|pfx|kdbx)"
                       r"|credentials(\..*)?|\.netrc|.*secret.*)$", re.I)
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true", "LC_ALL": "C"}


def repo_roots() -> list[Path]:
    """Dónde buscar clones: $HOME + EXTRA_REPO_DIRS de user.conf (separadas por ':')."""
    extra = user_conf().get("EXTRA_REPO_DIRS", "")
    return [Path.home()] + [Path(os.path.expandvars(d)).expanduser() for d in extra.split(":") if d]


def clone_base() -> Path:
    """Carpeta donde se sugiere clonar: la primera de EXTRA_REPO_DIRS que exista, si no el home."""
    return next((r for r in repo_roots()[1:] if r.is_dir()), Path.home())


def slug_of(url: str) -> Optional[str]:
    m = GITHUB_RE.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def git(path: Path | str, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return run(["git", "-C", str(path), *args], timeout=timeout, env=GIT_ENV)


def scan_repos() -> list[dict]:
    """Clones locales con remoto en GitHub: [{path, slug (owner/name), url}]."""
    args = ["find", *map(str, (r for r in repo_roots() if r.exists())), "-maxdepth", "5", "("]
    for i, name in enumerate(REPO_SKIP):
        args += (["-o"] if i else []) + ["-name", name]
    args += [")", "-prune", "-o", "-name", ".git", "-print", "-prune"]
    try:
        found = subprocess.run(args, capture_output=True, text=True, timeout=20).stdout.split("\n")
    except (OSError, subprocess.TimeoutExpired):
        found = []
    out = []
    for g in filter(None, found):
        path = Path(g).parent
        url = git(path, "remote", "get-url", "origin").stdout.strip()
        if slug := slug_of(url):
            out.append({"path": path, "slug": slug, "url": url})
    return out


def repo_state(path: Path) -> dict:
    """Rama, cambios sin commitear, ahead/behind (según el último fetch) y si tiene upstream."""
    head = git(path, "status", "--porcelain=v1", "--branch").stdout.splitlines()
    first = head[0][3:] if head else ""
    return {"branch": first.split("...")[0].split(" ")[0] or "?", "changes": max(0, len(head) - 1),
            "ahead": int(m.group(1)) if (m := re.search(r"ahead (\d+)", first)) else 0,
            "behind": int(m.group(1)) if (m := re.search(r"behind (\d+)", first)) else 0,
            "upstream": "..." in first}


def gh_user() -> str:
    return run(["gh", "api", "user", "-q", ".login"], timeout=15).stdout.strip() if shutil.which("gh") else ""


def gh_repos() -> list[dict]:
    r = run(["gh", "repo", "list", "--limit", "300", "--json",
             "nameWithOwner,url,isPrivate,description,pushedAt"], timeout=30)
    try:
        return json.loads(r.stdout or "[]")
    except ValueError:
        return []


def risky_files(path: Path) -> list[str]:
    """Cambios (incluye sin seguimiento) que parecen secretos."""
    out = git(path, "status", "--porcelain=v1", "-uall").stdout.splitlines()
    return [l[3:].strip('"') for l in out if SECRET_RE.search(l[3:].strip('"'))]


class ReposView(DView):
    FOCUS = "#repos"
    DEFAULT_CSS = css("""
    #repos-panel { height: 1fr; }
    #repo-info-panel { height: 14; }
    #repo-info { height: auto; }
    """)
    BINDINGS = [
        Binding("r", "rescan", "rescan"),
        Binding("f", "fetch", "fetch"),
        Binding("F", "fetch_all", "fetch all"),
        Binding("p", "pull", "pull"),
        Binding("P", "push", "push"),
        Binding("m", "commit", "commit"),
        Binding("c", "clone", "clone"),
        Binding("b", "branch", "branches"),
        Binding("B", "new_branch", "new branch"),
        Binding("d", "diff", "diff"),
        Binding("l", "log", "log"),
        Binding("z", "stash", "stash"),
        Binding("Z", "stash_pop", "stash pop"),
        Binding("v", "prs", "PRs/issues"),
        Binding("o", "web", "open on GitHub"),
        Binding("t", "terminal", "terminal here"),
        Binding("n", "create", "new on GitHub"),
    ]

    def compose(self) -> ComposeResult:
        yield Panel(Table(id="repos"), title="  Repositories", id="repos-panel")
        yield Panel(Static(id="repo-info"), title="Selected", id="repo-info-panel")

    def on_mount(self) -> None:
        t = self.query_one("#repos", Table)
        t.add_column("Repository", key="name", width=34)
        t.add_column("State", key="state", width=44)
        t.add_column("Path", key="path", width=40)
        self.repos: list[dict] = []
        self.remote: list[dict] = []
        self.me = ""
        self.busy = ""
        self.action_rescan()

    # ── datos ──

    def action_rescan(self) -> None:
        self.query_one("#repos-panel").border_subtitle = " scanning… "
        self.scan()

    @work(thread=True, exclusive=True, group="scan")
    def scan(self) -> None:
        repos = scan_repos()
        for r in repos:
            r.update(repo_state(r["path"]))
        me = gh_user()
        remote = gh_repos() if me else []
        self.app.call_from_thread(self.show, repos, remote, me)

    def show(self, repos: list[dict], remote: list[dict], me: str) -> None:
        self.repos, self.remote, self.me = repos, remote, me
        self.render_rows()

    def render_rows(self) -> None:
        ok, warn, muted = THEME["status_ok"], THEME["status_warn"], THEME["muted"]
        err = THEME["status_error"]
        home = str(Path.home())
        me = self.me.lower()
        mine = sorted((r for r in self.repos if r["slug"].split("/")[0].lower() == me),
                      key=lambda r: r["slug"].lower())
        others = sorted((r for r in self.repos if r not in mine), key=lambda r: r["slug"].lower())
        cloned = {r["slug"].lower() for r in self.repos}
        missing = sorted((g for g in self.remote if g["nameWithOwner"].lower() not in cloned),
                         key=lambda g: g["nameWithOwner"].lower())
        rows: list[tuple[str, list]] = []

        def header(label: str) -> None:
            rows.append((f"hdr:{label}", [Text(label, style=f"bold {THEME['primary']}"), "", ""]))

        def local(r: dict) -> None:
            st = Text()
            if r["changes"]:
                st.append(f"{r['changes']} uncommitted", style=warn)
            if r["ahead"]:
                st.append(("" if not st else " · ") + f"{r['ahead']} to push", style=warn)
            if r["behind"]:
                st.append(("" if not st else " · ") + f"{r['behind']} to pull", style=err)
            if not r["upstream"]:
                st.append(("" if not st else " · ") + "no upstream", style=warn)
            if not st:
                st.append("✓ clean", style=ok)
            st.append(f"  ({r['branch']})", style=muted)
            name = r["slug"].split("/", 1)[1] if r in mine else r["slug"]
            rows.append((f"local:{r['path']}", [Text(f"  {name}"), st,
                                                Text(str(r["path"]).replace(home, "~"), style=muted)]))

        if mine:
            header(f"Mine · {self.me}")
            for r in mine:
                local(r)
        if missing:
            header("On GitHub, not cloned")
            for g in missing:
                rows.append((f"remote:{g['nameWithOwner']}", [
                    Text(f"  {g['nameWithOwner'].split('/', 1)[1]}", style=muted),
                    Text(("private · " if g.get("isPrivate") else "") + "not cloned · c clones it", style=muted),
                    Text((g.get("description") or "")[:40], style=muted)]))
        if others:
            header("Third-party clones")
            for r in others:
                local(r)
        t = self.query_one("#repos", Table)
        t.set_rows(rows)
        if not self.me:
            sub = " gh is not logged in: only local clones (run `gh auth login`) "
        else:
            sub = (f" {len(mine)} mine · {len(missing)} not cloned · {len(others)} third-party · "
                   f"ahead/behind as of the last fetch ")
        self.query_one("#repos-panel").border_subtitle = f" {self.busy}… " if self.busy else sub
        self.show_info()

    # ── selección ──

    def current(self) -> tuple[str, str]:
        """('local', ruta) | ('remote', owner/name) | ('', '')."""
        key = self.query_one("#repos", Table).selected_key() or ""
        kind, _, val = key.partition(":")
        return (kind, val) if kind in ("local", "remote") else ("", "")

    def local_path(self, warn: bool = True) -> Optional[Path]:
        kind, val = self.current()
        if kind == "local":
            return Path(val)
        if warn:
            self.app.notify_err("Select a cloned repository first" if kind == "" else "Not cloned yet: press c")
        return None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "repos":
            self.show_info()
            self.update_hints()

    def show_info(self) -> None:
        kind, val = self.current()
        info = self.query_one("#repo-info", Static)
        if kind == "remote":
            g = next((g for g in self.remote if g["nameWithOwner"] == val), {})
            t = Text(val + "\n", style=f"bold {THEME['primary']}")
            t.append(f"{'private' if g.get('isPrivate') else 'public'} · pushed {g.get('pushedAt', '?')[:10]}\n",
                     style=THEME["muted"])
            t.append(g.get("description") or "(no description)")
            info.update(t)
        elif kind == "local":
            info.update(Text("…", style=THEME["muted"]))
            self.load_info(Path(val))
        else:
            info.update("")

    @work(thread=True, exclusive=True, group="info")
    def load_info(self, path: Path) -> None:
        st = git(path, "status", "--short", "--branch").stdout.splitlines()
        log = git(path, "log", "--oneline", "-5").stdout.splitlines()
        stash = git(path, "stash", "list").stdout.splitlines()
        t = Text(st[0] if st else "", style=f"bold {THEME['primary']}")
        t.append("\n")
        for line in st[1:9]:
            t.append(line + "\n", style=THEME["status_warn"])
        if len(st) > 9:
            t.append(f"… and {len(st) - 9} more\n", style=THEME["muted"])
        t.append("\n" if len(st) > 1 else "")
        for line in log:
            t.append(line + "\n", style=THEME["muted"])
        if stash:
            t.append(f"\n{len(stash)} stash(es)", style=THEME["status_warn"])
        self.app.call_from_thread(self.set_info, path, t)

    def set_info(self, path: Path, text: Text) -> None:
        if self.current() == ("local", str(path)):   # el cursor pudo haberse movido
            self.query_one("#repo-info", Static).update(text)

    def hints(self) -> list[tuple[str, str]]:
        kind, _ = self.current()
        if kind == "remote":
            return [("c", "clone"), ("o", "open"), ("n", "new"), ("r", "rescan"), ("q", "quit")]
        return [("m", "commit"), ("p", "pull"), ("P", "push"), ("f", "fetch"), ("b", "branches"),
                ("d", "diff"), ("l", "log"), ("c", "clone"), ("n", "new"), ("q", "quit")]

    # ── operaciones de git ──

    def run_op(self, path: Path, args: list[str], ok_msg: str, label: str, timeout: float = 120) -> None:
        self.busy = label
        self.query_one("#repos-panel").border_subtitle = f" {label}… "
        self.do_git(path, args, ok_msg, timeout)

    @work(thread=True, exclusive=True, group="op")
    def do_git(self, path: Path, args: list[str], ok_msg: str, timeout: float) -> None:
        r = git(path, *args, timeout=timeout)
        st = repo_state(path)
        self.app.call_from_thread(self.op_done, path, args, r, ok_msg, st)

    def op_done(self, path: Path, args: list[str], r: subprocess.CompletedProcess, ok_msg: str, st: dict) -> None:
        self.busy = ""
        for repo in self.repos:
            if repo["path"] == path:
                repo.update(st)
        self.render_rows()
        if r.returncode == 0:
            self.app.notify_ok(ok_msg)
        else:
            self.app.push_screen(TextModal(f"git {args[0]} failed · {path.name}",
                                           (r.stderr + r.stdout).strip() or "(no output)", end=False))

    def action_fetch(self) -> None:
        if path := self.local_path():
            self.run_op(path, ["fetch", "--all", "--prune"], f"Fetched {path.name}", f"fetching {path.name}")

    @work(thread=True, exclusive=True, group="op")
    def fetch_everything(self) -> None:
        for r in self.repos:
            git(r["path"], "fetch", "--all", "--prune", "--quiet", timeout=60)
            r.update(repo_state(r["path"]))
        self.app.call_from_thread(self.finish_fetch_all)

    def finish_fetch_all(self) -> None:
        self.busy = ""
        self.render_rows()
        self.app.notify_ok("Fetched all repositories")

    def action_fetch_all(self) -> None:
        if self.repos:
            self.busy = f"fetching {len(self.repos)} repositories"
            self.query_one("#repos-panel").border_subtitle = f" {self.busy}… "
            self.fetch_everything()

    def action_pull(self) -> None:
        if path := self.local_path():
            self.run_op(path, ["pull", "--ff-only"], f"Pulled {path.name}", f"pulling {path.name}")

    def action_push(self) -> None:
        path = self.local_path()
        if not path:
            return
        repo = next((r for r in self.repos if r["path"] == path), None) or repo_state(path)
        branch = repo["branch"]
        if repo["upstream"] and not repo["ahead"]:
            return self.app.notify_ok("Nothing to push")
        args = ["push"] if repo["upstream"] else ["push", "-u", "origin", branch]
        what = (f"{repo['ahead']} commit(s)" if repo["upstream"] else f"the new branch {branch}")

        def done(yes: bool) -> None:
            if yes:
                self.run_op(path, args, f"Pushed {path.name}", f"pushing {path.name}")

        self.app.push_screen(ConfirmModal(f"Push {path.name}", f"Push {what} of {branch} to origin?"), done)

    def action_commit(self) -> None:
        path = self.local_path()
        if not path:
            return
        status = git(path, "status", "--short").stdout.splitlines()
        if not status:
            return self.app.notify_ok("Nothing to commit")
        staged = [l for l in status if l[0] not in " ?"]
        shown = "\n".join(status[:6]) + (f"\n… and {len(status) - 6} more" if len(status) > 6 else "")

        def check(v: dict) -> Optional[str]:
            if not v["message"].strip():
                return "The commit message is missing"
            if v["stage"] == "staged" and not staged:
                return "Nothing is staged: choose “all changes”"
            if v["stage"] == "all" and (bad := risky_files(path)):
                return "Looks like secrets, not staged: " + ", ".join(bad[:3]) + " (add to .gitignore or stage by hand)"
            return None

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            self.busy = f"committing in {path.name}"
            self.query_one("#repos-panel").border_subtitle = f" {self.busy}… "
            self.do_commit(path, v["message"].strip(), v["stage"] == "all")

        self.app.push_screen(FormModal(
            f"Commit · {path.name}",
            [Field("message", "Message", placeholder="feat(scope): what changed"),
             Field("stage", "Stage", "all" if not staged else "staged",
                   choices=[("all changes (git add -A)", "all"), ("only what is already staged", "staged")])],
            hint=shown, validate=check), done)

    @work(thread=True, exclusive=True, group="op")
    def do_commit(self, path: Path, message: str, stage_all: bool) -> None:
        if stage_all:
            r = git(path, "add", "-A")
            if r.returncode != 0:
                return self.app.call_from_thread(self.op_done, path, ["add"], r, "", repo_state(path))
        r = git(path, "commit", "-m", message, timeout=120)
        self.app.call_from_thread(self.op_done, path, ["commit"], r, f"Committed in {path.name}", repo_state(path))

    def action_branch(self) -> None:
        path = self.local_path()
        if not path:
            return
        cur = git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        local = git(path, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout.split()
        remote = [b.removeprefix("origin/") for b in
                  git(path, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").stdout.split()
                  if b not in ("origin", "origin/HEAD")]
        rows = [(b, [("● " if b == cur else "  ") + b, "local"]) for b in local]
        rows += [(b, ["  " + b, "origin only"]) for b in remote if b not in local]

        def done(branch: Optional[str]) -> None:
            if branch and branch != cur:
                self.run_op(path, ["checkout", branch], f"On {branch}", f"switching to {branch}")

        self.app.push_screen(PickModal(f"Branches · {path.name}", ["Branch", ""], rows), done)

    def action_new_branch(self) -> None:
        path = self.local_path()
        if not path:
            return

        def check(v: dict) -> Optional[str]:
            name = v["name"].strip()
            if not re.fullmatch(r"[\w./-]+", name) or name.startswith("-"):
                return "Use letters, numbers, . _ - /"
            return None

        def done(v: Optional[dict]) -> None:
            if v:
                self.run_op(path, ["checkout", "-b", v["name"].strip()], f"Created {v['name'].strip()}",
                            "creating the branch")

        self.app.push_screen(FormModal(f"New branch · {path.name}", [Field("name", "Name")], validate=check), done)

    def action_stash(self) -> None:
        if path := self.local_path():
            if not git(path, "status", "--short").stdout.strip():
                return self.app.notify_ok("Nothing to stash")
            self.run_op(path, ["stash", "push", "-u", "-m", "settings"], "Stashed (Z brings it back)", "stashing")

    def action_stash_pop(self) -> None:
        if path := self.local_path():
            self.run_op(path, ["stash", "pop"], "Stash restored", "restoring the stash")

    def action_diff(self) -> None:
        if path := self.local_path():
            stat = git(path, "diff", "HEAD", "--stat").stdout
            diff = git(path, "diff", "HEAD").stdout
            untracked = git(path, "ls-files", "--others", "--exclude-standard").stdout
            text = (stat or "(no tracked changes)\n") + "\n" + diff[:30000]
            if len(diff) > 30000:
                text += "\n… (diff cut at 30000 characters)"
            if untracked:
                text += "\n\nUntracked:\n" + untracked
            self.app.push_screen(TextModal(f"{path.name} · diff", text, end=False))

    def action_log(self) -> None:
        if path := self.local_path():
            log = git(path, "log", "--oneline", "--graph", "--decorate", "-60").stdout
            self.app.push_screen(TextModal(f"{path.name} · log", log or "(no commits)", end=False))

    def action_prs(self) -> None:
        kind, val = self.current()
        slug = val if kind == "remote" else next((r["slug"] for r in self.repos if str(r["path"]) == val), "")
        if not slug or not shutil.which("gh"):
            return self.app.notify_err("Select a repository (gh needed)")
        self.load_prs(slug)

    @work(thread=True, exclusive=True, group="op")
    def load_prs(self, slug: str) -> None:
        prs = run(["gh", "pr", "list", "-R", slug, "--limit", "20"], timeout=30)
        issues = run(["gh", "issue", "list", "-R", slug, "--limit", "20"], timeout=30)
        text = "Pull requests\n" + (prs.stdout or "(none)\n") + "\nIssues\n" + (issues.stdout or "(none)\n")
        self.app.call_from_thread(self.app.push_screen, TextModal(f"{slug} · PRs & issues", text, end=False))

    def action_web(self) -> None:
        kind, val = self.current()
        slug = val if kind == "remote" else next((r["slug"] for r in self.repos if str(r["path"]) == val), "")
        if slug:
            detach(["xdg-open", f"https://github.com/{slug}"])
            self.app.notify_ok("Opened in the browser")

    def action_terminal(self) -> None:
        if path := self.local_path():
            detach(["kitty", "--directory", str(path)])

    # ── clonar y crear ──

    def action_clone(self) -> None:
        kind, val = self.current()
        cloned = {r["slug"].lower() for r in self.repos}
        missing = [g for g in self.remote if g["nameWithOwner"].lower() not in cloned]
        if not missing:
            return self.app.notify_ok("Everything on GitHub is already cloned" if self.me else "gh is not logged in")

        def ask(slug: str) -> None:
            name = slug.split("/", 1)[1]

            def check(v: dict) -> Optional[str]:
                dest = Path(v["dest"]).expanduser()
                return f"{dest} already exists" if dest.exists() else None

            def done(v: Optional[dict]) -> None:
                if not v:
                    return
                self.busy = f"cloning {name}"
                self.query_one("#repos-panel").border_subtitle = f" {self.busy}… "
                self.do_clone(slug, Path(v["dest"]).expanduser())

            self.app.push_screen(FormModal(f"Clone · {slug}", [
                Field("dest", "Into", str(clone_base() / name), paths=True)], validate=check), done)

        if kind == "remote":
            return ask(val)
        rows = [(g["nameWithOwner"], [g["nameWithOwner"], "private" if g.get("isPrivate") else "public",
                                      (g.get("description") or "")[:50]]) for g in missing]
        self.app.push_screen(PickModal("Clone from GitHub", ["Repository", "", ""], rows),
                             lambda slug: ask(slug) if slug else None)

    @work(thread=True, exclusive=True, group="op")
    def do_clone(self, slug: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = run(["gh", "repo", "clone", slug, str(dest)], timeout=600, env=GIT_ENV)
        self.app.call_from_thread(self.clone_done, slug, dest, r)

    def clone_done(self, slug: str, dest: Path, r: subprocess.CompletedProcess) -> None:
        self.busy = ""
        if r.returncode != 0:
            self.render_rows()
            return self.app.push_screen(TextModal(f"Clone failed · {slug}",
                                                  (r.stderr + r.stdout).strip() or "(no output)", end=False))
        self.app.notify_ok(f"Cloned into {dest}")
        if not any(str(dest).startswith(str(root)) for root in repo_roots()):
            self.app.notify_ok("That folder is outside the scanned roots: it will not be listed")
        self.action_rescan()

    def action_create(self) -> None:
        if not shutil.which("gh") or not self.me:
            return self.app.notify_err("gh is not logged in (gh auth login)")

        def check(v: dict) -> Optional[str]:
            d = Path(v["dir"]).expanduser()
            if not d.is_dir():
                return "That folder does not exist"
            if not re.fullmatch(r"[\w.-]+", v["name"].strip()):
                return "Name: letters, numbers, . _ -"
            if any(g["nameWithOwner"].lower() == f"{self.me}/{v['name'].strip()}".lower() for g in self.remote):
                return "You already have a repository with that name"
            if (d / ".git").exists() and git(d, "remote", "get-url", "origin").returncode == 0:
                return "That folder already has an origin remote"
            return None

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            d, name, vis = Path(v["dir"]).expanduser(), v["name"].strip(), v["visibility"]

            def confirmed(yes: bool) -> None:
                if yes:
                    self.busy = f"creating {name}"
                    self.query_one("#repos-panel").border_subtitle = f" {self.busy}… "
                    self.do_create(d, name, vis, v["description"].strip())

            self.app.push_screen(ConfirmModal(
                "Create on GitHub", f"Create the {vis} repository {self.me}/{name} from {d}?\n"
                "It is created empty: commit and push afterwards."), confirmed)

        self.app.push_screen(FormModal("New repository on GitHub", [
            Field("dir", "Local folder", str(clone_base()), paths=True),
            Field("name", "Name"),
            Field("visibility", "Visibility", "private", choices=[("private", "private"), ("public", "public")]),
            Field("description", "Description")], validate=check), done)

    @work(thread=True, exclusive=True, group="op")
    def do_create(self, d: Path, name: str, vis: str, desc: str) -> None:
        if not (d / ".git").exists():
            git(d, "init", "-b", "main")
        cmd = ["gh", "repo", "create", name, f"--{vis}", "--source", str(d), "--remote", "origin"]
        if desc:
            cmd += ["--description", desc]
        r = run(cmd, timeout=60, env=GIT_ENV)
        self.app.call_from_thread(self.create_done, name, r)

    def create_done(self, name: str, r: subprocess.CompletedProcess) -> None:
        self.busy = ""
        if r.returncode != 0:
            self.render_rows()
            return self.app.push_screen(TextModal(f"Create failed · {name}",
                                                  (r.stderr + r.stdout).strip() or "(no output)", end=False))
        self.app.notify_ok(f"Created {self.me}/{name}")
        self.action_rescan()
