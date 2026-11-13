"""AI Agents (GUI): paridad con AgentsView(manage=True) — pestañas:
- Usage: un bloque por proveedor activo (límites de 5 h / 7 d o cuota por modelo y el contexto de
  cada sesión abierta, de las mismas fuentes que la TUI) y abrir claude/opencode en una kitty.
- Providers: mostrar/ocultar cada uno (agents/providers.conf), con si está instalado o corriendo.
- Skills / Agents: cuáles se cargan (agent_skills: carpetas de skills.conf, la primera gana) y los
  propios de cada proveedor activo (provider_sources); prender/apagar, todos on/off.
- Folders: carpetas de origen (agregar con validación, quitar con confirmación, subir/bajar
  prioridad) y lo detectado en los proveedores (solo lectura). Cambiarlas aplica (sk.apply).
- MCPs / LSPs: servidores de Claude Code y opencode (backend agent_tools.py): prender/apagar con el
  mecanismo de cada uno, agregar/sacar MCPs, chequear salud (a mano: levanta los servidores locales)
  e instalar los plugins LSP de Claude (job con log)."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from . import _lib as L

UI: dict = {}
TABS = [("usage", "Usage"), ("providers", "Providers"), ("skills", "Skills"), ("agents", "Agents"),
        ("mcp", "MCPs"), ("lsp", "LSPs"), ("folders", "Folders")]
STATE: dict = {"items": {}, "builtin": False, "tools": {}, "health": False}
TOOL_PROVIDERS = (("claude", "Claude Code", "󰚩"), ("opencode", "opencode", "󰘦"))
WHERE = [["Claude Code and opencode", "both"], ["Claude Code", "claude"], ["opencode", "opencode"]]


def A():
    p = str(L.TOOLS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import agents_tui
    return agents_tui


def tilde(p: str) -> str:
    return str(p).replace(str(Path.home()), "~", 1)


def bar(pct) -> str:
    if pct is None:
        return "no data"
    k = max(0, min(10, round(pct / 10)))
    return "▓" * k + "░" * (10 - k) + f" {pct:3.0f}%"


def limit_rows(pid: str, texts: list) -> list:
    a = A()
    out = []
    for i, t in enumerate(texts):
        s = t.plain
        out.append(L.info(f"{pid}-l{i}", s[:a.LABEL_W].strip() or "·", s[a.LABEL_W:].strip()))
    return out


def session_rows(pid: str, rows: list) -> list:
    a = A()
    out = [L.item(f"{pid}-s{i}", title, sub=detail, right=bar(pct), glyph="󱚣", on=pct is None or pct < 80)
           for i, (title, pct, detail) in enumerate(rows[:a.MAX_AGENTS])]
    if len(rows) > a.MAX_AGENTS:
        out.append(L.info(f"{pid}-more", f"+ {len(rows) - a.MAX_AGENTS} more", ""))
    return out or [L.info(f"{pid}-none", "No open sessions", "")]


def page_usage() -> list:
    a = A()
    on = a.enabled_providers()
    codex = [a.codex_scan(p) for p in a.codex_rollouts()] if "codex" in on else []
    agy = a.agy_entries() if "antigravity" in on else []
    groups = [L.group("Run", [L.button(f"run:{b}", f"Open {n}", "In a new terminal", "Open")
                              for p, n, _i, b in a.PROVIDERS if p in ("claude", "opencode") and a.find_bin(b)])]
    for pid, name, icon, binary in a.PROVIDERS:
        if pid not in on:
            continue
        if not a.find_bin(binary) and not a.running_count(binary):
            groups.append(L.group(f"{icon}  {name}", [L.info(f"{pid}-ni", "Not installed", f"{binary} not found")]))
            continue
        if pid == "claude":
            rows = limit_rows(pid, a.claude_limits()) + session_rows(pid, a.claude_sessions())
            u = a.claude_usage()
            if u.get("updated_at"):
                rows.append(L.info("cl-upd", "Updated", u["updated_at"]))
        elif pid == "opencode":
            rows = session_rows(pid, a.opencode_sessions())
        elif pid == "codex":
            rows = limit_rows(pid, a.codex_limits(codex)) + session_rows(pid, a.codex_sessions(codex))
        else:
            rows = limit_rows(pid, a.agy_limits(agy)) + session_rows(pid, a.agy_sessions(agy))
            if not agy:
                rows.append(L.info("agy-hint", "No data yet", "set agents/agy-statusline.sh as agy's statusLine"))
        groups.append(L.group(f"{icon}  {name}", rows))
    return groups


def page_providers() -> list:
    a = A()
    on = a.enabled_providers()
    rows = []
    for pid, name, icon, binary in a.PROVIDERS:
        path, procs = a.find_bin(binary), a.running_count(binary)
        inst = f"● {procs} running · {tilde(path or binary)}" if procs else (f"installed · {tilde(path)}" if path else f"not installed ({binary})")
        rows.append(L.toggle(f"prov:{pid}", f"{icon}  {name}", inst, pid in on))
    return [L.group("Providers · also applies to the waybar popup and module", rows)]


def load_builtin() -> None:
    a = A()
    if "opencode" in a.enabled_providers() and not a.ps.BUILTIN_CACHE.exists() and not STATE["builtin"]:
        STATE["builtin"] = True

        def run():
            try:
                a.ps.opencode_builtin(refresh=True)
            finally:
                STATE["builtin"] = False
        threading.Thread(target=run, daemon=True).start()


def page_items(kind: str) -> list:
    a = A()
    sk, ps = a.sk, a.ps
    dirs, off = sk.read_conf()
    items = ps.discover(a.enabled_providers())
    STATE["items"] = {i.key: i for i in items}
    q = (UI.get("search") or "").lower()
    match = lambda *s: not q or any(q in (x or "").lower() for x in s)  # noqa: E731
    rows = []
    if kind == "skills":
        found = sk.scan(dirs)
        own = {s.name for s in found}
        dup = {i.name for i in items if i.origin == "claude.ai sync" and i.name in own}
        n_on = sum(1 for s in found if not s.shadowed_by and s.name not in off)
        for s in found:
            if not match(s.name, s.desc):
                continue
            on = not s.shadowed_by and s.name not in off
            rows.append(L.toggle(f"sk:{s.root}|{s.name}", s.name, ("shadowed by " + tilde(s.shadowed_by) + " · " if s.shadowed_by else "")
                                 + (s.desc[:90] if s.desc else "no frontmatter in SKILL.md") + f" · {Path(s.root).name}"
                                 + (" +claude.ai" if s.name in dup else ""), on))
        prov = [i for i in items if i.kind == "skill" and i.name not in dup and match(i.name, i.desc)]
        head = f"{n_on} of {len(found)} loaded · {len(prov)} from providers"
    else:
        agents = sk.scan_agents(dirs)
        agent_off = sk.read_agent_off()
        n_on = sum(1 for x in agents if x.name not in agent_off)
        for x in agents:
            if match(x.name, x.desc):
                rows.append(L.toggle(f"ag:{x.name}", x.name, f"{x.desc[:90]} · {Path(x.root).name} {x.formats}", x.name not in agent_off))
        prov = [i for i in items if i.kind == "agent" and match(i.name, i.desc)]
        head = f"{n_on} of {len(agents)} loaded · {len(prov)} from providers"
    prows = [L.toggle(f"pi:{i.key}", i.name, f"{i.desc[:90]} · {i.provider} · {i.origin}", i.on) if i.toggle else
             L.info(f"pi:{i.key}", i.name, f"fixed · {i.provider} · {i.origin}") for i in prov]
    ctl = [L.button(f"all:{kind}:on", "Enable all", head, "All on"), L.button(f"all:{kind}:off", "Disable all", "Your folders only", "All off")]
    if STATE["builtin"]:
        ctl.append(L.info("bi", "opencode built-in skills", "loading…"))
    return [L.group(kind.capitalize(), ctl), L.group("Your folders", rows or [L.info("none", "Nothing here", "")]),
            L.group("From your providers", prows or [L.info("nonep", "Nothing from providers", "")])]


def page_folders() -> list:
    a = A()
    sk, ps = a.sk, a.ps
    dirs, _ = sk.read_conf()
    found, agents = sk.scan(dirs), sk.scan_agents(dirs)
    rows = []
    for i, d in enumerate(dirs):
        err = sk.validate_dir(d)
        info = f"✗ {err}" if err else f"● {sum(1 for s in found if s.root == d)} skills · {sum(1 for x in agents if x.root == d)} agents"
        acts = [L.action(f"up:{i}", "Up")] if i else []
        acts += [L.action(f"down:{i}", "Down")] if i < len(dirs) - 1 else []
        acts.append(L.action(f"rmdir:{i}", "Remove", True))
        rows.append(L.item(f"dir:{i}", f"{i + 1}. {tilde(d)}", sub=info, on=not err, glyph="󰉋", actions=acts))
    det = []
    for prov, path, kind, n_s, n_a, st in ps.sources(a.enabled_providers()):
        bits = ([f"{n_s} skills"] if n_s else []) + ([f"{n_a} agents"] if n_a else [])
        det.append(L.info(f"det:{path}", f"{prov} · {kind}", f"{tilde(path)} · {' · '.join(bits)}" + ("" if st == "on" else " · disabled")))
    return [L.group("Skills & agents folders · the first one wins on repeated names",
                    rows + [L.button("adddir", "Add folder", "Needs a SKILLS/ subfolder", "Add")]),
            L.group("Detected in your active providers (managed by each provider)", det or [L.info("nodet", "Nothing detected", "")])]


def page_tools(kind: str) -> list:
    a = A()
    at = a.at
    on_prov = a.enabled_providers()
    items = (at.mcp_list if kind == "mcp" else at.lsp_list)(on_prov)
    STATE["tools"].update({t.key: t for t in items})
    q = (UI.get("search") or "").lower()
    groups = []
    if kind == "mcp":
        hc = at.health().get("at")
        groups.append(L.group("MCP servers", [
            L.button("addmcp", "Add MCP server", f"URL (remote) or command (local) · Claude user scope and/or {at._oc_mcp_file().name}", "Add"),
            L.button("health", "Check health", "checking…" if STATE["health"] else
                     (f"last check {a.short_ago(time.time() - hc)} · starts local servers" if hc
                      else "Starts local servers (e.g. Docker) to test them"), "Check")]))
    else:
        groups += L.job_group("lspinstall")
    for pid, name, icon in TOOL_PROVIDERS:
        if pid not in on_prov:
            continue
        rows = []
        mine = [t for t in items if t.provider == pid]
        for t in mine:
            if q and q not in t.name.lower() and q not in t.desc.lower():
                continue
            extra = []
            if t.warn:
                extra.append("⚠ " + t.warn)
            elif kind == "mcp" and t.extra.get("health"):
                extra.append(at.health_label(t.extra["health"])[0])
            sub = " · ".join([t.desc[:80], t.origin] + extra)
            k = f"tool:{t.key}"
            if not t.toggle:
                rows.append(L.info(k, t.name, "fixed · " + sub))
            elif t.toggle == "claude-lsp-install":
                rows.append(L.item(k, t.name, sub=sub, glyph="󰏓", on=False,
                                   actions=[L.action(f"install:{t.key}", "Install")]))
            elif kind == "mcp" and t.removable:
                rows.append(L.item(k, t.name, sub=sub, glyph="󰒍", on=t.on,
                                   actions=[L.action(f"flip:{t.key}", "Turn off" if t.on else "Turn on"),
                                            L.action(f"rmmcp:{t.key}", "Remove", True)]))
            else:
                rows.append(L.toggle(k, t.name, sub, t.on))
        n_on = sum(1 for t in mine if t.on)
        groups.append(L.group(f"{icon}  {name} · {n_on} of {len(mine)} on",
                              rows or [L.info(f"none:{pid}", "Nothing configured", "")]))
    if kind == "lsp":
        groups.append(L.group("Bulk", [L.button("tall:lsp:on", "Enable all", "Never installs: only what is already there", "All on"),
                                       L.button("tall:lsp:off", "Disable all", "", "All off")]))
    else:
        groups.append(L.group("Bulk", [L.button("tall:mcp:on", "Enable all", "", "All on"),
                                       L.button("tall:mcp:off", "Disable all", "Restart open sessions to apply", "All off")]))
    return groups


def fresh_tools(kind: str) -> list:
    """MCPs o LSPs releídos (el cache de STATE puede tener el estado de antes de un cambio)."""
    a = A()
    items = (a.at.mcp_list if kind == "mcp" else a.at.lsp_list)(a.enabled_providers())
    STATE["tools"].update({t.key: t for t in items})
    return items


def get() -> dict:
    tab = UI.get("tab") or "usage"
    if tab in ("skills", "agents"):
        load_builtin()
    groups = {"usage": page_usage, "providers": page_providers, "skills": lambda: page_items("skills"),
              "agents": lambda: page_items("agents"), "folders": page_folders,
              "mcp": lambda: page_tools("mcp"), "lsp": lambda: page_tools("lsp")}[tab]()
    busy = STATE["builtin"] or STATE["health"] or L.job_running("lspinstall")
    p = L.page("AI Agents", "Usage, providers, skills, agents, MCPs and LSPs", groups,
               refresh=5 if tab == "usage" else (2 if busy else 0))
    p.update(tabs=[{"key": k, "label": lbl} for k, lbl in TABS], tab=tab,
             search={"skills": "Filter skills…", "agents": "Filter agents…", "mcp": "Filter MCPs…",
                     "lsp": "Filter LSPs…"}.get(tab, ""))
    return p


def apply(msg: str) -> dict:
    try:
        A().sk.apply()
    except OSError as e:
        return L.fail(f"Could not apply: {e}")
    return L.ok(msg)


def set_value(key, value):
    a = A()
    sk, ps = a.sk, a.ps
    op, _, arg = key.partition(":")
    if op == "prov":
        a.set_provider(arg, bool(value))
        name = next(n for p, n, *_ in a.PROVIDERS if p == arg)
        load_builtin()
        return L.ok(f"{name} {'shown' if value else 'hidden'}")
    if op == "tool":
        t = STATE["tools"].get(arg)
        if t is None:
            return L.fail("Not found: reload")
        if err := a.at.set_enabled(t, bool(value)):
            return L.fail(err)
        return L.ok(f"{t.name} {'enabled' if value else 'disabled'} in {t.provider}")
    if op == "pi":
        item = STATE["items"].get(arg)
        if item is None:
            return L.fail("Not found: reload")
        if err := ps.set_enabled(item, bool(value)):
            return L.fail(err)
        return L.ok(f"{item.name} {'enabled' if value else 'disabled'} in {item.provider}")
    dirs, off = sk.read_conf()
    if op == "sk":
        root, _, name = arg.partition("|")
        owner = next((s for s in sk.scan(dirs) if s.name == name and not s.shadowed_by), None)
        if owner is None or owner.root != root:
            return L.fail(f"{name} is shadowed by {owner.root if owner else 'another folder'}")
        (off.discard if value else off.add)(name)
        sk.write_conf(dirs, off)
        return apply(f"{name} {'enabled' if value else 'disabled'}")
    if op == "ag":
        agent_off = sk.read_agent_off()
        (agent_off.discard if value else agent_off.add)(arg)
        sk.write_conf(dirs, off, agent_off)
        return apply(f"{arg} {'enabled' if value else 'disabled'}")
    return L.fail("Unknown setting")


def act(key, text=None):
    a = A()
    sk = a.sk
    op, _, arg = key.partition(":")
    dirs, off = sk.read_conf()
    at = a.at
    if op == "log" and arg == "lspinstall":
        return L.text_view("LSP plugin install", L.job_text("lspinstall"))
    if op == "flip":
        t = next((x for x in fresh_tools(arg.split("|")[1]) if x.key == arg), None)
        if t is None:
            return L.fail("Not found: reload")
        return set_value(f"tool:{arg}", not t.on)
    if op == "install":
        t = STATE["tools"].get(arg)
        if t is None:
            return L.fail("Not found: reload")
        if not L.yes(text):
            return L.confirm(key, "Install LSP plugin", f"Install {t.ref} for Claude Code (claude plugin install, user scope)?"
                             + (f"\n\n{t.extra.get('about')}" if t.extra.get("about") else "")
                             + (f"\n\nIt {t.warn}: install it with pacman/yay or Claude Code will not start it." if t.warn else ""),
                             danger=False, ok_label="Install")
        exe = at.claude_bin()
        if not exe:
            return L.fail("claude is not installed")
        return L.job_start("lspinstall", f"Install {t.ref}", [("user", [exe, "plugin", "install", "-s", "user", t.ref], t.ref)])
    if op == "rmmcp":
        t = STATE["tools"].get(arg)
        if t is None:
            return L.fail("Not found: reload")
        if not L.yes(text):
            where = "~/.claude.json (user scope)" if t.provider == "claude" else t.origin
            return L.confirm(key, "Remove MCP server", f"Remove {t.name} from {where}?\nTo keep its config, turn it off instead.",
                             ok_label="Remove")
        err = at.remove_mcp(t)
        return L.fail(err) if err else L.ok(f"{t.name} removed")
    if op == "addmcp":
        def fields(v: dict) -> list:
            return [{"name": "name", "label": "NAME", "text": v.get("name", "")},
                    {"name": "target", "label": "URL OR COMMAND", "text": v.get("target", "")},
                    {"name": "where", "label": "ADD TO", "text": v.get("where", "both"), "choices": WHERE},
                    {"name": "header", "label": "HEADER (OPTIONAL)", "text": v.get("header", "")}]
        if text is None:
            return L.form("addmcp", "Add MCP server", fields({}),
                          hint="https://… (remote) or npx -y @scope/server (local) · header: Authorization: Bearer {env:TOKEN}")
        v = L.parse_form(text)
        v["name"] = v.get("name", "").strip()
        if err := at.validate_new(v["name"], v.get("target", ""), v.get("where") or "both", v.get("header", "")):
            return L.form("addmcp", "Add MCP server", fields(v), error=err)
        err = at.add_mcp(v["name"], v["target"], v.get("where") or "both", v.get("header", ""))
        return L.fail(err) if err else L.ok(f"{v['name']} added")
    if op == "health":
        if not STATE["health"]:
            STATE["health"] = True

            def run():
                try:
                    at.check_health()
                finally:
                    STATE["health"] = False
            threading.Thread(target=run, daemon=True).start()
        return L.ok("Checking MCP health…")
    if op == "tall":
        kind, _, state = arg.partition(":")
        on = state == "on"
        todo = [t for t in fresh_tools(kind) if t.kind == kind and t.toggle and t.toggle != "claude-lsp-install"
                and t.on != on and t.provider in a.enabled_providers()]
        errs = [e for t in todo if (e := at.set_enabled(t, on))]
        return L.fail(errs[0]) if errs else L.ok(f"{len(todo)} {'enabled' if on else 'disabled'}" if todo else "Nothing to change")
    if op == "run":
        path = a.find_bin(arg)
        if not path:
            return L.fail(f"{arg} is not installed")
        L.detach(["kitty", "--title", arg, "-e", path])
        return {"ok": True, "msg": "", "close": True}
    if op == "all":
        kind, _, state = arg.partition(":")
        on = state == "on"
        if kind == "skills":
            sk.write_conf(dirs, set() if on else {s.name for s in sk.scan(dirs)})
        else:
            sk.write_conf(dirs, off, set() if on else {x.name for x in sk.scan_agents(dirs)})
        return apply(f"All {kind} {'enabled' if on else 'disabled'}")
    if op == "adddir":
        fields = lambda v: [{"name": "path", "label": "FOLDER", "text": v}]  # noqa: E731
        if text is None:
            return L.form("adddir", "Add folder", fields(""), hint="/path/with/SKILLS/ · needs a SKILLS/ subfolder")
        p = L.parse_form(text).get("path", "").strip()
        err = "Enter a folder" if not p else ("Already in the list" if sk._expand(p) in dirs else sk.validate_dir(p))
        if err:
            return L.form("adddir", "Add folder", fields(p), error=err)
        sk.write_conf(dirs + [sk._expand(p)], off)
        return apply("Folders updated")
    if op in ("up", "down", "rmdir") and arg.isdigit() and int(arg) < len(dirs):
        i = int(arg)
        if op == "rmdir":
            if not L.yes(text):
                return L.confirm(key, "Remove folder", f"Stop loading skills and agents from {dirs[i]}?\n"
                                 "The folder itself is not deleted.", ok_label="Remove")
            sk.write_conf([x for x in dirs if x != dirs[i]], off)
            return apply("Folders updated")
        j = i - 1 if op == "up" else i + 1
        if 0 <= j < len(dirs):
            dirs[i], dirs[j] = dirs[j], dirs[i]
            sk.write_conf(dirs, off)
            return apply("Folders updated")
    return L.ok()
