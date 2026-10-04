#!/usr/bin/env bash
# Etapa: herdr — plugins de herdr y su configuración.
#   - herdr-pet (nikok6/herdr-pet): mascota "neon" sobre los paneles
#   - herdr-plugin-manager (speardragon/herdr-plugin-manager): gestor en popup
#   - herdr-agent-usage (levi-qiao/herdr-agent-usage): cuota de Claude/opencode
# Los atajos y las filas del sidebar ya vienen en config/herdr/config.toml.tpl.
# Va después de links: el configure de agent-usage escribe en ~/.config/herdr,
# ~/.config/kitty y ~/.claude/settings.json, que tienen que estar enlazados.

HERDR_PLUGINS=(
    nikok6/herdr-pet
    speardragon/herdr-plugin-manager
    levi-qiao/herdr-agent-usage
)

# Preferencias de herdr-agent-usage (un archivo por clave en su config-dir).
# "only," marca la lista de agentes como selección explícita.
HERDR_USAGE_PREFS=(
    "agents=only,claude,opencode"
    "sidebar-layout=gauges"
    "fields=provider,model,context"
    "quota-percent=used"
    "low-quota-alert=20%"
    "row-gap=0"
    "sidebar-pacing=off"
    "statusline-pace=on"
    "agent-order=default"
)

# _herdr_plugin_root <id>: carpeta del checkout instalado (de plugins.json).
_herdr_plugin_root() {
    jq -r --arg id "$1" '.[] | select(.plugin_id == $id) | .plugin_root' \
        "${XDG_CONFIG_HOME:-$HOME/.config}/herdr/plugins.json" 2>/dev/null
}

_herdr_install_plugins() {
    local installed repo
    installed="$(herdr plugin list 2>/dev/null || true)"
    for repo in "${HERDR_PLUGINS[@]}"; do
        if grep -q "github:$repo@" <<<"$installed"; then
            log "herdr: $repo ya instalado"
            continue
        fi
        info "herdr: instalando $repo"
        run herdr plugin install "$repo" --yes >/dev/null || warn "herdr: falló $repo (reintentá: herdr plugin install $repo)"
    done
}

# Mascota neon (de petdex.dev, va a ~/.codex/pets) y pet.toml mínimo. Si ya
# existe un pet.toml no se toca: el popover de ajustes lo edita en vivo.
_herdr_pet() {
    if [[ ! -d "$HOME/.codex/pets/neon" ]]; then
        if ! command -v npx >/dev/null 2>&1; then
            warn "herdr-pet: falta npx para bajar la mascota neon"
        elif $DRY_RUN; then
            echo "[dry-run] npx --yes petdex@latest install neon"
        else
            npx --yes petdex@latest install neon >/dev/null 2>&1 || warn "herdr-pet: no se pudo bajar neon (npx petdex install neon)"
        fi
    fi
    local dir; dir="$(herdr plugin config-dir pet 2>/dev/null)" || return 0
    [[ -n "$dir" && ! -e "$dir/pet.toml" ]] || return 0
    if $DRY_RUN; then echo "[dry-run] crear $dir/pet.toml (pet = \"neon\")"; return 0; fi
    mkdir -p "$dir"
    printf 'enabled = true\npet = "neon"\n' > "$dir/pet.toml"
    log "herdr-pet: mascota neon"
}

# Preferencias + configure de agent-usage. configure solo acepta correr "dentro
# de herdr" (HERDR_PLUGIN_*); se le pasan esas variables para no depender de
# un servidor corriendo. Es idempotente: repara lo que falte y no duplica.
_herdr_agent_usage() {
    local root config state pref
    root="$(_herdr_plugin_root herdr-agent-usage)"
    [[ -x "$root/target/release/herdr-agent-usage" ]] || { $DRY_RUN || warn "herdr-agent-usage no está compilado: se omite su configuración"; return 0; }
    config="$(herdr plugin config-dir herdr-agent-usage)"
    state="${XDG_STATE_HOME:-$HOME/.local/state}/herdr/plugins/herdr-agent-usage"
    run mkdir -p "$config" "$state"
    for pref in "${HERDR_USAGE_PREFS[@]}"; do
        [[ -e "$config/${pref%%=*}" ]] && continue   # respeta lo que cambiaste en sus ajustes
        if $DRY_RUN; then echo "[dry-run] $config/${pref%%=*} = ${pref#*=}"; else printf '%s\n' "${pref#*=}" > "$config/${pref%%=*}"; fi
    done
    run env HERDR_PLUGIN_ID=herdr-agent-usage HERDR_PLUGIN_ROOT="$root" \
        HERDR_PLUGIN_CONFIG_DIR="$config" HERDR_PLUGIN_STATE_DIR="$state" \
        "$root/target/release/herdr-agent-usage" configure --apply \
        && log "herdr-agent-usage: sidebar, statusline de Claude y fuente de iconos" \
        || warn "herdr-agent-usage: falló configure (desde herdr: acción \"Install / repair agent quota\")"
}

# Integraciones de herdr para los agentes presentes: sin ellas herdr no conoce
# el id de sesión de cada panel y agent-usage no puede atribuirle la cuota.
_herdr_integrations() {
    local agent status
    status="$(herdr integration status 2>/dev/null || true)"
    for agent in claude opencode; do
        command -v "$agent" >/dev/null 2>&1 || continue
        if grep -q "^$agent: not installed" <<<"$status"; then
            run herdr integration install "$agent" >/dev/null && log "herdr: integración $agent" \
                || warn "herdr: falló la integración $agent (herdr integration install $agent)"
        fi
    done
}

step_herdr() {
    header "herdr (plugins)"
    command -v herdr >/dev/null 2>&1 || { info "herdr no está instalado: se omite"; return 0; }
    command -v jq >/dev/null 2>&1 || { warn "Falta jq: se omiten los plugins de herdr"; return 0; }
    # herdr-agent-usage se compila con cargo (rustup también lo provee).
    if ! command -v cargo >/dev/null 2>&1; then
        local -a noconfirm=(); $ASSUME_YES && noconfirm=(--noconfirm)
        run sudo pacman -S --needed "${noconfirm[@]}" rust || warn "Sin cargo no se puede compilar herdr-agent-usage"
    fi

    _herdr_integrations
    _herdr_install_plugins
    _herdr_pet
    _herdr_agent_usage
    $DRY_RUN || herdr server reload-config >/dev/null 2>&1 || true   # solo si hay un servidor corriendo
    info "herdr: prefix+shift+m plugins · prefix+shift+p/o mascota · prefix+shift+r/q cuotas"
}
