#!/usr/bin/env python3
"""MCPs y LSPs de los agentes (Claude Code y opencode): verlos, prenderlos/apagarlos, agregar y sacar.

Backend sin Textual (lo usan Settings → AI Agents, pestañas MCPs y LSPs, en la TUI y en la GUI).
Igual que provider_sources.py para skills: cada cosa se apaga con el mecanismo PROPIO de su
proveedor, nunca borrando lo que no es nuestro.

  qué                     se lee de                                   cómo se apaga / prende
  ----------------------  ------------------------------------------  ---------------------------------------
  MCP de Claude (user)    ~/.claude.json → mcpServers                  `claude mcp remove -s user` guardando la
                                                                       config en el estado (aparcado) y
                                                                       `claude mcp add-json -s user` al prender
                                                                       (Claude no tiene un "disabled" global)
  MCP de un plugin        .mcp.json / plugin.json del plugin           el plugin entero (`enabledPlugins`)
  MCP local de proyecto   ~/.claude.json → projects[…].mcpServers      solo lectura
  Conector de claude.ai   cache de salud + claudeAiMcpEverConnected    solo lectura (se gestiona en claude.ai)
  MCP de opencode         opencode.jsonc → mcp (+ opencode.json)       `"enabled": true|false` en el mismo
                                                                       .jsonc (le gana a opencode.json, así que
                                                                       ahí no sirve) editado por spans. Si el
                                                                       .jsonc es un symlink (generado desde una
                                                                       plantilla), se edita opencode.json
  LSP de Claude           plugins del marketplace con `lspServers`     instalar (`claude plugin install`) y
                                                                       después `enabledPlugins`
  LSP de opencode         integrados (del binario, cacheados) + `lsp`  `lsp.<id>.disabled = true` en
                          de la config                                 opencode.json (el .jsonc no tiene `lsp`)

La salud (`claude mcp list` / `opencode mcp list`) solo se pide a mano: levanta los servidores
locales (ej. un contenedor de Docker), así que nunca va en un timer. Queda cacheada.

Todo lo que se escribe va con temporal + os.replace. Variables para probar sobre copias:
CLAUDE_HOME, CLAUDE_JSON, OPENCODE_DIR, AGENTS_CACHE, AGENT_TOOLS_STATE, CLAUDE_BIN, OPENCODE_BIN.

Uso: agent_tools.py mcp | lsp | health
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_skills as sk  # noqa: E402
import provider_sources as ps  # noqa: E402

HOME = Path.home()
CLAUDE_HOME = sk.CLAUDE_HOME
CLAUDE_JSON = Path(os.environ.get("CLAUDE_JSON", HOME / ".claude.json"))
OPENCODE_DIR = sk.OPENCODE_DIR
CACHE_DIR = ps.CACHE_DIR
STATE_FILE = Path(os.environ.get("AGENT_TOOLS_STATE") or sk.STATE_HOME / "dotfiles" / "agent-tools.json")
HEALTH_CACHE = CACHE_DIR / "mcp-health.json"
LSP_CACHE = CACHE_DIR / "opencode-lsp.json"
USER_BIN_DIRS = ps.USER_BIN_DIRS + [HOME / ".npm-global" / "bin", HOME / ".claude" / "local", HOME / "go" / "bin"]
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOCK = threading.Lock()


def which(name: str) -> str | None:
    """Binario en el PATH o en las carpetas por usuario (lo que lanza Hyprland no las tiene)."""
    if not name:
        return None
    if os.sep in name:
        return name if os.access(name, os.X_OK) else None
    found = shutil.which(name)
    if found:
        return found
    for d in USER_BIN_DIRS:
        f = d / name
        if f.is_file() and os.access(f, os.X_OK):
            return str(f)
    return None


def claude_bin() -> str | None:
    return os.environ.get("CLAUDE_BIN") or which("claude")


def opencode_bin() -> str | None:
    return os.environ.get("OPENCODE_BIN") or which("opencode")


def tilde(p) -> str:
    return str(p).replace(str(HOME), "~", 1)


@dataclass
class Tool:
    provider: str          # claude | opencode
    kind: str              # mcp | lsp
    name: str
    desc: str              # transporte + destino (MCP) o extensiones (LSP)
    origin: str            # "user", "plugin foo", "claude.ai", "built-in", "opencode.jsonc"…
    on: bool = True
    toggle: str = ""       # "" = solo lectura | claude-mcp | claude-plugin | claude-lsp-install | opencode-mcp | opencode-lsp
    ref: str = ""
    why: str = ""          # por qué es de solo lectura
    removable: bool = False
    warn: str = ""         # problema visible (binario que falta, config inválida)
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}|{self.kind}|{self.name}|{self.origin}"

    @property
    def slow(self) -> bool:
        """Cambiarlo corre la CLI de claude (segundos): la UI lo hace en un hilo."""
        return self.toggle in ("claude-mcp", "claude-lsp-install")


# ── JSON / estado ─────────────────────────────────────────

def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def _write_text(path: Path, text: str) -> None:
    ps._write_text(path, text)


def _state() -> dict:
    d = _read_json(STATE_FILE)
    return d if isinstance(d, dict) else {}


def _save_state(d: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _write_text(STATE_FILE, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    try:
        STATE_FILE.chmod(0o600)            # la config aparcada puede tener tokens en headers/env
    except OSError:
        pass


# ── JSONC con spans (editar opencode.jsonc sin perder comentarios) ─

class _Node:
    __slots__ = ("start", "end", "value", "members")

    def __init__(self, start: int, end: int, value, members=None):
        self.start, self.end, self.value = start, end, value
        self.members = members           # objeto: {clave: (inicio de la clave, _Node)}


class _JSONC:
    def __init__(self, text: str):
        self.s, self.i = text, 0

    def ws(self) -> None:
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif s.startswith("//", self.i):
                j = s.find("\n", self.i)
                self.i = len(s) if j < 0 else j
            elif s.startswith("/*", self.i):
                j = s.find("*/", self.i + 2)
                self.i = len(s) if j < 0 else j + 2
            else:
                break

    def string(self) -> _Node:
        s, start = self.s, self.i
        j = start + 1
        while j < len(s) and s[j] != '"':
            j += 2 if s[j] == "\\" else 1
        if j >= len(s):
            raise ValueError("unterminated string")
        self.i = j + 1
        return _Node(start, self.i, json.loads(s[start:self.i]))

    def value(self) -> _Node:
        self.ws()
        s, start = self.s, self.i
        if start >= len(s):
            raise ValueError("unexpected end")
        c = s[start]
        if c == '"':
            return self.string()
        if c == "{":
            self.i += 1
            members, val = {}, {}
            while True:
                self.ws()
                if self.s[self.i] == "}":
                    self.i += 1
                    break
                kstart = self.i
                k = self.string()
                self.ws()
                if self.s[self.i] != ":":
                    raise ValueError(f"expected ':' at {self.i}")
                self.i += 1
                v = self.value()
                members[k.value] = (kstart, v)
                val[k.value] = v.value
                self.ws()
                if self.s[self.i] == ",":
                    self.i += 1
                elif self.s[self.i] != "}":
                    raise ValueError(f"expected ',' or '}}' at {self.i}")
            return _Node(start, self.i, val, members)
        if c == "[":
            self.i += 1
            val = []
            while True:
                self.ws()
                if self.s[self.i] == "]":
                    self.i += 1
                    break
                val.append(self.value().value)
                self.ws()
                if self.s[self.i] == ",":
                    self.i += 1
            return _Node(start, self.i, val)
        m = re.compile(r"-?[0-9.eE+-]+|true|false|null").match(s, start)
        if not m:
            raise ValueError(f"unexpected {c!r} at {start}")
        self.i = m.end()
        return _Node(start, self.i, json.loads(m.group(0)))


def jsonc_parse(text: str) -> _Node:
    p = _JSONC(text)
    root = p.value()
    if not isinstance(root.value, dict):
        raise ValueError("not a JSON object")
    return root


def _indent_at(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    m = re.match(r"[ \t]*", text[line_start:])
    return m.group(0) if m else ""


def _dump_block(obj, indent: str) -> str:
    """JSON con 2 espacios, desde la columna `indent` (las líneas siguientes llevan ese margen)."""
    return json.dumps(obj, indent=2, ensure_ascii=False).replace("\n", "\n" + indent)


def jsonc_set_member(text: str, path: list[str], key: str, value) -> str:
    """Pone `key: value` en el objeto de `path` (lo reemplaza si ya está; si no, lo agrega al final)."""
    root = jsonc_parse(text)
    node = root
    for p in path:
        if p not in (node.members or {}):
            return _add_path(text, root, path, key, value)
        node = node.members[p][1]
    if node.members is None:
        raise ValueError("/".join(path) + " is not an object")
    if key in node.members:
        v = node.members[key][1]
        ind = _indent_at(text, node.members[key][0])
        return text[:v.start] + _dump_block(value, ind) + text[v.end:]
    return _append_member(text, node, key, value)


def _append_member(text: str, node: _Node, key: str, value) -> str:
    if node.members:
        last_k, last_v = list(node.members.values())[-1]
        ind = _indent_at(text, last_k)
        sep = "\n\n" if isinstance(value, dict) and len(value) > 1 else "\n"
        return (text[:last_v.end] + f",{sep}{ind}{json.dumps(key)}: {_dump_block(value, ind)}" + text[last_v.end:])
    ind = _indent_at(text, node.start) + "  "
    outer = _indent_at(text, node.start)
    return (text[:node.start] + "{\n" + f"{ind}{json.dumps(key)}: {_dump_block(value, ind)}\n{outer}}}"
            + text[node.end:])


def _add_path(text: str, root: _Node, path: list[str], key: str, value) -> str:
    """Crea los objetos que faltan de `path` y deja `key: value` adentro."""
    node, i = root, 0
    while i < len(path) and path[i] in (node.members or {}):
        node = node.members[path[i]][1]
        i += 1
    obj = {key: value}
    for p in reversed(path[i + 1:]):
        obj = {p: obj}
    return _append_member(text, node, path[i], obj)


def jsonc_remove_member(text: str, path: list[str], key: str) -> str:
    """Saca `key` del objeto de `path`, con los comentarios `//` que tenga justo arriba y su coma."""
    node = jsonc_parse(text)
    for p in path:
        node = node.members[p][1]
    if key not in node.members:
        return text
    keys = list(node.members)
    idx = keys.index(key)
    kstart, v = node.members[key]
    # comentarios de línea pegados arriba (sin una línea en blanco de por medio)
    start = text.rfind("\n", 0, kstart) + 1
    while start > 0:
        prev = text.rfind("\n", 0, start - 1) + 1
        line = text[prev:start - 1].strip()
        if line.startswith("//"):
            start = prev
        else:
            break
    if len(keys) == 1:
        return text[:node.start] + "{}" + text[node.end:]
    if idx < len(keys) - 1:
        # no es el último: se va hasta la coma y el resto de la línea
        j = v.end
        while j < len(text) and text[j] in " \t":
            j += 1
        if j < len(text) and text[j] == ",":
            j += 1
        nl = text.find("\n", j)
        end = len(text) if nl < 0 else nl + 1
        # una línea en blanco que quede doble se colapsa
        if text[end:end + 1] == "\n" and (start == 0 or text[start - 2:start] == "\n\n"):
            end += 1
        return text[:start] + text[end:]
    # el último: se saca la coma del anterior y todo hasta el final del valor
    prev_v = node.members[keys[idx - 1]][1]
    return text[:prev_v.end] + text[v.end:]


# ── opencode: config ──────────────────────────────────────

def _oc_jsonc() -> Path:
    return OPENCODE_DIR / "opencode.jsonc"


def _oc_json() -> Path:
    return OPENCODE_DIR / "opencode.json"


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def opencode_conf() -> tuple[dict, dict]:
    """(opencode.jsonc, opencode.json) como dicts. opencode los fusiona y el .jsonc gana."""
    try:
        jc = jsonc_parse(_oc_jsonc().read_text()).value
    except (OSError, ValueError):
        jc = {}
    try:
        js = ps._read_json(_oc_json())
    except ValueError:
        js = {}
    return jc, js


def _oc_mcp_file() -> Path:
    """Dónde se escriben los MCP de opencode: el .jsonc, salvo que sea un symlink (generado en otro
    lado, ej. desde una plantilla): ahí, opencode.json. El editor por spans sirve para los dos."""
    f = _oc_jsonc()
    return _oc_json() if f.is_symlink() or not f.exists() else f


def _oc_mcp_text() -> str:
    f = _oc_mcp_file()
    try:
        return f.read_text()
    except FileNotFoundError:
        return "{\n}\n"


def _write_jsonc(new: str, check) -> None:
    """Valida el resultado (que parsee y que `check(dict)` dé True) y reemplaza atómico."""
    f = _oc_mcp_file()
    if f.is_symlink():
        raise ValueError(f"{f.name} is generated elsewhere (symlink): not touched")
    parsed = jsonc_parse(new).value
    if not check(parsed):
        raise ValueError("the edit did not produce the expected config: nothing written")
    _write_text(f, new)


# ── MCP ───────────────────────────────────────────────────

def _target(conf: dict) -> str:
    if conf.get("url"):
        return conf["url"]
    cmd = conf.get("command")
    if isinstance(cmd, list):
        return " ".join(cmd)
    return " ".join([cmd or "", *(conf.get("args") or [])]).strip()


def _transport(conf: dict) -> str:
    t = conf.get("type") or ("http" if conf.get("url") else "stdio")
    return {"local": "stdio", "remote": "http"}.get(t, t)


def health() -> dict:
    return _read_json(HEALTH_CACHE)


def _health_of(provider: str, name: str) -> str:
    return (health().get(provider) or {}).get(name, "")


def _plugin_mcps(path: Path) -> dict:
    out: dict = {}
    for f, key in ((path / ".mcp.json", None), (path / ".claude-plugin" / "plugin.json", "mcpServers")):
        d = _read_json(f)
        if key:
            d = d.get(key)
            if isinstance(d, str):
                d = _read_json(path / d)
        if isinstance(d, dict):
            out.update(d.get("mcpServers", d) if "mcpServers" in d else d)
    return {k: v for k, v in out.items() if isinstance(v, dict)}


def mcp_claude() -> list[Tool]:
    out: list[Tool] = []
    cj = _read_json(CLAUDE_JSON)
    parked = (_state().get("parked_mcp") or {}).get("claude") or {}
    servers = cj.get("mcpServers") or {}
    for name in sorted(set(servers) | set(parked), key=str.lower):
        conf = servers.get(name) or parked.get(name) or {}
        on = name in servers
        out.append(Tool("claude", "mcp", name, f"{_transport(conf)} · {_target(conf)}", "user", on, "claude-mcp",
                        name, removable=True, extra={"health": _health_of("claude", name) if on else ""}))
    for proj, pd in sorted((cj.get("projects") or {}).items()):
        for name, conf in sorted((pd.get("mcpServers") or {}).items()):
            out.append(Tool("claude", "mcp", name, f"{_transport(conf)} · {_target(conf)}", f"local · {tilde(proj)}",
                            name not in (pd.get("disabledMcpServers") or []),
                            why=f"local scope of {tilde(proj)}: `claude mcp remove -s local {name}` there",
                            extra={"health": ""}))
    for key, pname, path, on in ps._claude_plugins():
        for name, conf in sorted(_plugin_mcps(path).items()):
            out.append(Tool("claude", "mcp", f"{pname}:{name}", f"{_transport(conf)} · {_target(conf)}",
                            f"plugin {pname}", on, "claude-plugin", key,
                            extra={"health": _health_of("claude", f"plugin:{pname}:{name}")}))
    conns = {n for n in (health().get("claude") or {}) if n.startswith("claude.ai ")}
    conns |= set(cj.get("claudeAiMcpEverConnected") or [])
    for name in sorted(conns):
        out.append(Tool("claude", "mcp", name.removeprefix("claude.ai "), "claude.ai connector", "claude.ai",
                        why="a claude.ai connector: manage it in claude.ai → Settings → Connectors",
                        extra={"health": _health_of("claude", name)}))
    return out


def mcp_opencode() -> list[Tool]:
    jc, js = opencode_conf()
    merged = _deep_merge(js.get("mcp") or {}, jc.get("mcp") or {})
    in_json = _oc_mcp_file() == _oc_json()         # el .jsonc es generado: se escribe opencode.json
    out: list[Tool] = []
    for name, conf in merged.items():
        if not isinstance(conf, dict):
            continue
        in_jsonc = name in (jc.get("mcp") or {})
        editable = not in_jsonc if in_json else in_jsonc
        if editable:
            why = ""
        elif in_json:
            why = "defined in the generated opencode.jsonc: change it in its template"
        else:
            why = "defined in opencode.json: edit it there"
        t = conf.get("type")
        warn = "" if t in ("local", "remote") else f"invalid type {t!r}: opencode ignores it (use local or remote)"
        out.append(Tool("opencode", "mcp", name, f"{_transport(conf)} · {_target(conf)}",
                        "opencode.jsonc" if in_jsonc else "opencode.json", conf.get("enabled", True) is not False,
                        "opencode-mcp" if editable else "", name, why=why,
                        removable=editable, warn=warn, extra={"health": _health_of("opencode", name)}))
    return out


def mcp_list(providers: set[str] | None = None) -> list[Tool]:
    out: list[Tool] = []
    if providers is None or "claude" in providers:
        out += mcp_claude()
    if providers is None or "opencode" in providers:
        out += mcp_opencode()
    return out


def _claude(args: list[str], timeout: int = 60) -> tuple[bool, str]:
    exe = claude_bin()
    if not exe:
        return False, "claude is not installed"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, cwd=str(HOME))
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    out = _ANSI.sub("", (r.stdout + r.stderr).strip())
    return r.returncode == 0, out


def _claude_json_conf(conf: dict) -> dict:
    """Config de opencode → formato de Claude (`claude mcp add-json`)."""
    if conf.get("url"):
        d = {"type": "http", "url": conf["url"]}
        if conf.get("headers"):
            d["headers"] = conf["headers"]
        return d
    cmd = conf.get("command") or []
    if isinstance(cmd, str):
        cmd = [cmd, *(conf.get("args") or [])]
    d = {"type": "stdio", "command": cmd[0] if cmd else "", "args": cmd[1:]}
    env = conf.get("env") or conf.get("environment")
    if env:
        d["env"] = env
    return d


def set_claude_mcp(name: str, on: bool) -> str | None:
    with _LOCK:
        st = _state()
        parked = st.setdefault("parked_mcp", {}).setdefault("claude", {})
        if on:
            conf = parked.get(name)
            if conf is None:
                return f"{name}: no saved config to restore"
            ok, out = _claude(["mcp", "add-json", "-s", "user", name, json.dumps(conf)])
            if not ok:
                return out or "claude mcp add-json failed"
            parked.pop(name, None)
        else:
            conf = (_read_json(CLAUDE_JSON).get("mcpServers") or {}).get(name)
            if conf is None:
                return f"{name} is not configured"
            parked[name] = conf                 # primero se guarda, después se saca
            _save_state(st)
            ok, out = _claude(["mcp", "remove", "-s", "user", name])
            if not ok:
                parked.pop(name, None)
                _save_state(st)
                return out or "claude mcp remove failed"
        _save_state(st)
    return None


def set_opencode_mcp(name: str, on: bool) -> str | None:
    try:
        text = _oc_mcp_text()
        new = jsonc_set_member(text, ["mcp", name], "enabled", on)
        _write_jsonc(new, lambda d: d["mcp"][name].get("enabled") is on)
    except (OSError, ValueError, KeyError) as e:
        return f"could not change {name}: {e}"
    return None


def set_enabled(item: Tool, on: bool) -> str | None:
    """Prende/apaga con el mecanismo del proveedor. Devuelve un mensaje de error o None."""
    if not item.toggle:
        return f"{item.name}: {item.why or 'read-only'}"
    try:
        if item.toggle == "claude-mcp":
            return set_claude_mcp(item.ref, on)
        if item.toggle == "claude-plugin":
            ps.set_claude_plugin(item.ref, on)
        elif item.toggle == "claude-lsp-install":
            if not on:
                return None
            ok, out = _claude(["plugin", "install", "-s", "user", item.ref], timeout=300)
            if not ok:
                return out.splitlines()[-1] if out else "claude plugin install failed"
        elif item.toggle == "opencode-mcp":
            return set_opencode_mcp(item.ref, on)
        elif item.toggle == "opencode-lsp":
            set_opencode_lsp(item.ref, on)
    except (OSError, ValueError) as e:
        return f"could not change {item.name}: {e}"
    return None


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def parse_target(target: str, header: str = "") -> dict:
    """URL → remota; otra cosa → comando local. Devuelve la config en formato opencode."""
    target = target.strip()
    if re.match(r"^https?://", target):
        d: dict = {"type": "remote", "url": target}
        if header.strip():
            k, _, v = header.partition(":")
            d["headers"] = {k.strip(): v.strip()}
        return d
    return {"type": "local", "command": shlex.split(target)}


def validate_new(name: str, target: str, where: str, header: str = "") -> str | None:
    if not NAME_RE.match(name or ""):
        return "name: letters, digits, . _ - (up to 64)"
    if not target.strip():
        return "enter a URL or a command"
    if header.strip() and ":" not in header:
        return "header: Name: value"
    try:
        conf = parse_target(target, header)
    except ValueError as e:
        return f"command: {e}"
    if conf["type"] == "local" and not which(conf["command"][0]):
        return f"{conf['command'][0]} not found"
    have = {(t.provider, t.name) for t in mcp_list()}
    for p in (("claude", "opencode") if where == "both" else (where,)):
        if (p, name) in have:
            return f"{name} already exists in {p}"
        if p == "claude" and not claude_bin():
            return "claude is not installed"
    return None


def add_mcp(name: str, target: str, where: str, header: str = "") -> str | None:
    """Agrega un MCP en Claude (user) y/o opencode (.jsonc, o .json si el .jsonc es generado). Error o None."""
    conf = parse_target(target, header)
    errs = []
    if where in ("both", "opencode"):
        try:
            text = _oc_mcp_text()
            new = jsonc_set_member(text, ["mcp"], name, {**conf, "enabled": True})
            _write_jsonc(new, lambda d: name in d.get("mcp", {}))
        except (OSError, ValueError) as e:
            errs.append(f"opencode: {e}")
    if where in ("both", "claude"):
        ok, out = _claude(["mcp", "add-json", "-s", "user", name, json.dumps(_claude_json_conf(conf))])
        if not ok:
            errs.append(f"claude: {out or 'failed'}")
    return "; ".join(errs) or None


def remove_mcp(item: Tool) -> str | None:
    if not item.removable:
        return f"{item.name}: {item.why or 'cannot be removed from here'}"
    if item.provider == "claude":
        with _LOCK:
            st = _state()
            parked = st.setdefault("parked_mcp", {}).setdefault("claude", {})
            if item.name in parked and not item.on:
                parked.pop(item.name)
                _save_state(st)
                return None
        ok, out = _claude(["mcp", "remove", "-s", "user", item.name])
        return None if ok else (out or "claude mcp remove failed")
    try:
        text = _oc_mcp_text()
        new = jsonc_remove_member(text, ["mcp"], item.name)
        _write_jsonc(new, lambda d: item.name not in d.get("mcp", {}))
    except (OSError, ValueError, KeyError) as e:
        return f"could not remove {item.name}: {e}"
    return None


def check_health() -> dict:
    """`claude mcp list` y `opencode mcp list` (en paralelo). Levanta los servidores locales: solo a mano."""
    res: dict = {"claude": {}, "opencode": {}}

    def cl() -> None:
        ok, out = _claude(["mcp", "list"], timeout=90)
        for line in out.splitlines():
            if ": " not in line or " - " not in line:
                continue
            name, rest = line.split(": ", 1)
            status = rest.rsplit(" - ", 1)[1].strip()
            res["claude"][name.strip()] = status

    def oc() -> None:
        exe = opencode_bin()
        if not exe:
            return
        try:
            out = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True, timeout=90,
                                 stdin=subprocess.DEVNULL, cwd=str(HOME)).stdout
        except (OSError, subprocess.TimeoutExpired):
            return
        for line in _ANSI.sub("", out).splitlines():
            m = re.search(r"([✓✗○⚠!])\s+(\S+)\s+(.+?)\s*$", line)
            if m:
                res["opencode"][m.group(2)] = {"✓": "✔ "}.get(m.group(1), m.group(1) + " ") + m.group(3)
    th = [threading.Thread(target=f) for f in (cl, oc)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    res["at"] = time.time()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _write_text(HEALTH_CACHE, json.dumps(res, ensure_ascii=False, indent=1) + "\n")
    return res


def health_label(status: str) -> tuple[str, str]:
    """(texto corto, nivel ok|warn|error|"") para mostrar la salud."""
    if not status:
        return "", ""
    s = status.lower()
    if "connected" in s and "fail" not in s:
        return "✓ connected", "ok"
    if "auth" in s:
        return "! needs auth", "warn"
    if "pending" in s or "disabled" in s:
        return status[:24], "warn"
    return "✗ " + re.sub(r"^[✘✗]\s*", "", status).split("—")[0].strip()[:30], "error"


# ── LSP ───────────────────────────────────────────────────

def _marketplace_plugins() -> list[tuple[str, str, Path]]:
    """(nombre, marketplace, carpeta) de todos los plugins de los marketplaces conocidos."""
    out = []
    for mk in sorted((CLAUDE_HOME / "plugins" / "marketplaces").glob("*/")):
        for base in ("plugins", "external_plugins"):
            for p in sorted((mk / base).glob("*/")):
                out.append((p.name, mk.name, p))
    return out


def _lsp_servers(path: Path) -> dict:
    out: dict = {}
    pj = _read_json(path / ".claude-plugin" / "plugin.json")
    d = pj.get("lspServers")
    if isinstance(d, str):
        d = _read_json(path / d)
    if isinstance(d, dict):
        out.update(d)
    lj = _read_json(path / ".lsp.json")
    if isinstance(lj, dict):
        out.update(lj)
    return {k: v for k, v in out.items() if isinstance(v, dict) and v.get("command")}


def lsp_claude() -> list[Tool]:
    installed = {k: (on, path) for k, _n, path, on in ps._claude_plugins()}
    out: list[Tool] = []
    for name, mk, path in _marketplace_plugins():
        servers = _lsp_servers(path)
        if not servers:
            continue
        key = f"{name}@{mk}"
        exts = sorted({e for s in servers.values() for e in (s.get("extensionToLanguage") or {})})
        cmds = [s["command"] for s in servers.values()]
        missing = [c for c in cmds if not which(c)]
        desc = _read_json(path / ".claude-plugin" / "plugin.json").get("description", "")
        if key in installed:
            on = installed[key][0]
            t = Tool("claude", "lsp", name, " ".join(exts), f"plugin · {mk}", on, "claude-plugin", key)
        else:
            t = Tool("claude", "lsp", name, " ".join(exts), f"plugin · {mk}", False, "claude-lsp-install", key)
        t.warn = f"needs {', '.join(missing)} installed" if missing else ""
        t.extra = {"installed": key in installed, "about": desc, "command": " ".join(cmds)}
        out.append(t)
    return out


def opencode_builtin_lsp() -> list[tuple[str, list[str]]]:
    """LSPs integrados de opencode (id, extensiones), sacados del binario y cacheados por versión."""
    exe = opencode_bin()
    real = Path(os.path.realpath(exe)) if exe else None
    sig = ""
    if real and real.is_file():
        st = real.stat()
        sig = f"{real}|{st.st_size}|{int(st.st_mtime)}"
    cached = _read_json(LSP_CACHE)
    if cached.get("sig") == sig and cached.get("servers"):
        return [tuple(x) for x in cached["servers"]]
    if not sig:
        return [tuple(x) for x in cached.get("servers", [])]
    try:
        data = real.read_bytes()
    except OSError:
        return [tuple(x) for x in cached.get("servers", [])]
    found: dict[str, list[str]] = {}
    for m in re.finditer(rb'id:"([a-z0-9-]+)",(?:extensions|root):', data):
        win = data[m.start():m.start() + 900]
        e = re.search(rb"extensions:\[([^\]]*)\]", win)
        if e and b"spawn" in win:
            exts = [x.decode(errors="replace") for x in re.findall(rb'"([^"]*)"', e.group(1))]
            found.setdefault(m.group(1).decode(), exts)
    servers = sorted(found.items())
    if servers:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _write_text(LSP_CACHE, json.dumps({"sig": sig, "servers": servers}) + "\n")
    return [tuple(x) for x in servers]


def lsp_opencode() -> list[Tool]:
    jc, js = opencode_conf()
    lsp_jc = jc.get("lsp") if isinstance(jc.get("lsp"), dict) else {}
    lsp_js = js.get("lsp") if isinstance(js.get("lsp"), dict) else {}
    merged = _deep_merge(lsp_js, lsp_jc)
    out: list[Tool] = []
    seen = set()

    def mk(lid: str, exts: list[str], origin: str) -> Tool:
        conf = merged.get(lid) or {}
        on = not conf.get("disabled")
        if lid in lsp_jc:
            return Tool("opencode", "lsp", lid, " ".join(exts), origin, on,
                        why="set in opencode.jsonc: edit it there")
        return Tool("opencode", "lsp", lid, " ".join(exts), origin, on, "opencode-lsp", lid)
    for lid, exts in opencode_builtin_lsp():
        seen.add(lid)
        out.append(mk(lid, list(exts), "built-in"))
    for lid, conf in merged.items():
        if lid in seen or not isinstance(conf, dict) or not conf.get("command"):
            continue
        t = mk(lid, list(conf.get("extensions") or []), "config")
        cmd = conf["command"][0] if isinstance(conf["command"], list) else conf["command"]
        t.warn = "" if which(cmd) else f"needs {cmd} installed"
        out.append(t)
    return out


def set_opencode_lsp(lid: str, on: bool) -> None:
    """lsp.<id>.disabled en opencode.json (hermano del .jsonc, que no tiene `lsp`)."""
    f = _oc_json()
    data = ps._read_json(f)
    lsp = data.setdefault("lsp", {})
    cur = lsp.setdefault(lid, {})
    if on:
        cur.pop("disabled", None)
    else:
        cur["disabled"] = True
    if not cur:
        lsp.pop(lid, None)
    if not lsp:
        data.pop("lsp", None)
    ps._write_json(f, data)


def lsp_list(providers: set[str] | None = None) -> list[Tool]:
    out: list[Tool] = []
    if providers is None or "claude" in providers:
        out += lsp_claude()
    if providers is None or "opencode" in providers:
        out += lsp_opencode()
    return out


# ── CLI ───────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "mcp"
    if cmd in ("mcp", "lsp"):
        for t in (mcp_list() if cmd == "mcp" else lsp_list()):
            mode = t.toggle or "read-only"
            print(f"{t.provider:9} {'on ' if t.on else 'off'} {t.name:28} {t.origin:22} {mode:18} {t.desc[:60]}"
                  + (f"  ⚠ {t.warn}" if t.warn else ""))
    elif cmd == "health":
        print(json.dumps(check_health(), indent=2, ensure_ascii=False))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
