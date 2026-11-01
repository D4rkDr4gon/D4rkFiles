-- =============================================================================
-- Hyprland — configuración base (Hyprland >= 0.57: la config es Lua)
-- Mismos keybindings y comportamiento que la config de Qtile (Wayland).
--
-- Nada de acá depende del usuario o la máquina:
--   env.lua     (generado)  terminal/navegador/teclado, desde ~/.config/dotfiles/user.conf
--   theme.lua   (generado)  bordes, rounding, opacidad, blur y animaciones del tema activo
--   ~/.config/dotfiles/hypr/*.conf / *.lua   tus overrides (monitores, atajos propios…),
--               cargados al final por lib/user_conf.lua
-- Los scripts usan scripts/hypr-dispatch (por ruta absoluta) para los dispatchers.
-- =============================================================================

local home     = os.getenv("HOME")
local hypr     = home .. "/.config/hypr"
local mainMod  = "SUPER"
-- Ruta estable al repo (symlink creado por install.sh, sin importar dónde lo clonaste)
local dotfiles = home .. "/.local/share/dotfiles"
local SCRIPTS  = hypr .. "/scripts"
local USER_DIR = home .. "/.config/dotfiles/hypr"

-- Carga un archivo generado; si falta o falla, avisa y sigue con lo de acá
local function load(name)
    local ok, res = pcall(dofile, hypr .. "/" .. name)
    if not ok then
        hl.notification.create({ text = name .. ": " .. tostring(res), timeout = 10000, icon = "error" })
        return nil
    end
    return res
end

local env = load("env.lua") or {}
local terminal     = env.terminal or "kitty"
local browser      = env.browser or "firefox"
local file_manager = env.file_manager or "thunar"
local editor       = env.editor or terminal

-- -----------------------------------------------------------------------------
-- MONITOR — autodetección (resolución preferida, posición automática, escala 1).
-- Para un layout propio (varios monitores, escala, refresh) creá
-- ~/.config/dotfiles/hypr/monitors.conf; `hyprctl monitors` lista los nombres.
-- -----------------------------------------------------------------------------
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })

-- -----------------------------------------------------------------------------
-- EXEC ONCE — Autostart (equivalente a hooks.py)
-- -----------------------------------------------------------------------------
-- Una línea por comando ("cmd",  -- nota): Settings → Startup apps las lista.
-- hl.exec_cmd corre con `sh -c`, así que $HOME y && funcionan.
hl.on("hyprland.start", function()
    local autostart = {
        "waybar",
        "dunst",
        "$HOME/.local/share/dotfiles/scripts/wayland/notif-jump.py",   -- click del medio en una notificación -> workspace de la app
        "swayosd-server",                                              -- OSD de volumen/brillo (estilo: swayosd/style.css, tematizado por theme-switch.sh)
        "wl-paste --type text  --watch $HOME/.local/share/dotfiles/scripts/cliphist.sh store",   -- historial de portapapeles (texto)
        "wl-paste --type image --watch $HOME/.local/share/dotfiles/scripts/cliphist.sh store",   -- historial de portapapeles (imágenes)
        "[ -x /usr/lib/fprintd ] && $HOME/.local/share/dotfiles/config/fprint-osd/fprint-osd.py", -- OSD de huella (solo si fprintd está instalado)
        "$HOME/.local/share/dotfiles/config/desktop-widgets/desktop-widgets.py", -- widgets en workspaces vacíos (reloj, música, clima…); Settings → Desktop widgets
        "$HOME/.local/share/dotfiles/config/hypr/scripts/start-hyprpaper.sh",
        "$HOME/.local/share/dotfiles/scripts/welcome.sh",              -- notify-send de bienvenida
        "systemctl --user start hyprland-session-init.service",        -- Activar graphical-session.target para portal
        "command -v kdeconnectd >/dev/null && kdeconnectd",            -- KDE Connect (opcional)
        "$HOME/.local/share/dotfiles/scripts/phone-proximity.py",      -- bloquea al alejarse el teléfono (Settings → Phone; off por defecto)
        "$HOME/.local/share/dotfiles/scripts/usbguard-notify.py",      -- avisa/permite USB bloqueados (sale solo si no hay usbguard)
        "$HOME/.local/share/dotfiles/tools/spotify_api.py --autostart", -- spotify_player -d si se prendió en Settings → Spotify (off por defecto)
        "$HOME/.local/share/dotfiles/config/hypr/scripts/hypr-session.py daemon", -- autosave/restauración de ventanas (Settings → Workspaces → Session)
        "systemctl --user start hyprpolkitagent",                      -- agente de polkit (diálogo de contraseña/huella; tema: hyprtoolkit.conf)
        "hyprshell run",                                               -- overview (Mod+W / swipe 3 dedos arriba) + Alt+Tab con previews; config: config/hyprshell/config.ron
    }
    for _, cmd in ipairs(autostart) do
        hl.exec_cmd(cmd)
    end
end)

-- -----------------------------------------------------------------------------
-- CONFIG — input, gestos, general, cursor, decoration (lo que depende del tema
-- está en theme.lua; el layout de teclado, en env.lua)
-- -----------------------------------------------------------------------------
hl.config({
    input = {
        kb_layout     = env.kb_layout or "us",
        kb_variant    = env.kb_variant or "",
        follow_mouse  = 1,
        mouse_refocus = false,
        sensitivity   = 0,

        touchpad = {
            natural_scroll       = true,
            tap_to_click         = true,
            drag_lock            = true,
            disable_while_typing = true,
            scroll_factor        = 0.5,
        },
    },

    gestures = {
        workspace_swipe_distance     = 300,
        workspace_swipe_cancel_ratio = 0.3,   -- más fácil confirmar el cambio
        workspace_swipe_create_new   = false, -- no crear workspaces fuera de los habilitados
        workspace_swipe_forever      = false, -- no saltar varios workspaces de un swipe
    },

    general = {
        layout = "dwindle",
    },

    cursor = {
        inactive_timeout = 3,
    },

    decoration = {
        active_opacity     = 1.0,
        fullscreen_opacity = 1.0,
        blur = {
            new_optimizations = true,
            ignore_opacity    = false,
        },
    },
})

-- 3 dedos horizontal: cambiar de workspace (sigue el dedo, como macOS/GNOME)
hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
-- 3 dedos arriba: overview de workspaces (hyprshell). Mismo IPC que Mod+W.
hl.gesture({
    fingers   = 3,
    direction = "up",
    action    = function() hl.exec_cmd("hyprshell socat '\"OpenOverview\"'") end,
})

-- Tema activo: borde, gaps, rounding, opacidad, blur, sombra y animaciones
load("theme.lua")

-- -----------------------------------------------------------------------------
-- WINDOW RULES — Reglas de flotación y opacidad (equivalente a layouts.py + hooks.py)
-- -----------------------------------------------------------------------------
for _, class in ipairs({ "pavucontrol", "blueman-manager", "nm-connection-editor", "qt5ct",
                         "pinentry", "ssh-askpass", "Bitwarden" }) do
    hl.window_rule({ match = { class = "^(" .. class .. ")$" }, float = true })
end
for _, title in ipairs({ "branchdialog", "confirmreset", "makebranch", "maketag" }) do
    hl.window_rule({ match = { title = "^(" .. title .. ")$" }, float = true })
end

-- Firefox siempre a pantalla completa no flotante
hl.window_rule({ match = { class = "^(firefox)$" }, tile = true })

-- Diálogos centrados de tamaño fijo, abren y cierran con el mismo atajo
-- (config/waybar/scripts/center-tui-launch.sh). La opacidad de los TUI la pone theme.lua.
local dialogs = {
    settings  = { 1560, 960 },   -- tools/settings/settings_tui.py
    clipboard = { 1200, 680 },   -- tools/clipboard_tui.py, Mod+V
    expenses  = { 1560, 960 },   -- tools/expenses_tui.py, Mod+G
    ["spotify-tui"] = { 1300, 800 }, -- tools/spotify_tui.py, Mod+Y
}
for class, size in pairs(dialogs) do
    hl.window_rule({ match = { class = "^(" .. class .. ")$" }, float = true, center = true,
                     size = size, opacity = "0.97 override" })
end

-- Ventana del menú Update (rofi/scripts/update-menu.sh): terminal centrada, sin pin,
-- porque corre tareas largas con sudo/huella.
hl.window_rule({ match = { class = "^(dotfiles-update)$" }, float = true, center = true, size = { 1000, 620 } })

-- Widgets TUI flotantes (config/waybar/scripts/*-launch.sh): float + pin (visibles
-- en todos los workspaces), como un popup en la esquina superior derecha. El tamaño
-- lo pide kitty en celdas y la posición la calcula float-tui-launch.sh.
for _, class in ipairs({ "proton-backup", "claude-agents", "cliamp", "bluetui", "impala",
                         "vpn-tui", "shortcuts", "hyprmon", "webapps", "modes" }) do
    hl.window_rule({ match = { class = "^(" .. class .. ")$" }, float = true, pin = true })
end
hl.window_rule({ match = { class = "^(proton-backup)$" }, opacity = "0.97 override" })

-- Widgets de escritorio (config/desktop-widgets): blur detrás de las tarjetas;
-- ignore_alpha deja sin blur la parte transparente de la capa
hl.layer_rule({ match = { namespace = "^(desktop-widgets)$" }, blur = true, ignore_alpha = 0.1 })

-- -----------------------------------------------------------------------------
-- KEYBINDINGS — Replican exactamente los de Qtile (keys.py)
-- -----------------------------------------------------------------------------
local function exec(keys, cmd, flags)
    hl.bind(keys, hl.dsp.exec_cmd(cmd), flags)
end

-- ===================== APLICATION SHORTCUTS =====================
exec(mainMod .. " + Return",         terminal)
exec(mainMod .. " + SHIFT + Return", dotfiles .. "/config/herdr/launch.sh")
exec(mainMod .. " + Space",          "rofi -show drun -theme " .. home .. "/.config/rofi/theme-drun.rasi")  -- walker/elephant tiene una race condition: ver docs/components.md
exec(mainMod .. " + B",              browser)
exec(mainMod .. " + F",              "cd /tmp && " .. file_manager)  -- cwd=/tmp: hyprfm-git ignora su theme si cwd == $HOME (bug upstream)
exec(mainMod .. " + K",              "bash " .. home .. "/.config/waybar/scripts/shortcuts-launch.sh")  -- cheatsheet de shortcuts, ver + editar
exec(mainMod .. " + S",              editor)
exec(mainMod .. " + V",              home .. "/.config/waybar/scripts/clipboard-launch.sh")  -- historial de portapapeles (cliphist + TUI)
exec(mainMod .. " + G",              home .. "/.config/waybar/scripts/expenses-launch.sh")   -- gestor de gastos (TUI)
exec(mainMod .. " + Y",              home .. "/.config/waybar/scripts/spotify-launch.sh")    -- Spotify (TUI sobre spotify_player)
exec(mainMod .. " + E",              home .. "/.config/rofi/scripts/emoji.sh")               -- selector de emojis (copia al portapapeles)
exec(mainMod .. " + SHIFT + M",      dotfiles .. "/scripts/mode-switch.sh")  -- modos de escritorio (~/.config/dotfiles/modes.conf)

-- ===================== CLOSE / WINDOW TOGGLE =====================
hl.bind(mainMod .. " + Q",         hl.dsp.window.close())
hl.bind(mainMod .. " + SHIFT + F", hl.dsp.window.fullscreen())
exec(mainMod .. " + SHIFT + D",    dotfiles .. "/scripts/focus-mode.sh toggle")  -- modo Focus: No Molestar + sin widgets que distraen
hl.bind(mainMod .. " + T",         hl.dsp.window.float({ action = "toggle" }))

-- ===================== MOVE / RESIZE WINDOW (hjkl) =====================
local dirs   = { h = "left", l = "right", k = "up", j = "down" }
local resize = { h = { -30, 0 }, l = { 30, 0 }, k = { 0, -30 }, j = { 0, 30 } }
for key, dir in pairs(dirs) do
    hl.bind(mainMod .. " + SHIFT + " .. key, hl.dsp.window.move({ direction = dir }))
    hl.bind(mainMod .. " + CTRL + " .. key,  hl.dsp.window.resize({ x = resize[key][1], y = resize[key][2], relative = true }))
end

-- ===================== LAYOUT =====================
hl.bind(mainMod .. " + Tab", hl.dsp.window.cycle_next())
hl.bind(mainMod .. " + N",   hl.dsp.layout("togglesplit"))  -- equivalente a normalize en dwindle
-- Alt+Tab: lo registra hyprshell (switcher con previews, hyprshell/config.ron)

-- ===================== WORKSPACES (Qtile-like behavior) =====================
-- Los scripts traen el workspace N al monitor actual antes de enfocarlo, como
-- en Qtile. La cantidad (1–10, 9 por defecto; Qtile: 1..6) la elige Settings →
-- Workspaces en ~/.config/dotfiles/hypr/workspaces.conf ("# count: N").
local function ws_count()
    local f = io.open(USER_DIR .. "/workspaces.conf")
    if not f then return 9 end
    local text = f:read("*a")
    f:close()
    return math.max(1, math.min(10, tonumber(text:match("# count: *(%d+)")) or 9))
end

for i = 1, ws_count() do
    local key = i % 10  -- el 10 es la tecla 0
    exec(mainMod .. " + " .. key,         SCRIPTS .. "/move-and-focus-workspace.sh " .. i)
    exec(mainMod .. " + SHIFT + " .. key, SCRIPTS .. "/move-window-to-workspace.sh " .. i)
end

exec("CTRL + Tab",         SCRIPTS .. "/workspace-cycle.sh next")  -- Ctrl+Tab siguiente (da la vuelta en 1..N)
exec("CTRL + SHIFT + Tab", SCRIPTS .. "/workspace-cycle.sh prev")  -- Ctrl+Shift+Tab anterior

-- ===================== SYSTEM / UTILITIES =====================
exec(mainMod .. " + L",             home .. "/.config/rofi/scripts/action-menu.sh")
exec(mainMod .. " + SHIFT + Space", home .. "/.config/waybar/scripts/settings-launch.sh")
hl.bind(mainMod .. " + CTRL + R", function()  -- recarga waybar y la config
    hl.exec_cmd(dotfiles .. "/scripts/barupdate.sh")
    hl.dispatch(hl.dsp.reload_config())
end)

-- ===================== SCREENSHOTS =====================
exec("Print",                   dotfiles .. "/scripts/screenshot.sh")
exec(mainMod .. " + SHIFT + S", dotfiles .. "/scripts/screenshot.sh")

-- ===================== VOLUMEN / BRILLO / MEDIA (OSD vía swayosd) =====================
-- locked = funciona con la pantalla bloqueada; repeating = repite al mantener
-- (no tiene sentido para mute/media)
local held = { locked = true, repeating = true }
exec("XF86AudioRaiseVolume",  "swayosd-client --output-volume +5",          held)
exec("XF86AudioLowerVolume",  "swayosd-client --output-volume -5",          held)
exec("XF86AudioMute",         "swayosd-client --output-volume mute-toggle", { locked = true })
exec("XF86AudioMicMute",      "swayosd-client --input-volume mute-toggle",  { locked = true })
exec("XF86MonBrightnessUp",   "swayosd-client --brightness +10",            held)
exec("XF86MonBrightnessDown", "swayosd-client --brightness -10",            held)
exec("XF86AudioPlay",         "swayosd-client --playerctl play-pause",      { locked = true })
exec("XF86AudioNext",         "swayosd-client --playerctl next",            { locked = true })
exec("XF86AudioPrev",         "swayosd-client --playerctl prev",            { locked = true })

-- ===================== MOUSE BINDINGS =====================
hl.bind(mainMod .. " + mouse:272", hl.dsp.window.drag(),   { mouse = true })
hl.bind(mainMod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

-- ===================== WINDOW MANAGEMENT =====================
hl.bind(mainMod .. " + M",     hl.dsp.window.fullscreen())            -- Maximizar (fullscreen pero con bordes y barra)
hl.bind(mainMod .. " + minus", hl.dsp.focus({ workspace = "empty" })) -- Ir a workspace vacío

-- ===================== MONITOR NAVIGATION =====================
hl.bind(mainMod .. " + period",         hl.dsp.focus({ monitor = "+1" }))        -- Siguiente monitor
hl.bind(mainMod .. " + comma",          hl.dsp.focus({ monitor = "-1" }))        -- Monitor anterior
hl.bind(mainMod .. " + SHIFT + period", hl.dsp.window.move({ monitor = "+1" }))  -- Mover ventana al sig. monitor
hl.bind(mainMod .. " + SHIFT + comma",  hl.dsp.window.move({ monitor = "-1" }))  -- Mover ventana al ant. monitor

-- =============================================================================
-- ENV — Variables de entorno
-- =============================================================================
hl.env("XCURSOR_THEME", "Adwaita")
hl.env("XCURSOR_SIZE", "24")
-- WLR_NO_HARDWARE_CURSORS lo agrega env.lua cuando se detecta NVIDIA o una VM.

-- NOTA: DISPLAY heredado del display manager ya se limpia con `unset DISPLAY` en
-- start-hyprland.sh, ANTES de lanzar Hyprland. No forzar DISPLAY="" acá: queda
-- persistente toda la sesión y rompe XWayland/apps X11 (ej. OnlyOffice).

-- Forzar backend Wayland
hl.env("XDG_SESSION_TYPE", "wayland")
hl.env("XDG_CURRENT_DESKTOP", "Hyprland")

-- =============================================================================
-- OVERRIDES DEL USUARIO — al final, así pisan todo lo anterior. Ejemplo
-- (~/.config/dotfiles/hypr/monitors.conf):
--   monitor=eDP-1,1920x1080@60,0x0,1
--   monitor=DP-1,2560x1440@144,1920x0,1
-- Los *.conf heredan $mainMod, $terminal, $browser, $fileManager, $editor,
-- $dotfiles y $SCRIPTS_DIR, como cuando hyprland.conf los incluía con `source`.
-- =============================================================================
local ok, user_conf = pcall(dofile, hypr .. "/lib/user_conf.lua")
if ok then
    user_conf.load(USER_DIR, {
        mainMod = mainMod, terminal = terminal, browser = browser, fileManager = file_manager,
        editor = editor, dotfiles = dotfiles, SCRIPTS_DIR = SCRIPTS,
    })
else
    hl.notification.create({ text = "lib/user_conf.lua: " .. tostring(user_conf), timeout = 10000, icon = "error" })
end
