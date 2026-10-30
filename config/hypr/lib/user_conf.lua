-- =============================================================================
-- user_conf.lua — overrides del usuario en ~/.config/dotfiles/hypr/
--
-- Hyprland >= 0.57 solo lee Lua, pero los overrides siguen en el formato de
-- siempre para no romper lo que ya tenía cada uno (y Settings los escribe así):
--   settings.conf   `input:sensitivity = 0.2`, `env = XCURSOR_SIZE,24` (Settings)
--   autostart.conf  `exec-once = cmd` (Settings → Startup apps)
--   monitors.conf   `monitor = eDP-1,1920x1080@60,0x0,1`
--   workspaces.conf `# count: N` (lo lee hyprland.lua; acá se saltea)
--   *.conf propios  el mismo subconjunto
-- Este módulo traduce ese subconjunto de hyprlang a hl.*: opciones (planas o en
-- bloques `input { … }`), `$var = …`, env, exec-once/exec, monitor, bind*/unbind
-- (exec y unos pocos dispatchers). Lo demás (windowrule, source, gesture, …)
-- no se aplica y se avisa con una notificación: pasalo a un *.lua.
-- Después corre los *.lua de la carpeta (Lua directo, todo hl.* disponible).
-- Todo en orden alfabético: el último que define algo gana.
-- =============================================================================

local M = {}

local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

