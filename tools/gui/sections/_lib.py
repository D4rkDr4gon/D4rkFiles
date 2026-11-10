"""
_lib.py — piezas comunes de los módulos de sección de la GUI.

Cada tools/gui/sections/<id>.py expone:
    get() -> dict                       página: page(titulo, subtitulo, [group(...)], refresh=seg)
    set_value(key, value) -> dict|None  cambia un toggle/choice/slider (devuelve {"msg": ...} opcional)
    act(key, text=None) -> dict|None    ejecuta un botón/item; {"msg": ..} y/o {"ask": {...}} para pedir texto
La GUI (quickshell/SectionPage.qml) dibuja el resultado; los backends no saben de QML.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path

# Rutas del repo y del usuario (mismas convenciones que tools/settings/sections/common.py)
TOOLS = Path(__file__).resolve().parents[2]                              # tools/
DOTFILES = Path(os.environ.get("DOTFILES_DIR") or TOOLS.parent)          # raíz del repo
CONFIG = DOTFILES / "config"
SETTINGS_DIR = TOOLS / "settings"
SETTINGS_SRC = SETTINGS_DIR / "settings_tui.py"
CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dotfiles"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "dotfiles"
CURRENT_THEME = STATE_DIR / "current_theme.json"


def run(cmd: list[str], timeout: int = 10, **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def detach(cmd: list[str]) -> None:
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def literal(name: str, src: Path = SETTINGS_SRC):
    """Constante literal de un .py sin importarlo (la TUI carga Textual al importarse)."""
    tree = ast.parse(src.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


# ── constructores de filas ────────────────────────────────

def page(title: str, subtitle: str, groups: list, refresh: int = 0) -> dict:
    return {"title": title, "subtitle": subtitle, "groups": groups, "refresh": refresh * 1000}


def group(name: str, rows: list) -> dict:
    return {"name": name, "rows": rows}


def _row(kind: str, key: str, name: str, desc: str = "", **kw) -> dict:
    return {"kind": kind, "key": key, "name": name, "desc": desc, **kw}


def toggle(key, name, desc, value, **kw):
    return _row("toggle", key, name, desc, value=bool(value), **kw)


def choice(key, name, desc, value, options, **kw):
    return _row("choice", key, name, desc, value=value, options=list(options), **kw)


def slider(key, name, desc, value, lo, hi, step=1, **kw):
    return _row("slider", key, name, desc, value=value, lo=lo, hi=hi, step=step, **kw)


def button(key, name, desc, label, danger=False, **kw):
    return _row("button", key, name, desc, label=label, danger=danger, **kw)


def info(key, name, value, desc=""):
    return _row("info", key, name, desc, value=value)


def item(key, label, sub="", right="", glyph="", image="", on=False, actions=None, color=""):
    """color: muestra de color (#rrggbb) en lugar del glifo."""
    return {"kind": "item", "key": key, "label": label, "sub": sub, "right": right, "glyph": glyph,
            "image": image, "on": on, "actions": actions or [], "color": color}


def action(key: str, label: str, danger: bool = False) -> dict:
    return {"key": key, "label": label, "danger": danger}


def ok(msg: str = "") -> dict:
    return {"ok": True, "msg": msg}


def fail(msg: str) -> dict:
    return {"ok": False, "msg": msg}


def ask(key: str, label: str, secret: bool = False, text: str = "") -> dict:
    return {"ok": True, "ask": {"key": key, "label": label, "secret": secret, "text": text}}


def form(key: str, title: str, fields: list[dict], error: str = "", hint: str = "", ok_label: str = "") -> dict:
    """Formulario de varios campos: [{name, label, text, secret, choices}]; act(key, json) recibe {name: valor}.
    choices: strings o pares [etiqueta, valor]. Para revalidar, devolver el mismo form con error= y los valores cargados."""
    return {"ok": True, "ask": {"key": key, "title": title, "fields": fields, "error": error, "hint": hint,
                                "okLabel": ok_label}}


def parse_form(text) -> dict:
    try:
        return json.loads(text or "{}")
    except ValueError:
        return {}


def split_terse(line: str) -> list[str]:
    """`nmcli -t` separa con ':' y escapa los ':' internos como '\\:'."""
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ── helpers para módulos que reusan lo de Settings ───────

_common = None


def settings_common():
    """tools/settings/sections/common.py (hypr_block_get/set, hypr_apply…) sin chocar con el paquete `sections` de la GUI."""
    global _common
    if _common is None:
        import importlib.util
        import sys
        tui = str(TOOLS)
        if tui not in sys.path:
            sys.path.insert(0, tui)
        spec = importlib.util.spec_from_file_location("settings_common", SETTINGS_DIR / "sections" / "common.py")
        _common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_common)
    return _common


