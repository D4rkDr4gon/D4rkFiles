-- Preset de animaciones "off" — Sin animaciones (la curva liner queda definida para la línea del borde de theme.lua).
-- Lo elige el campo `animations` del tema (Settings → Appearance → Motion);
-- theme.lua lo carga y agrega la animación del borde (borderangle).
hl.config({ animations = { enabled = false } })
hl.curve("liner", { type = "bezier", points = { {0.0, 0.0}, {1.0, 1.0} } })
