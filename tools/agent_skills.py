#!/usr/bin/env python3
"""Skills de agentes: carpetas de origen + cuáles se cargan (Claude Code y opencode).

Backend sin Textual (lo usa la vista de Settings → AI Agents).

Config de usuario `~/.config/dotfiles/skills.conf` (ver skills.conf.example):

    dir=~/agent-skills       # una o más; la primera tiene prioridad (sin ninguna, no hay carpetas propias)
    off=some-skill           # skills desactivadas (las nuevas nacen activas)
    agent_off=some-agent     # agentes desactivados (los nuevos nacen activos)

Cada carpeta aporta lo que tenga en `SKILLS/<nombre>/SKILL.md` (o `skills/`), `AGENTS-CLAUDE-CODE/*.md`
(formato Claude Code) y `AGENTS/*.md` (formato opencode). Un agente se identifica por su nombre
de archivo y la selección vale para los dos formatos. `apply()` deja el sistema igual a la config:

  - ~/.claude/skills/<nombre>  → symlink a la skill activa (opencode también lee ahí,
    así que una sola selección vale para los dos).
  - ~/.claude/agents/<n>.md    → symlink al agente activo de AGENTS-CLAUDE-CODE/.
  - ~/.config/opencode/agents/ → carpeta generada con un symlink por agente activo de AGENTS/.
  - opencode.jsonc             → sin `skills.paths` (si no, opencode vería todas las skills).

Lo que cada proveedor trae por su cuenta (sync de claude.ai, plugins, skills integradas…) lo
detecta y apaga `provider_sources.py`.

Todo se reemplaza con temporal + os.replace: nunca hay un instante con un link roto
(puede haber sesiones abiertas). Solo se tocan symlinks "gestionados" (cuyo destino cuelga
de una carpeta configurada o conocida); entradas reales (`synced/`) no.

Variables de entorno para probar sobre copias: AGENT_SKILLS_CONF, CLAUDE_HOME, OPENCODE_DIR.

Uso: agent_skills.py dir | list | agents | status | apply
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
CONF = Path(os.environ.get("AGENT_SKILLS_CONF") or CONFIG_HOME / "dotfiles" / "skills.conf")
CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")
# ~/.config/opencode es una carpeta real (solo se enlaza su opencode.jsonc generado)
OPENCODE_DIR = Path(os.environ.get("OPENCODE_DIR") or CONFIG_HOME / "opencode")
STATE_FILE = Path(os.environ.get("AGENT_SKILLS_STATE") or STATE_HOME / "dotfiles" / "agent-skills.json")

HEADER = """\
# Skills de agentes (Claude Code y opencode). Se cambian desde Settings → AI Agents.
#   dir=<carpeta>   carpeta con SKILLS/ (y AGENTS/, AGENTS-CLAUDE-CODE/); la primera tiene prioridad
#   off=<skill>     skill desactivada (no se enlaza en ~/.claude/skills)
#   agent_off=<n>   agente desactivado (no se enlaza en ~/.claude/agents ni opencode/agents)
"""


# ── skills.conf ───────────────────────────────────────────

def _expand(p: str) -> str:
    return os.path.expanduser(p.strip()).rstrip("/") or "/"


def _read_conf_all() -> tuple[list[str], set[str], set[str]]:
    """(carpetas en orden de prioridad, skills desactivadas). Sin archivo: ninguna carpeta."""
    dirs: list[str] = []
    off: set[str] = set()
    agent_off: set[str] = set()
    try:
        lines = CONF.read_text().splitlines()
    except OSError:
        return [], off, agent_off
    for line in lines:
        line = line.split("#", 1)[0].strip()
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k == "dir" and v and _expand(v) not in dirs:
            dirs.append(_expand(v))
        elif k == "off" and v:
            off.add(v)
        elif k == "agent_off" and v:
            agent_off.add(v)
    return dirs, off, agent_off


def read_conf() -> tuple[list[str], set[str]]:
    """(carpetas en orden de prioridad, skills desactivadas). Sin archivo: ninguna carpeta."""
    d, o, _ = _read_conf_all()
    return d, o


def read_agent_off() -> set[str]:
    """Agentes desactivados."""
    return _read_conf_all()[2]


def write_conf(dirs: list[str], off: set[str], agent_off: set[str] | None = None) -> None:
    """Reescribe la config (temporal + os.replace). Conserva el encabezado de comentarios.
    `agent_off=None` conserva los agentes desactivados que ya había."""
    if agent_off is None:
        agent_off = read_agent_off()
    try:
        old = CONF.read_text().splitlines()
        head = []
        for l in old:
            if l.startswith("#") or not l.strip():
                head.append(l)
            else:
                break
        header = "\n".join(head).rstrip("\n") + "\n" if head else HEADER
    except OSError:
        header = HEADER
    body = ("".join(f"dir={d}\n" for d in dirs) + "".join(f"off={s}\n" for s in sorted(off))
            + "".join(f"agent_off={a}\n" for a in sorted(agent_off)))
    CONF.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONF.with_name(f".{CONF.name}.tmp")
    tmp.write_text(header + "\n" + body)
    os.replace(tmp, CONF)


def first_dir() -> str:
    dirs, _ = read_conf()
    return dirs[0] if dirs else ""


def sub(root: str | Path, name: str) -> Path:
    """Subcarpeta `name` de una carpeta de skills sin distinguir mayúsculas (SKILLS/skills, AGENTS/agents…)."""
    base = Path(root)
    try:
        for e in base.iterdir():
            if e.name.lower() == name.lower() and e.is_dir():
                return e
    except OSError:
        pass
    return base / name


# ── escaneo ───────────────────────────────────────────────

@dataclass
class Skill:
    name: str              # nombre de la carpeta (= nombre del symlink)
    desc: str              # descripción del frontmatter ("" si no hay)
    root: str              # carpeta de origen (la de skills.conf)
    path: Path             # <root>/SKILLS/<name>
    shadowed_by: str = ""  # carpeta anterior que ya trae una skill con el mismo nombre
    valid: bool = True     # frontmatter con name+description (si no, la UI avisa; igual se enlaza)


def parse_frontmatter(skill_md: Path) -> dict[str, str]:
    """name/description del frontmatter. Soporta `description: >`/`|` en varias líneas."""
    try:
        lines = skill_md.read_text(errors="replace").splitlines()
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    key, buf = "", []

    def flush() -> None:
        if key:
            out[key] = " ".join(x.strip() for x in buf if x.strip())
    for l in lines[1:]:
        if l.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", l)
        if m and not l.startswith((" ", "\t")):
            flush()
            key, v = m.group(1), m.group(2).strip()
            buf = [] if v in (">", "|", ">-", "|-") else [v.strip("\"'")]
        elif key:
            buf.append(l)
    flush()
    return out


def scan(dirs: list[str]) -> list[Skill]:
    """Skills de todas las carpetas; ordenadas por nombre. Gana la primera carpeta."""
    seen: dict[str, str] = {}
    found: list[Skill] = []
    for root in dirs:
        base = sub(root, "SKILLS")
        try:
            entries = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            continue
        for p in entries:
            fm = parse_frontmatter(p / "SKILL.md")
            sk = Skill(p.name, fm.get("description", ""), root, p,
                       shadowed_by=seen.get(p.name, ""), valid=bool(fm.get("name") and fm.get("description")))
            seen.setdefault(p.name, root)
            found.append(sk)
    return sorted(found, key=lambda s: (s.name.lower(), s.shadowed_by != ""))


def active_skills(dirs: list[str], off: set[str]) -> dict[str, Skill]:
    """Skills que se enlazan: primera ocurrencia de cada nombre, sin las `off`."""
    return {s.name: s for s in scan(dirs) if not s.shadowed_by and s.name not in off}


def validate_dir(path: str) -> str | None:
    """Mensaje de error si la carpeta no sirve como origen de skills."""
    p = Path(_expand(path))
    if not p.is_dir():
        return "folder does not exist"
    if not sub(p, "SKILLS").is_dir():
        return "no SKILLS/ subfolder inside"
    return None


@dataclass
class Agent:
    name: str                 # nombre del archivo sin .md (= nombre del symlink)
    desc: str
    root: str                 # primera carpeta que lo trae
    claude: Path | None = None    # AGENTS-CLAUDE-CODE/<name>.md (primera carpeta que lo tenga)
    opencode: Path | None = None  # AGENTS/<name>.md

    @property
    def formats(self) -> str:
        return " ".join(f for f, p in (("claude", self.claude), ("opencode", self.opencode)) if p)


def scan_agents(dirs: list[str]) -> list[Agent]:
    """Agentes de todas las carpetas, uno por nombre (cada formato: gana la primera carpeta)."""
    found: dict[str, Agent] = {}
    for root in dirs:
        for subname, attr in (("AGENTS-CLAUDE-CODE", "claude"), ("AGENTS", "opencode")):
            try:
                files = sorted(sub(root, subname).glob("*.md"))
            except OSError:
                continue
            for f in files:
                a = found.get(f.stem)
                if a is None:
                    a = found[f.stem] = Agent(f.stem, parse_frontmatter(f).get("description", ""), root)
                if getattr(a, attr) is None:
                    setattr(a, attr, f)
                    if not a.desc:
                        a.desc = parse_frontmatter(f).get("description", "")
    return sorted(found.values(), key=lambda a: a.name.lower())


# ── symlinks ──────────────────────────────────────────────

def _set_link(link: Path, target: Path) -> bool:
    """Deja `link` → `target` (atómico). True si cambió algo."""
    try:
        if link.is_symlink() and Path(os.readlink(link)) == target:
            return False
    except OSError:
        pass
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.with_name(f".{link.name}.tmp")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    os.symlink(target, tmp)
    os.replace(tmp, link)
    return True


def _known_roots() -> set[str]:
    """Carpetas de skills de ahora y de antes (para reconocer los symlinks de una carpeta ya quitada)."""
    roots = set(read_conf()[0])
    try:
        roots |= set(json.loads(STATE_FILE.read_text()).get("roots", []))
    except (OSError, ValueError):
        pass
    return roots


def _remember_roots(dirs: list[str]) -> None:
    known = _known_roots() | set(dirs)
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_name(f".{STATE_FILE.name}.tmp")
        tmp.write_text(json.dumps({"roots": sorted(known)}, indent=2) + "\n")
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def is_ours(link: Path, roots: set[str] | None = None) -> bool:
    """¿Es un symlink de este gestor? Su destino está adentro de una carpeta configurada o conocida.
    Un symlink ajeno (a otro lado, aunque tenga `/skills/` en la ruta) nunca se toca."""
    if not link.is_symlink():
        return False
    tgt = os.path.normpath(os.path.join(link.parent, os.readlink(link)))
    return any(tgt.startswith(r.rstrip("/") + "/") for r in (roots if roots is not None else _known_roots()))


def _sync_dir(folder: Path, want: dict[str, Path], roots: set[str]) -> tuple[int, int]:
    """Deja en `folder` exactamente los symlinks `want` (más lo ajeno que no es nuestro).
    Devuelve (creados/repuntados, borrados)."""
    changed = removed = 0
    for name, target in want.items():
        if _set_link(folder / name, target):
            changed += 1
    try:
        entries = list(folder.iterdir())
    except OSError:
        entries = []
    for e in entries:
        if e.name.startswith(".") or e.name in want:
            continue
        if is_ours(e, roots):
            e.unlink()
            removed += 1
    return changed, removed


# ── opencode.jsonc ────────────────────────────────────────

_SKILLS_PATHS = re.compile(r'\n[ \t]*"skills"\s*:\s*\{\s*"paths"\s*:\s*\[[^\]]*\]\s*,?\s*\}\s*,?[ \t]*(?=\n)')


def clean_opencode_paths() -> bool:
    """Saca `skills.paths` de opencode.jsonc (opencode lee ~/.claude/skills por su cuenta).
    True si lo cambió. Si el bloque no tiene la forma esperada, no toca nada."""
    f = OPENCODE_DIR / "opencode.jsonc"
    if f.is_symlink():            # generado en otro lado (D4rkFiles): no se toca
        return False
    try:
        text = f.read_text()
    except OSError:
        return False
    new, n = _SKILLS_PATHS.subn("", text, count=1)
    if not n:
        return False
    tmp = f.with_name(f".{f.name}.tmp")
    tmp.write_text(new)
    tmp.chmod(f.stat().st_mode)
    os.replace(tmp, f)
    return True


# ── apply / status ────────────────────────────────────────

def apply() -> dict:
    """Aplica la config al sistema. Devuelve un resumen para mostrar."""
    dirs, off, agent_off = _read_conf_all()
    _remember_roots(dirs)
    roots = _known_roots()
    act = active_skills(dirs, off)
    res = {"skills": len(act), "linked": 0, "unlinked": 0, "agents": 0, "opencode": False}

    ch, rm = _sync_dir(CLAUDE_HOME / "skills", {n: s.path for n, s in act.items()}, roots)
    res["linked"], res["unlinked"] = ch, rm

    agents = [a for a in scan_agents(dirs) if a.name not in agent_off]
    ch, rm = _sync_dir(CLAUDE_HOME / "agents", {f"{a.name}.md": a.claude for a in agents if a.claude},
                       roots)
    res["agents"] = ch + rm

    # opencode/agents: antes era un symlink a AGENTS/; ahora es una carpeta con un symlink por agente
    oa = OPENCODE_DIR / "agents"
    if oa.is_symlink():
        oa.unlink()
    oa.mkdir(parents=True, exist_ok=True)
    ch, rm = _sync_dir(oa, {f"{a.name}.md": a.opencode for a in agents if a.opencode}, roots)
    res["agents"] += ch + rm
    res["opencode"] = clean_opencode_paths()
    return res


def status() -> dict:
    """Estado actual vs config (sin escribir nada)."""
    dirs, off = read_conf()
    act = active_skills(dirs, off)
    sk = CLAUDE_HOME / "skills"
    ok = bad = 0
    for n, s in act.items():
        l = sk / n
        if l.is_symlink() and Path(os.readlink(l)) == s.path and l.exists():
            ok += 1
        else:
            bad += 1
    ag_off = read_agent_off()
    ag = [a for a in scan_agents(dirs) if a.name not in ag_off and a.claude]
    ag_ok = sum(1 for a in ag if (CLAUDE_HOME / "agents" / f"{a.name}.md").is_symlink()
                and Path(os.readlink(CLAUDE_HOME / "agents" / f"{a.name}.md")) == a.claude)
    return {"dirs": dirs, "off": sorted(off), "active": len(act), "synced": ok, "pending": bad,
            "agent_off": sorted(ag_off), "agents_active": len(ag), "agents_synced": ag_ok}


# ── CLI ───────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "dir":
        print(first_dir())
    elif cmd == "list":
        dirs, off = read_conf()
        for s in scan(dirs):
            mark = "shadowed" if s.shadowed_by else ("off" if s.name in off else "on")
            print(f"{mark:9} {s.name:34} {s.root}")
    elif cmd == "agents":
        dirs, _ = read_conf()
        off = read_agent_off()
        for a in scan_agents(dirs):
            print(f"{'off' if a.name in off else 'on':4} {a.name:16} {a.formats:16} {a.root}")
    elif cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif cmd == "apply":
        print(json.dumps(apply(), ensure_ascii=False))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