def field(key: str, name: str, desc: str, value: str, glyph: str = ""):
    """Fila de texto editable: al hacer click el módulo recibe act("edit:<key>") y responde con ask(..., text=valor)."""
    return item(f"edit:{key}", name, sub=desc, right=value or "—", glyph=glyph)


def tui_group(section_id: str, why: str = "Needs sudo or a terminal flow") -> dict:
    return group("More", [button(f"tui:{section_id}", "Open the TUI version", why, "Open")])


def open_tui(section_id: str) -> dict:
    """Abre esa sección de Settings en la TUI (GUI_FORCE_TUI evita volver al despachador) y cierra la ventana GUI."""
    detach(["env", "GUI_FORCE_TUI=1", str(Path.home() / ".config/waybar/scripts/center-tui-launch.sh"), "settings", "Settings",
            "python3", str(SETTINGS_SRC), "--section", section_id])
    return {"ok": True, "msg": "", "close": True}


# ── diálogos y vistas extra de SectionPage ───────────────

def terminal(argv: list[str], title: str, msg: str = "Continue in the terminal") -> dict:
    """Lo que la TUI corre con app.suspend() (sudo con contraseña, makepkg, logins): en una terminal suelta.
    Cierra la ventana GUI (es una capa overlay: taparía la terminal)."""
    detach(["kitty", "--class", "dotfiles-term", "--title", title, "sh", "-c",
            '"$@"; echo; read -p "(enter to close)" _', "sh", *argv])
    return {"ok": True, "msg": msg, "close": True}


def confirm(key: str, title: str, message: str = "", danger: bool = True, ok_label: str = "") -> dict:
    """Pide confirmación; si acepta llega act(key, "yes")."""
    return {"ok": True, "ask": {"key": key, "title": title, "message": message, "confirm": True, "danger": danger,
                                "okLabel": ok_label}}


def text_view(title: str, body: str, msg: str = "") -> dict:
    """Muestra un texto largo (diff, log, salida de un comando) en un visor desplazable."""
    return {"ok": True, "msg": msg, "text": {"title": title, "body": body}}


def yes(text) -> bool:
    return (text or "").strip().lower() == "yes"


# ── root sin terminal: helper rootd.py autorizado UNA vez con pkexec (huella) ──

import threading as _th

_root = {"p": None, "seq": 0}
_root_lock = _th.Lock()
ROOTD = TOOLS / "gui" / "rootd.py"


# Avisos sin pedido hacia la GUI ({"event": {...}} por stdout); bridge.py serve lo conecta.
EMIT = None


def emit(ev: dict) -> None:
    if EMIT is not None:
        try:
            EMIT(ev)
        except Exception:  # noqa: BLE001 - un aviso nunca rompe una acción
            pass