-- Lista los archivos de una carpeta con esa extensión, ordenados
local function list(dir, ext)
    local out = {}
    local p = io.popen('ls -1 "' .. dir .. '" 2>/dev/null')
    if not p then return out end
    for name in p:lines() do
        if name:sub(-#ext) == ext then out[#out + 1] = name end
    end
    p:close()
    table.sort(out)
    return out
end

-- Valor de hyprlang -> tipo de Lua (true/false, número o texto)
local function typed(v)
    if v == "true" or v == "yes" or v == "on" then return true end
    if v == "false" or v == "no" or v == "off" then return false end
    return tonumber(v) or v
end

-- "SUPER SHIFT" / "$mainMod_SHIFT" + "K" -> "SUPER + SHIFT + K"
local function combo(mods, key)
    local parts = {}
    for m in mods:gmatch("[^%s_]+") do parts[#parts + 1] = m:upper() end
    parts[#parts + 1] = key
    return table.concat(parts, " + ")
end

-- Dispatchers de hyprlang que se traducen en un bind; el resto no
local function dispatcher(name, arg)
    if name == "exec" then return hl.dsp.exec_cmd(arg) end
    if name == "killactive" then return hl.dsp.window.close() end
    if name == "togglefloating" then return hl.dsp.window.float({ action = "toggle" }) end
    if name == "fullscreen" then return hl.dsp.window.fullscreen() end
    if name == "workspace" then return hl.dsp.focus({ workspace = arg }) end
    if name == "movetoworkspace" then return hl.dsp.window.move({ workspace = arg, follow = true }) end
    if name == "movetoworkspacesilent" then return hl.dsp.window.move({ workspace = arg, follow = false }) end
    return nil
end

local BIND_FLAGS = { l = "locked", e = "repeating", r = "release", o = "long_press",
                     n = "non_consuming", t = "transparent", i = "ignore_mods" }

-- monitor = nombre,modo,posición,escala[,clave,valor…] | nombre,disable
local function monitor(v)
    local f = {}
    for part in (v .. ","):gmatch("([^,]*),") do f[#f + 1] = trim(part) end
    local m = { output = f[1] or "" }
    if f[2] == "disable" or f[2] == "disabled" then
        m.disabled = true
        return m
    end
    m.mode, m.position, m.scale = f[2] ~= "" and f[2] or nil, f[3] ~= "" and f[3] or nil, typed(f[4] or "")
    if m.scale == "" then m.scale = nil end
    for i = 5, #f - 1, 2 do
        if f[i] ~= "" then m[f[i]] = typed(f[i + 1]) end
    end
    return m
end

-- Aplica un .conf; devuelve las líneas que no supo traducir. `base` = variables
-- que antes heredaban de hyprland.conf ($mainMod, $terminal, $SCRIPTS_DIR…)
local function load_conf(path, autostart, base)
    local fh = io.open(path)
    if not fh then return {} end
    local name = path:match("[^/]+$")
    local vars, stack, skipped = setmetatable({}, { __index = base }), {}, {}

    local function expand(s)
        return (s:gsub("%$([%w_]+)", function(k) return vars[k] or os.getenv(k) end))
    end

    local n = 0
    for raw in fh:lines() do
        n = n + 1
        -- `#` comenta hasta el final de la línea; `##` es un # literal
        local line = trim(raw:gsub("##", "\0"):gsub("#.*$", ""):gsub("\0", "#"))
        local ok = true
        if line == "" then
            -- vacía o comentario
        elseif line == "}" then
            stack[#stack] = nil
        elseif line:match("^[%w_:%.%-]+%s*{$") then
            stack[#stack + 1] = line:match("^([%w_:%.%-]+)")
        else
            local key, val = line:match("^([^=]-)%s*=%s*(.*)$")
            if not key then
                ok = false
            else
                key = trim(key)
                if key:sub(1, 1) == "$" then
                    vars[key:sub(2)] = expand(val)
                elseif #stack == 0 and (key == "exec-once" or key == "exec") then
                    autostart[#autostart + 1] = expand(val)
                elseif #stack == 0 and key == "env" then
                    local k, v = val:match("^%s*([^,]+),%s*(.*)$")
                    if k then hl.env(trim(k), expand(v)) else ok = false end
                elseif #stack == 0 and key == "monitor" then
                    hl.monitor(monitor(expand(val)))
                elseif #stack == 0 and key:match("^bind[a-z]*$") then
                    local mods, k, d, arg = expand(val):match("^([^,]*),%s*([^,]+),%s*([^,]+),?%s*(.*)$")
                    local dsp = mods and dispatcher(trim(d), trim(arg))
                    if dsp then
                        local flags = {}
                        for c in key:sub(5):gmatch(".") do
                            if BIND_FLAGS[c] then flags[BIND_FLAGS[c]] = true end
                        end
                        hl.bind(combo(mods, trim(k)), dsp, next(flags) and flags or nil)
                    else
                        ok = false
                    end
                elseif #stack == 0 and key == "unbind" then
                    local mods, k = expand(val):match("^([^,]*),%s*(.+)$")
                    if k then hl.unbind(combo(mods, trim(k))) else ok = false end
                elseif key:match("^[%w_%.:%-]+$") and (#stack > 0 or key:find(":")) then
                    -- opción: `input:touchpad:natural_scroll = true` o dentro de bloques
                    local path = table.concat(stack, ".") .. (#stack > 0 and "." or "") .. key
                    path = path:gsub(":", "."):gsub("%-", "_")
                    hl.config({ [path] = typed(expand(val)) })
                else
                    ok = false   -- windowrule, source, gesture, animation…
                end
            end
        end
        if not ok then skipped[#skipped + 1] = name .. ":" .. n .. "  " .. line end
    end
    fh:close()
    return skipped
end

-- Carga los overrides de `dir`; las apps de inicio se lanzan con la sesión
function M.load(dir, base)
    local autostart, skipped = {}, {}
    for _, name in ipairs(list(dir, ".conf")) do
        if name ~= "workspaces.conf" then
            for _, s in ipairs(load_conf(dir .. "/" .. name, autostart, base or {})) do skipped[#skipped + 1] = s end
        end
    end
    for _, name in ipairs(list(dir, ".lua")) do
        local ok, err = pcall(dofile, dir .. "/" .. name)
        if not ok then skipped[#skipped + 1] = name .. ": " .. tostring(err) end
    end
    if #autostart > 0 then
        hl.on("hyprland.start", function()
            for _, cmd in ipairs(autostart) do hl.exec_cmd(cmd) end
        end)
    end
    if #skipped > 0 then
        local shown = { table.unpack(skipped, 1, math.min(#skipped, 4)) }
        hl.notification.create({
            text = "~/.config/dotfiles/hypr: " .. #skipped .. " line(s) not applied (Hyprland 0.57 reads Lua;"
                .. " move them to a .lua file):\n" .. table.concat(shown, "\n"),
            timeout = 15000, icon = "warning",
        })
    end
end

return M
