from libqtile.config import Group, Key
from libqtile.lazy import lazy
from .keys import keys, mod

# Mapeo OFICIAL (una sola verdad): (nombre de grupo, ícono de barra)
WORKSPACE_MAP = [
    ("1", "  "),
    ("2", "  "),
    ("3", "  "),
    ("4", "  "),
    ("5", "  "),
    ("6", "  ")
]

# Grupos: name = clave interna, label = ícono que muestra la barra
groups = [Group(name, label=label) for name, label in WORKSPACE_MAP]

# Keybindings: números → grupos
for key, name in WORKSPACE_MAP:
    keys.extend([
        Key([mod], key,
            lazy.group[name].toscreen(),
            desc=f"Go to workspace {name}"
        ),
        Key([mod, "shift"], key,
            lazy.window.togroup(name),
            desc=f"Move window to workspace {name}"
        ),
    ])
