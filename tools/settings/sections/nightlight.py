"""Night light — hyprsunset (filtro de luz azul de Hyprland).

Lo usa Settings → Displays. La config es config/hypr/hyprsunset.conf (= ~/.config/
hypr/hyprsunset.conf, generado y en .gitignore): dos perfiles por horario (de día `identity`, de noche
la temperatura) o, sin horario, uno solo neutro y se prende a mano. Lo que
eligió el usuario va en la línea `# settings:` de la cabecera, que es lo que se
relee. El daemon corre como hyprsunset.service (usuario); prender y apagar en
el momento va por IPC (`hyprctl hyprsunset …`) y dura hasta el próximo perfil.
"""

from __future__ import annotations

import os
import re
import shutil

from common import DOTFILES, run

# hyprsunset solo lee ~/.config/hypr/hyprsunset.conf, que es config/hypr del
# repo: el archivo es generado y está en .gitignore (como hypridle.conf).
CONF = DOTFILES / "config" / "hypr" / "hyprsunset.conf"
UNIT = "hyprsunset.service"
DEFAULTS = {"temperature": "4500", "gamma": "100", "schedule": "on", "from": "21:00", "to": "07:30"}
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def installed() -> bool:
    return bool(shutil.which("hyprsunset"))


def running() -> bool:
    return run(["systemctl", "--user", "is-active", UNIT]).stdout.strip() == "active" or \
        run(["pgrep", "-x", "hyprsunset"]).returncode == 0


def read_conf() -> dict:
    cfg = dict(DEFAULTS)
    try:
        m = re.search(r"^# settings: (.*)$", CONF.read_text(), re.M)
    except OSError:
        m = None
    if m:
        cfg.update(dict(kv.split("=", 1) for kv in m.group(1).split() if "=" in kv))
    return cfg


def write_conf(cfg: dict) -> None:
    """Genera hyprsunset.conf (temporal + os.replace: el daemon lo lee al arrancar)."""
    settings = " ".join(f"{k}={cfg[k]}" for k in DEFAULTS)
    night = (f"profile {{\n    time = {cfg['from']}\n    temperature = {cfg['temperature']}\n"
             f"    gamma = {int(cfg['gamma']) / 100:g}\n}}\n")
    if cfg["schedule"] == "on":
        body = f"profile {{\n    time = {cfg['to']}\n    identity = true\n}}\n\n" + night
    else:
        body = "# sin horario: neutro todo el día, se prende a mano desde Settings → Displays\n" \
               "profile {\n    time = 0:00\n    identity = true\n}\n"
    text = ("# hyprsunset — luz nocturna. Generado por Settings → Displays → Night light settings:\n"
            "# se reescribe desde ahí (la línea settings es lo que se relee).\n"
            f"# settings: {settings}\n\n"
            "max-gamma = 100\n\n" + body)
    tmp = CONF.with_suffix(".conf.tmp")
    tmp.write_text(text)
    os.replace(tmp, CONF)


def ipc(*args: str) -> str:
    return run(["hyprctl", "hyprsunset", *args]).stdout.strip()


def filtering() -> bool | None:
    """True si el filtro está aplicado ahora; None si no se pudo saber."""
    ident = ipc("identity", "get")
    if ident in ("true", "false"):
        return ident == "false"
    return None


def describe(cfg: dict) -> str:
    sched = f"{cfg['from']} → {cfg['to']}" if cfg["schedule"] == "on" else "no schedule"
    gamma = f" · brightness {cfg['gamma']}%" if cfg["gamma"] != "100" else ""
    return f"{cfg['temperature']}K{gamma} · {sched}"


def in_night(cfg: dict) -> bool:
    """Si el horario dice que ahora es de noche (para cuando el IPC no responde)."""
    if cfg["schedule"] != "on":
        return False
    from datetime import datetime
    now = datetime.now().strftime("%H:%M")
    start, end = (f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}" for t in (cfg["from"], cfg["to"]))
    return start <= now or now < end if start > end else start <= now < end
