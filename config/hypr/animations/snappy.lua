-- Preset de animaciones "snappy" — Rápido, sin rebote.
-- Lo elige el campo `animations` del tema (Settings → Appearance → Motion);
-- theme.lua lo carga y agrega la animación del borde (borderangle).
hl.config({ animations = { enabled = true } })
hl.curve("snap", { type = "bezier", points = { {0.2, 1.0}, {0.3, 1.0} } })
hl.curve("winOut", { type = "bezier", points = { {0.0, 0.0}, {0.2, 1.0} } })
hl.curve("liner", { type = "bezier", points = { {0.0, 0.0}, {1.0, 1.0} } })
hl.animation({ leaf = "windows", enabled = true, speed = 3, bezier = "snap", style = "slide" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 3, bezier = "snap", style = "slide" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 2, bezier = "winOut", style = "slide" })
hl.animation({ leaf = "fade", enabled = true, speed = 2, bezier = "liner" })
hl.animation({ leaf = "border", enabled = true, speed = 5, bezier = "liner" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 2, bezier = "snap", style = "slide" })
