#!/usr/bin/env python3
"""Skills y agentes propios de cada proveedor (los que trae o preconfigura cada uno).

Backend sin Textual. Al activar un proveedor en Settings → AI Agents → Providers, sus carpetas
nativas se detectan y sus skills/agentes entran a los paneles Skills y Agents, para verlos y
apagarlos con el mecanismo PROPIO de cada proveedor (nunca borrando archivos):

  proveedor   qué se detecta                                     cómo se apaga
  ----------  -------------------------------------------------  ---------------------------------------
  claude      sync de claude.ai, plugins (instalados y           plugin: `enabledPlugins` de
              sincronizados), skills y agentes sueltos           ~/.claude/settings.json (todo el plugin).
                                                                 Sync de claude.ai y sueltos: solo lectura.
  opencode    ~/.config/opencode/skills, la skill integrada,     `opencode.json` hermano del jsonc:
              agentes propios (build, plan, general, explore)    permission.skill.<n> = "deny" /
                                                                 agent.<n>.disable = true (se fusiona
                                                                 con opencode.jsonc, que no se toca).
  codex       ~/.agents/skills, ~/.codex/skills y las de         [[skills.config]] enabled = false en
              sistema (.system)                                  ~/.codex/config.toml
  antigravity (nada)                                             sin mecanismo por skill conocido

Todo lo que se escribe va con temporal + os.replace. Variables para probar sobre copias:
CLAUDE_HOME, OPENCODE_DIR, CODEX_HOME, AGENTS_SKILLS_HOME, AGENTS_CACHE.

Uso: provider_sources.py list [proveedor…] | sources
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_skills as sk  # noqa: E402

HOME = Path.home()
CLAUDE_HOME = sk.CLAUDE_HOME
OPENCODE_DIR = sk.OPENCODE_DIR
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
AGENTS_SKILLS_HOME = Path(os.environ.get("AGENTS_SKILLS_HOME", HOME / ".agents" / "skills"))
CACHE_DIR = Path(os.environ.get("AGENTS_CACHE", Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "agents"))
USER_BIN_DIRS = [HOME / ".local" / "bin", HOME / ".opencode" / "bin", HOME / ".bun" / "bin", HOME / ".cargo" / "bin"]


def _opencode_bin() -> str | None:
    """Ruta de opencode (el PATH de Hyprland no trae las carpetas por usuario)."""
    if os.environ.get("OPENCODE_BIN"):
        return os.environ["OPENCODE_BIN"]
    found = shutil.which("opencode")
    if found:
        return found
    for d in USER_BIN_DIRS:
        f = d / "opencode"
        if f.is_file() and os.access(f, os.X_OK):
            return str(f)
    return None

PROVIDER_IDS = ("claude", "opencode", "codex", "antigravity")
COLLAPSE_OVER = 30     # un plugin con más skills que esto va en una sola fila

OPENCODE_AGENTS = {    # agentes que trae opencode (los internos compaction/summary/title no se muestran)
    "build": "Default agent: full tool access, for development work",
    "plan": "Read-only planning agent: analysis without editing files",
    "general": "General-purpose subagent for research and multi-step tasks",
    "explore": "Fast read-only subagent for exploring codebases",
}


@dataclass
class Item:
    provider: str
    kind: str            # "skill" | "agent"
    name: str
    desc: str
    origin: str          # texto corto de dónde sale ("claude.ai sync", "plugin foo", "built-in"…)
    on: bool = True
    toggle: str = ""     # "" = solo lectura | claude-plugin | opencode-skill | opencode-agent | codex-skill
    ref: str = ""        # con qué se apaga: clave del plugin, nombre, ruta de SKILL.md
    why: str = ""        # por qué es de solo lectura

    @property
    def key(self) -> str:
        return f"{self.provider}|{self.kind}|{self.name}|{self.ref}"


# ── escritura atómica de JSON / texto ─────────────────────

def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    try:
        tmp.chmod(path.stat().st_mode)
    except OSError:
        pass
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    """Objeto JSON del archivo ({} si no existe). ValueError si no es JSON puro (ej. con comentarios)."""
    try:
        text = path.read_text()
    except OSError:
        return {}
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return data


def _write_json(path: Path, data: dict) -> None:
    _write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ── Claude Code ───────────────────────────────────────────

def _claude_plugins() -> list[tuple[str, str, Path, bool]]:
    """(clave `nombre@marketplace`, nombre, carpeta, habilitado) de los plugins instalados."""
    try:
        inst = json.loads((CLAUDE_HOME / "plugins" / "installed_plugins.json").read_text())["plugins"]
    except (OSError, ValueError, KeyError):
        return []
    try:
        enabled = json.loads((CLAUDE_HOME / "settings.json").read_text()).get("enabledPlugins", {})
    except (OSError, ValueError):
        enabled = {}
    return [(key, key.split("@")[0], Path(e[0]["installPath"]), bool(enabled.get(key, False)))
            for key, e in inst.items() if e]


def discover_claude() -> list[Item]:
    out: list[Item] = []
    sync_why = "synced from your claude.ai account: manage it there"
    for md in sorted((CLAUDE_HOME / "skills" / "synced").glob("*/*/SKILL.md")):
        out.append(Item("claude", "skill", md.parent.name, sk.parse_frontmatter(md).get("description", ""),
                        "claude.ai sync", why=sync_why))
    for md in sorted((CLAUDE_HOME / "plugins" / "synced").glob("*/*/skills/*/SKILL.md")):
        out.append(Item("claude", "skill", f"{md.parents[2].name}:{md.parent.name}",
                        sk.parse_frontmatter(md).get("description", ""), "synced plugin", why=sync_why))
    for key, name, path, on in _claude_plugins():
        skills = sorted(path.glob("skills/*/SKILL.md"))
        agents = sorted(path.glob("agents/*.md"))
        if len(skills) > COLLAPSE_OVER or (not on and skills):
            # deshabilitado (no carga nada) o enorme: una sola fila
            out.append(Item("claude", "skill", f"{name} (plugin)",
                            f"{len(skills)} skills · {'enabled' if on else 'disabled in settings.json'}",
                            f"plugin {name}", on, "claude-plugin", key))
        else:
            for md in skills:
                out.append(Item("claude", "skill", f"{name}:{md.parent.name}",
                                sk.parse_frontmatter(md).get("description", ""), f"plugin {name}", on,
                                "claude-plugin", key))
        for md in agents:
            out.append(Item("claude", "agent", f"{name}:{md.stem}", sk.parse_frontmatter(md).get("description", ""),
                            f"plugin {name}", on, "claude-plugin", key))
    # agentes sueltos de ~/.claude/agents (los symlinks de skills.conf son de la otra mitad del gestor)
    try:
        loose = sorted((CLAUDE_HOME / "agents").glob("*.md"))
    except OSError:
        loose = []
    for md in loose:
        if not sk.is_ours(md):
            out.append(Item("claude", "agent", md.stem, sk.parse_frontmatter(md).get("description", ""),
                            "~/.claude/agents", why="a loose file in ~/.claude/agents: move or delete it"))
    # skills sueltas de ~/.claude/skills (ni nuestros symlinks ni el sync)
    try:
        entries = sorted((CLAUDE_HOME / "skills").iterdir())
    except OSError:
        entries = []
    for e in entries:
        if e.name in ("synced",) or e.name.startswith(".") or not (e / "SKILL.md").is_file():
            continue
        if not sk.is_ours(e):
            out.append(Item("claude", "skill", e.name, sk.parse_frontmatter(e / "SKILL.md").get("description", ""),
                            "~/.claude/skills", why="a local skill in ~/.claude/skills: move or delete it"))
    return out


def set_claude_plugin(key: str, on: bool) -> None:
    f = CLAUDE_HOME / "settings.json"
    data = _read_json(f)
    data.setdefault("enabledPlugins", {})[key] = on
    _write_json(f, data)


# ── opencode ──────────────────────────────────────────────

BUILTIN_CACHE = CACHE_DIR / "opencode-builtin.json"


def opencode_builtin(refresh: bool = False) -> list[tuple[str, str]]:
    """Skills integradas de opencode (nombre, descripción). `opencode debug skill` tarda unos segundos:
    la UI solo lee el cache (refresh=False) y lo rellena en un hilo con refresh=True."""
    try:
        cached = json.loads(BUILTIN_CACHE.read_text())
    except (OSError, ValueError):
        cached = None
    if not refresh:
        return [tuple(x) for x in cached["skills"]] if cached else []
    exe = _opencode_bin()
    if not exe:
        return [tuple(x) for x in cached["skills"]] if cached else []
    # opencode corta la salida a ~64 KB cuando va a un pipe: se redirige a un archivo
    tmp = CACHE_DIR / ".opencode-skills.tmp"
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as out:
            subprocess.run([exe, "debug", "skill"], stdout=out, stderr=subprocess.DEVNULL, timeout=60, check=False)
        txt = tmp.read_text()
        data = json.loads(txt[txt.index("["):txt.rindex("]") + 1])
    except (OSError, ValueError, subprocess.SubprocessError):
        return [tuple(x) for x in cached["skills"]] if cached else []
    finally:
        tmp.unlink(missing_ok=True)
    skills = [(x["name"], x.get("description", "")) for x in data if str(x.get("location", "")).startswith("<")]
    _write_text(BUILTIN_CACHE, json.dumps({"skills": skills}, ensure_ascii=False) + "\n")
    return skills


def _opencode_json() -> Path:
    return OPENCODE_DIR / "opencode.json"


def discover_opencode() -> list[Item]:
    out: list[Item] = []
    try:
        conf = _read_json(_opencode_json())
    except ValueError:
        conf = {}
    denied = {n for n, v in (conf.get("permission", {}).get("skill", {}) or {}).items() if v == "deny"}
    disabled = {n for n, v in (conf.get("agent", {}) or {}).items() if isinstance(v, dict) and v.get("disable")}
    for md in sorted((OPENCODE_DIR / "skills").glob("*/SKILL.md")):
        out.append(Item("opencode", "skill", md.parent.name, sk.parse_frontmatter(md).get("description", ""),
                        "~/.config/opencode/skills", md.parent.name not in denied, "opencode-skill", md.parent.name))
    for name, desc in opencode_builtin():
        out.append(Item("opencode", "skill", name, desc, "built-in", name not in denied, "opencode-skill", name))
    for name, desc in OPENCODE_AGENTS.items():
        out.append(Item("opencode", "agent", name, desc, "built-in", name not in disabled, "opencode-agent", name))
    try:
        files = sorted((OPENCODE_DIR / "agents").glob("*.md"))
    except OSError:
        files = []
    for md in files:                                        # archivos propios (los symlinks son de skills.conf)
        if not md.is_symlink():
            out.append(Item("opencode", "agent", md.stem, sk.parse_frontmatter(md).get("description", ""),
                            "~/.config/opencode/agents", md.stem not in disabled, "opencode-agent", md.stem))
    return out


def set_opencode(kind: str, name: str, on: bool) -> None:
    """Escribe en opencode.json (hermano de opencode.jsonc, que opencode fusiona y no se toca)."""
    f = _opencode_json()
    data = _read_json(f)                                    # ValueError si tiene comentarios: no pisarlo
    if kind == "skill":
        perm = data.setdefault("permission", {})
        sec = perm.setdefault("skill", {})
        if on:
            sec.pop(name, None)
        else:
            sec[name] = "deny"
        if not sec:
            perm.pop("skill", None)
        if not perm:
            data.pop("permission", None)
    else:
        ag = data.setdefault("agent", {})
        cur = ag.setdefault(name, {})
        if on:
            cur.pop("disable", None)
        else:
            cur["disable"] = True
        if not cur:
            ag.pop(name, None)
        if not ag:
            data.pop("agent", None)
    _write_json(f, data)


# ── Codex ─────────────────────────────────────────────────

def _codex_config() -> Path:
    return CODEX_HOME / "config.toml"


def _codex_disabled() -> set[str]:
    try:
        cfg = tomllib.loads(_codex_config().read_text())
    except (OSError, ValueError):
        return set()
    entries = (cfg.get("skills", {}) or {}).get("config", []) or []
    return {str(e.get("path")) for e in entries if isinstance(e, dict) and e.get("enabled") is False}


def discover_codex() -> list[Item]:
    off = _codex_disabled()
    out: list[Item] = []
    for base, origin in ((AGENTS_SKILLS_HOME, "~/.agents/skills"), (CODEX_HOME / "skills", "~/.codex/skills"),
                         (CODEX_HOME / "skills" / ".system", "system")):
        try:
            mds = sorted(base.glob("*/SKILL.md"))
        except OSError:
            continue
        for md in mds:
            out.append(Item("codex", "skill", md.parent.name, sk.parse_frontmatter(md).get("description", ""),
                            origin, str(md) not in off, "codex-skill", str(md)))
    return out


def set_codex_skill(path: str, on: bool) -> None:
    """[[skills.config]] path = "…" / enabled = false en config.toml; al prender se quita el bloque."""
    f = _codex_config()
    try:
        text = f.read_text()
    except OSError:
        text = ""
    parts = re.split(r"(?m)^(?=\[\[skills\.config\]\]\s*$)", text)
    head, blocks = parts[0], parts[1:]
    quoted = json.dumps(path)
    kept, found = [], False
    for b in blocks:
        m = re.search(r'(?m)^path\s*=\s*(".*?"|\'.*?\')\s*$', b)
        if m and m.group(1).strip("\"'") == path:
            found = True
            if on:
                continue                                      # prender = sacar el bloque
            b = re.sub(r"(?m)^enabled\s*=.*$", "enabled = false", b) if "enabled" in b else \
                b.rstrip("\n") + "\nenabled = false\n"
        kept.append(b)
    if not on and not found:
        kept.append(f"[[skills.config]]\npath = {quoted}\nenabled = false\n")
    body = [x.strip("\n") for x in ([head] if head.strip() else []) + kept]
    new = "\n\n".join(body) + "\n" if body else ""
    _write_text(f, new)


# ── API común ─────────────────────────────────────────────

ADAPTERS = {"claude": discover_claude, "opencode": discover_opencode, "codex": discover_codex,
            "antigravity": lambda: []}


def discover(providers: set[str] | None = None) -> list[Item]:
    """Skills y agentes propios de los proveedores activos (todos si providers=None)."""
    ids = PROVIDER_IDS if providers is None else [p for p in PROVIDER_IDS if p in providers]
    out: list[Item] = []
    for p in ids:
        out += ADAPTERS[p]()
    return out


def set_enabled(item: Item, on: bool) -> str | None:
    """Prende/apaga con el mecanismo del proveedor. Devuelve un mensaje de error o None."""
    if not item.toggle:
        return f"{item.name}: {item.why or 'read-only'}"
    try:
        if item.toggle == "claude-plugin":
            set_claude_plugin(item.ref, on)
        elif item.toggle == "opencode-skill":
            set_opencode("skill", item.ref, on)
        elif item.toggle == "opencode-agent":
            set_opencode("agent", item.ref, on)
        elif item.toggle == "codex-skill":
            set_codex_skill(item.ref, on)
    except (OSError, ValueError) as e:
        return f"could not change {item.name}: {e}"
    return None


def sources(providers: set[str] | None = None) -> list[tuple[str, Path, str, int, int, str]]:
    """Carpetas que se leen por proveedor: (proveedor, ruta, tipo, skills, agentes, estado on|off).
    Es lo que muestra el popup de carpetas en solo lectura."""
    ids = PROVIDER_IDS if providers is None else [p for p in PROVIDER_IDS if p in providers]
    out: list[tuple[str, Path, str, int, int, str]] = []
    if "claude" in ids:
        for b in sorted((CLAUDE_HOME / "skills" / "synced").glob("*/")):
            n = len(list(b.glob("*/SKILL.md")))
            if n:
                out.append(("claude", b, "claude.ai sync", n, 0, "on"))
        for b in sorted((CLAUDE_HOME / "plugins" / "synced").glob("*/*/")):
            n = len(list(b.glob("skills/*/SKILL.md")))
            if n:
                out.append(("claude", b, "synced plugin", n, 0, "on"))
        for _k, name, path, on in _claude_plugins():
            out.append(("claude", path, f"plugin {name}", len(list(path.glob("skills/*/SKILL.md"))),
                        len(list(path.glob("agents/*.md"))), "on" if on else "off"))
    if "opencode" in ids:
        n = len(list((OPENCODE_DIR / "skills").glob("*/SKILL.md")))
        out.append(("opencode", OPENCODE_DIR, "opencode", n + len(opencode_builtin()), len(OPENCODE_AGENTS), "on"))
    if "codex" in ids:
        for base, kind in ((AGENTS_SKILLS_HOME, "agents skills"), (CODEX_HOME / "skills", "codex skills")):
            n = len(list(base.glob("*/SKILL.md"))) if base.is_dir() else 0
            if n:
                out.append(("codex", base, kind, n, 0, "on"))
    return out


# ── CLI ───────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "list"
    ids = set(argv[2:]) or None
    if cmd == "list":
        for it in discover(ids):
            mode = it.toggle or "read-only"
            print(f"{it.provider:11} {it.kind:5} {'on ' if it.on else 'off'} {it.name:44} {it.origin:26} {mode}")
    elif cmd == "sources":
        for prov, path, kind, ns, na, st in sources(ids):
            print(f"{prov:11} {kind:18} {ns:4} skills {na:3} agents {st:3} {path}")
    elif cmd == "refresh-builtin":
        print(len(opencode_builtin(refresh=True)), "built-in opencode skills cached")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
