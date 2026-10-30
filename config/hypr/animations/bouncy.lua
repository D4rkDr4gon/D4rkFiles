-- Preset de animaciones "bouncy" — Rebote marcado + popin.
-- Lo elige el campo `animations` del tema (Settings → Appearance → Motion);
-- theme.lua lo carga y agrega la animación del borde (borderangle).
hl.config({ animations = { enabled = true } })
hl.curve("overshot", { type = "bezier", points = { {0.34, 1.56}, {0.64, 1.0} } })
hl.curve("wind", { type = "bezier", points = { {0.05, 0.9}, {0.1, 1.15} } })
hl.curve("winOut", { type = "bezier", points = { {0.0, 0.0}, {0.2, 1.0} } })
hl.curve("liner", { type = "bezier", points = { {0.0, 0.0}, {1.0, 1.0} } })
hl.animation({ leaf = "windows", enabled = true, speed = 6, bezier = "overshot", style = "popin 80%" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 6, bezier = "overshot", style = "popin 80%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 5, bezier = "winOut", style = "popin 80%" })
hl.animation({ leaf = "fade", enabled = true, speed = 3, bezier = "liner" })
hl.animation({ leaf = "border", enabled = true, speed = 10, bezier = "liner" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 5, bezier = "wind", style = "slide" })