def _root_proc():
    p = _root["p"]
    if p is not None and p.poll() is None:
        return p
    # Mientras pkexec espera la huella/contraseña, la GUI se oculta: es una capa overlay con el
    # teclado tomado y taparía el diálogo de polkit (parecía trabada). Vuelve al terminar.
    emit({"auth": True})
    try:
        p = subprocess.Popen(["pkexec", "/usr/bin/python3", str(ROOTD)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, bufsize=1)
        first = p.stdout.readline()
    finally:
        emit({"auth": False})
    if '"ready"' not in first:
        p.kill()
        _root["p"] = None
        return None
    _root["p"] = p
    return p


def root_run(cmds: list[list[str]], input_text: str | None = None, timeout: int = 600, log: str | None = None) -> tuple[bool, str]:
    """Corre los comandos como root (en orden; frena en el primero que falla). Devuelve (ok, salida).
    La primera vez pide autorización con polkit (huella); después se reusa mientras viva la GUI."""
    out = []
    with _root_lock:
        p = _root_proc()
        if p is None:
            return False, "Authorization cancelled"
        for cmd in cmds:
            _root["seq"] += 1
            req = {"id": _root["seq"], "argv": [str(c) for c in cmd], "input": input_text, "timeout": timeout, "log": log}
            try:
                p.stdin.write(json.dumps(req) + "\n")
                p.stdin.flush()
                res = json.loads(p.stdout.readline() or "{}")
            except (OSError, ValueError):
                _root["p"] = None
                return False, "Root helper died"
            out.append((res.get("out") or "") + (res.get("err") or ""))
            if res.get("rc") != 0:
                return False, "\n".join(out).strip() or f"{cmd[0]} failed ({res.get('rc')})"
    return True, "\n".join(out).strip()


def root_ok(cmds: list[list[str]], ok_msg: str, **kw) -> dict:
    ok_, out = root_run(cmds, **kw)
    return ok(ok_msg) if ok_ else fail(out.splitlines()[-1][:160] if out else "Failed")


def root_file(content: str) -> str:
    """Temporal del usuario para instalarlo con root_run([["install", "-m644", tmp, "/etc/…"]])."""
    import os
    import time
    d = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "dotfiles-gui"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"root-{os.getpid()}-{time.monotonic_ns()}"
    f.write_text(content)
    return str(f)


def tui_module(name: str):
    """Módulo de una sección de la TUI (tools/settings/sections/<name>.py) para reusar su backend.
    Se carga como `tui_<name>`; sus imports (common, dtui, netzones…) se resuelven desde sus carpetas."""
    import importlib.util
    import sys
    key = f"tui_{name}"
    if key in sys.modules:
        return sys.modules[key]
    for d in (TOOLS, SETTINGS_DIR / "sections", SETTINGS_DIR):
        if str(d) not in sys.path:
            sys.path.append(str(d))
    spec = importlib.util.spec_from_file_location(key, SETTINGS_DIR / "sections" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


def unsafe_gate() -> bool:
    """Como common.unsafe_gate de la TUI: en una red insegura (netguard) pide autorización antes de
    conectar algo (USB, Bluetooth). Va por el helper root, así que no suma otro pedido de huella."""
    c = settings_common()
    if not c.network_unsafe():
        return True
    ngr = Path("/usr/local/lib/netguard/netguard-root")
    if not ngr.exists():
        return True
    return root_run([[str(ngr), "--via=auth", "check"]], timeout=60)[0]


# ── trabajos largos (actualizar, snapshots…): hilo + log que la página muestra en vivo ──

JOBS: dict = {}
ROOTSHIM = TOOLS / "gui" / "rootshim.py"


def _job_dir() -> Path:
    import os
    d = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "dotfiles-gui"
    d.mkdir(parents=True, exist_ok=True)
    return d


class _RootSocket:
    """Socket del usuario (0600) que deja a un proceso propio (yay) correr `pacman` como root a través
    del helper de la GUI: `yay --sudo rootshim.py`. Existe solo mientras dura el trabajo que lo pidió."""

    def __init__(self):
        import os
        import socket
        self.path = str(_job_dir() / f"root-{os.getpid()}.sock")
        try:
            os.unlink(self.path)
        except OSError:
            pass
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            self.s.bind(self.path)
        finally:
            os.umask(old)
        self.s.listen(4)
        self.alive = True
        _th.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while self.alive:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            _th.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        import os
        try:
            f = c.makefile("rw")
            req = json.loads(f.readline() or "{}")
            argv = req.get("argv") or []
            if not argv or os.path.basename(argv[0]) != "pacman":
                res = {"rc": 126, "out": "", "err": "only pacman goes through the GUI root helper"}
            else:
                ok_, out = root_run([argv], timeout=7200, log=req.get("log"))
                res = {"rc": 0 if ok_ else 1, "out": out}
            f.write(json.dumps(res) + "\n")
            f.flush()
        except (OSError, ValueError):
            pass
        finally:
            c.close()

    def close(self):
        import os
        self.alive = False
        try:
            self.s.close()
            os.unlink(self.path)
        except OSError:
            pass


def job_start(jid: str, title: str, steps: list, after=None) -> dict:
    """steps: [(kind, argv, etiqueta)] con kind "root" | "user" | "aur" (user con el sudo de la GUI) o
    (callable, etiqueta) que devuelve texto. Frena en el primero que falla. after(ok) al terminar."""
    import os
    import subprocess
    import time
    j = JOBS.get(jid)
    if j and j["running"]:
        return fail(f"{j['title']} is already running")
    log = _job_dir() / f"job-{jid}.log"
    log.write_text("")
    j = JOBS[jid] = {"title": title, "running": True, "ok": None, "log": str(log), "cur": "", "started": time.time(), "step": ""}

    def write(text: str):
        with open(log, "a") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")

    def work():
        ok_ = True
        sock = None
        try:
            for st in steps:
                if callable(st[0]):
                    j["step"] = st[1]
                    write(f"\n══ {st[1]} ══")
                    try:
                        write(str(st[0]() or ""))
                    except Exception as e:  # noqa: BLE001
                        write(f"✗ {e}")
                        ok_ = False
                        break
                    continue
                kind, argv, label = st
                j["step"] = label
                write(f"\n══ {label} ══\n$ {' '.join(argv)}")
                if kind == "root":
                    cur = _job_dir() / f"job-{jid}-step.log"
                    j["cur"] = str(cur)
                    ok_, out = root_run([argv], timeout=7200, log=str(cur))
                    try:
                        write(cur.read_text(errors="replace"))
                    except OSError:
                        pass
                    j["cur"] = ""
                    if out:
                        write(out)
                else:
                    env = dict(os.environ)
                    if kind == "aur":
                        sock = sock or _RootSocket()
                        env["DOTFILES_GUI_ROOTSOCK"] = sock.path
                        argv = [argv[0], "--sudo", str(ROOTSHIM), *argv[1:]]
                    with open(log, "a") as fh:
                        ok_ = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             env=env, timeout=7200).returncode == 0
                if not ok_:
                    write(f"✗ {label} failed")
                    break
        except Exception as e:  # noqa: BLE001
            write(f"✗ {e}")
            ok_ = False
        finally:
            if sock:
                sock.close()
        write("\n✓ Done" if ok_ else "\n✗ Stopped")
        j.update(running=False, ok=ok_, step="")
        if after:
            try:
                after(ok_)
            except Exception:  # noqa: BLE001
                pass

    _th.Thread(target=work, daemon=True).start()
    return ok(f"{title}: started")


def job_text(jid: str) -> str:
    j = JOBS.get(jid)
    if not j:
        return ""
    try:
        body = Path(j["log"]).read_text(errors="replace")
        if j.get("cur"):
            body += Path(j["cur"]).read_text(errors="replace")
    except OSError:
        body = ""
    return body


def job_group(jid: str) -> list:
    """Grupo "Running …" / "Last run" con la última línea y un botón para ver el log completo (act "log:<jid>")."""
    j = JOBS.get(jid)
    if not j:
        return []
    lines = [ln for ln in job_text(jid).splitlines() if ln.strip()]
    state = f"running · {j['step']}" if j["running"] else ("✓ finished" if j["ok"] else "✗ failed")
    return [group(("Running · " if j["running"] else "Last run · ") + j["title"], [
        info("jobstate", "State", state),
        info("jobline", "Output", (lines[-1] if lines else "…")[:140]),
        button(f"log:{jid}", "Full log", f"{len(lines)} lines", "Show")])]


def job_running(jid: str) -> bool:
    return bool(JOBS.get(jid, {}).get("running"))


def root_alive() -> bool:
    """¿El helper root ya está autorizado? (para leer cosas de root sin disparar la huella)."""
    p = _root["p"]
    return p is not None and p.poll() is None
