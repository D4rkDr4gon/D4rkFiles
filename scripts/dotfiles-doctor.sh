#!/usr/bin/env bash
#===============================================================================
# dotfiles-doctor — diagnóstico de la instalación de dotfiles (solo lectura)
#   links     symlinks esperados en ~/.config y ~, y symlinks colgantes hacia el repo
#   packages  paquetes de install/packages/*.txt vs instalados (y si existen en repos)
#   services  units systemd esperadas habilitadas + units fallidas
#   configs   sintaxis de scripts/JSON/TOML/Python, themes, colores generados,
#             Hyprland y hyprshell
#   repo      secretos versionados, estado de apps en git, ignorados pero trackeados
#
# Uso: dotfiles-doctor.sh [sección...] [-v] [--strict] [--no-color] [-h]
#   sección: links packages services configs repo (default: todas)
#   -v         muestra también los chequeos OK y los que no aplican
#   --strict   los avisos (WARN) también hacen fallar (exit 1)
# Exit: 0 todo bien · 1 errores (o avisos con --strict) · 2 uso incorrecto
# CI (sin sistema real): dotfiles-doctor.sh configs repo
#===============================================================================

set -uo pipefail

DOTFILES="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
PKG_DIR="$DOTFILES/install/packages"
MANIFEST="$DOTFILES/manifest/links.tsv"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles"

VERBOSE=0; STRICT=0; USE_COLOR=1
SECTIONS=()
for arg in "$@"; do
    case "$arg" in
        links|packages|services|configs|repo) SECTIONS+=("$arg") ;;
        -v|--verbose) VERBOSE=1 ;;
        --strict)     STRICT=1 ;;
        --no-color)   USE_COLOR=0 ;;
        -h|--help)    sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            echo "Opción desconocida: $arg (usá -h)" >&2; exit 2 ;;
    esac
done
[ ${#SECTIONS[@]} -eq 0 ] && SECTIONS=(links packages services configs repo)
{ [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; } || USE_COLOR=0

if [ "$USE_COLOR" -eq 1 ]; then
    GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; DIM='\033[2m'; NC='\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; BLUE=''; DIM=''; NC=''
fi

N_OK=0; N_WARN=0; N_ERR=0        # totales
S_OK=0; S_WARN=0; S_ERR=0        # de la sección en curso

header() { echo -e "\n${BLUE}══ $1 ══${NC}"; S_OK=0; S_WARN=0; S_ERR=0; }
footer() {
    local extra=""
    [ "$S_WARN" -gt 0 ] && extra+=", ${S_WARN} avisos"
    [ "$S_ERR" -gt 0 ]  && extra+=", ${S_ERR} errores"
    echo -e "${DIM}  → ${S_OK} ok${extra}${NC}"
}
pass()  { N_OK=$((N_OK+1));     S_OK=$((S_OK+1));     [ "$VERBOSE" -eq 1 ] && echo -e "  ${GREEN}✓${NC} $1"; return 0; }
warn()  { N_WARN=$((N_WARN+1)); S_WARN=$((S_WARN+1)); echo -e "  ${YELLOW}⚠${NC} $1"; return 0; }
err()   { N_ERR=$((N_ERR+1));   S_ERR=$((S_ERR+1));   echo -e "  ${RED}✗${NC} $1"; return 0; }
skip()  { [ "$VERBOSE" -eq 1 ] && echo -e "  ${DIM}- $1${NC}"; return 0; }
hint()  { echo -e "      ${DIM}$1${NC}"; }
tilde() { echo "${1/#$HOME/\~}"; }

# ¿Aplica un chequeo? cond vacía = siempre; "a,b" = alguno de los comandos;
# "path:GLOB" = existe algún archivo que matchee.
applies() {
    local cond="$1" c
    [ -z "$cond" ] && return 0
    if [[ "$cond" == path:* ]]; then compgen -G "${cond#path:}" >/dev/null; return; fi
    local IFS=','
    for c in $cond; do command -v "$c" &>/dev/null && return 0; done
    return 1
}

# Archivos versionados (o, sin git, los del árbol), sin código de terceros.
tracked() { # patrón git (pathspec)
    if git -C "$DOTFILES" rev-parse --git-dir &>/dev/null; then
        git -C "$DOTFILES" ls-files -z -- "$@"
    else
        find "$DOTFILES" -type f \( -name "${1#\*\*/}" \) -not -path '*/.git/*' -print0
    fi
}

#===============================================================================
# LINKS
#===============================================================================
# Los enlaces esperados salen de manifest/links.tsv (el mismo archivo que usa install.sh).
# El grupo "hyprland" aplica si Hyprland está instalado; "x11" si lo está Qtile.
group_applies() {
    case "$1" in
        core)     return 0 ;;
        hyprland) command -v Hyprland &>/dev/null ;;
        x11)      command -v qtile &>/dev/null ;;
        *)        return 1 ;;
    esac
}

check_link() {
    local src="$1" dest="$2" real
    if [ ! -e "$src" ]; then
        if [ -e "$src.tpl" ]; then
            err "$(basename "$src") no está generado (falta renderizar la plantilla)"
            hint "scripts/theme-switch.sh <tema> --render-only"
        else
            err "${src#"$DOTFILES"/}: no existe en el repo (¿el manifiesto quedó desactualizado?)"
        fi
        return
    fi
    if [ -L "$dest" ]; then
        real="$(readlink -f "$dest")"
        if [ "$real" = "$(readlink -f "$src")" ]; then
            pass "$(tilde "$dest")"
        else
            err "$(tilde "$dest") apunta a $(tilde "$real") (esperado $(tilde "$src"))"
            hint "ln -sfT '$src' '$dest'   # o ./install.sh --only links (hace backup)"
        fi
    elif [ -e "$dest" ]; then
        err "$(tilde "$dest") es un archivo/directorio real, no un link al repo (los cambios no se versionan)"
        hint "./install.sh --only links   # lo mueve a un backup y crea el link"
    else
        err "$(tilde "$dest") no existe"
        hint "./install.sh --only links"
    fi
}

section_links() {
    header "LINKS"
    local src dst group s
    if [ ! -r "$MANIFEST" ]; then err "no encuentro $(tilde "$MANIFEST")"; footer; return; fi
    while IFS=$'\t' read -r src dst group; do
        [[ -z "$src" || "$src" == \#* ]] && continue
        group_applies "$group" || { skip "$dst: grupo $group no aplica"; continue; }
        s="$DOTFILES/$src"; [ "$src" = "." ] && s="$DOTFILES"
        check_link "$s" "$HOME/$dst"
    done < "$MANIFEST"
    # Symlinks colgantes que apuntan al repo (borrado/renombrado de algo versionado)
    local l target
    while IFS= read -r l; do
        target="$(readlink "$l")"
        if [[ "$target" == "$DOTFILES"* ]]; then
            err "link colgante: $(tilde "$l") → $(tilde "$target")"
            hint "rm '$l'   # o restaurar el archivo en el repo"
        fi
    done < <({ find "$HOME/.config" -maxdepth 4 -xtype l; find "$HOME" -maxdepth 1 -xtype l; } 2>/dev/null)
    footer
}

#===============================================================================
# PACKAGES
#===============================================================================
# Lista de paquetes de un grupo: un nombre por línea (sin comentarios).
declared() { awk '!/^[[:space:]]*(#|$)/ {print $1}' "$@" 2>/dev/null; }

section_packages() {
    header "PACKAGES"
    if ! command -v pacman &>/dev/null; then skip "no es Arch (sin pacman)"; footer; return; fi
    if [ ! -d "$PKG_DIR" ]; then err "no encuentro $(tilde "$PKG_DIR")"; footer; return; fi

    # Solo los grupos de las sesiones instaladas (base siempre).
    local -A kind=()
    local p f groups=(base)
    command -v Hyprland &>/dev/null && groups+=(hyprland)
    command -v qtile &>/dev/null && groups+=(x11)
    for f in "${groups[@]}"; do
        while IFS= read -r p; do kind[$p]=repo; done < <(declared "$PKG_DIR/$f.txt")
        while IFS= read -r p; do kind[$p]=aur;  done < <(declared "$PKG_DIR/$f.aur.txt")
    done
    local all=("${!kind[@]}")
    if [ ${#all[@]} -eq 0 ]; then err "no pude leer las listas de $(tilde "$PKG_DIR")"; footer; return; fi

    # pacman -T imprime los NO satisfechos y entiende `provides`
    local missing=()
    mapfile -t missing < <(pacman -T "${all[@]}" 2>/dev/null | sort)
    pass "$(( ${#all[@]} - ${#missing[@]} ))/${#all[@]} paquetes declarados están instalados"

    local have_sync=0 miss_repo=() miss_aur=()
    compgen -G '/var/lib/pacman/sync/*.db' >/dev/null && have_sync=1
    for p in "${missing[@]}"; do
        if [ "${kind[$p]}" = aur ]; then
            miss_aur+=("$p")
        elif [ "$have_sync" -eq 1 ] && ! pacman -Sddp "$p" &>/dev/null; then
            err "$p (install/packages) no existe en los repos: install.sh abortaría al instalarlo"
            hint "moverlo a la lista .aur.txt, corregir el nombre (¿renombrado en los repos?) o quitarlo"
        else
            miss_repo+=("$p")
        fi
    done
    [ ${#miss_repo[@]} -gt 0 ] && warn "declarados y no instalados (repos, ${#miss_repo[@]}): ${miss_repo[*]}"
    [ ${#miss_aur[@]} -gt 0 ]  && warn "declarados y no instalados (AUR, ${#miss_aur[@]}): ${miss_aur[*]}"
    [ $(( ${#miss_repo[@]} + ${#miss_aur[@]} )) -gt 0 ] && hint "./install.sh --only packages (usa --needed)"
    footer
}

#===============================================================================
# SERVICES
#===============================================================================
# scope | unit | condición (ver applies)
UNITS=(
    "user|pipewire.service|pipewire"
    "user|pipewire-pulse.service|pipewire-pulse"
    "user|wireplumber.service|wireplumber"
    "user|hyprland-session-init.service|Hyprland"
    "user|elephant.service|elephant"
    "user|battery-watch.timer|path:/sys/class/power_supply/BAT*"
    "system|display-manager.service|Hyprland,qtile"
    "system|bluetooth.service|bluetoothd"
    "system|power-profiles-daemon.service|powerprofilesctl"
    "system|fstrim.timer|fstrim"
)

section_services() {
    header "SERVICES"
    if ! command -v systemctl &>/dev/null; then skip "sin systemd"; footer; return; fi
    local entry scope unit cond state sc scflag
    for entry in "${UNITS[@]}"; do
        IFS='|' read -r scope unit cond <<< "$entry"
        applies "$cond" || { skip "$unit: no aplica"; continue; }
        sc=(); scflag=""; [ "$scope" = user ] && { sc=(--user); scflag=" --user"; }
        state="$(systemctl "${sc[@]}" is-enabled "$unit" 2>&1 | head -1)"
        case "$state" in
            enabled|enabled-runtime|static|alias|indirect|linked) pass "$scope $unit ($state)" ;;
            disabled)
                # Activación por D-Bus/socket: deshabilitada pero funcionando es válido
                if systemctl "${sc[@]}" is-active --quiet "$unit"; then
                    pass "$scope $unit (deshabilitada pero activa: la levanta D-Bus/socket)"
                else
                    warn "$scope $unit existe pero está deshabilitada e inactiva"
                    hint "systemctl${scflag} enable --now $unit"
                fi ;;
            *) err "$scope $unit: ${state:-no encontrada}" ;;
        esac
    done
    local failed
    for scope in system user; do
        sc=(); scflag=""; [ "$scope" = user ] && { sc=(--user); scflag=" --user"; }
        while IFS= read -r failed; do
            [ -n "$failed" ] && { warn "unit fallida ($scope): $failed"; hint "systemctl${scflag} status $failed"; }
        done < <(systemctl "${sc[@]}" --failed --no-legend --plain 2>/dev/null | awk '{print $1}')
    done
    footer
}

#===============================================================================
# CONFIGS
#===============================================================================
# Validador para JSON/JSONC/TOML/Python/themes. Imprime "E|archivo|msg", "W|..."
# y "S|msg" (no aplica). Todo en un solo python para no pagar N arranques.
PY_CHECK='
import ast, json, os, re, sys
kind, root, files = sys.argv[1], sys.argv[2], sys.argv[3:]

def strip_jsonc(t):
    out, i, n, s = [], 0, len(t), False
    while i < n:
        c = t[i]
        if s:
            out.append(c)
            if c == "\\": out.append(t[i+1]); i += 1
            elif c == "\"": s = False
        elif c == "\"": s = True; out.append(c)
        elif t.startswith("//", i):
            while i < n and t[i] != "\n": i += 1
            continue
        elif t.startswith("/*", i):
            j = t.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        else: out.append(c)
        i += 1
    t, out, s = "".join(out), [], False   # comas finales
    for i, c in enumerate(t):
        if s:
            out.append(c)
            if c == "\"" and t[i-1] != "\\": s = False
        elif c == "\"": s = True; out.append(c)
        elif c == ",":
            m = re.match(r"\s*[}\]]", t[i+1:])
            if not m: out.append(c)
        else: out.append(c)
    return "".join(out)

if kind == "toml":
    try: import tomllib
    except ImportError: print("S|python < 3.11 (sin tomllib)"); sys.exit(0)

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
REQ = ["name","wallpaper","primary","secondary","background","foreground","chip_battery",
       "chip_bluetooth","chip_wlan","chip_audio","status_ok","status_warn","status_error"]
for f in files:
    rel = os.path.relpath(f, root)
    try:
        data = open(f, encoding="utf-8").read()
        if   kind == "json":  json.loads(data)
        elif kind == "jsonc": json.loads(strip_jsonc(data))
        elif kind == "toml":  tomllib.loads(data)
        elif kind == "py":    ast.parse(data, f)
        elif kind == "theme":
            d = json.loads(data)
            for k in REQ:
                if k not in d: print(f"E|{rel}|falta la clave \"{k}\" (theme-switch escribiría \"null\")")
                elif k not in ("name","wallpaper") and not HEX.match(str(d[k])):
                    print(f"E|{rel}|{k}=\"{d[k]}\" no es #rrggbb")
            w = d.get("wallpaper")
            if w and os.path.isabs(w):
                print(f"W|{rel}|wallpaper con ruta absoluta ({w}): usar solo el nombre del archivo")
            elif w and not os.path.exists(os.path.join(root, "assets", "wallpapers", w)):
                # Puede vivir en ~/.local/share/backgrounds (imágenes propias del usuario).
                print(f"S|{rel}: wallpaper {w} no está en assets/wallpapers (¿imagen propia del usuario?)")
            for k in ("radius",):
                if k in d and not isinstance(d[k], (int, float)): print(f"E|{rel}|{k} debe ser numérico")
    except Exception as e:
        print(f"E|{rel}|{type(e).__name__}: {str(e).splitlines()[0]}")
'

run_pycheck() { # tipo, archivos... → reporta; devuelve nº de archivos chequeados
    local pykind="$1"; shift
    [ $# -eq 0 ] && return 0
    command -v python3 &>/dev/null || { skip "sin python3: no se chequea $pykind"; return 0; }
    local out level a b bad=0
    out="$(python3 -c "$PY_CHECK" "$pykind" "$DOTFILES" "$@" 2>&1)"
    while IFS='|' read -r level a b; do
        case "$level" in
            E) err "$a: $b"; bad=$((bad+1)) ;;
            W) warn "$a: $b" ;;
            S) skip "$a" ;;
            "") ;;
            *) err "python: $level|$a|$b"; bad=$((bad+1)) ;;
        esac
    done <<< "$out"
    [ "$bad" -eq 0 ] && pass "$# archivos $pykind válidos"
    return 0
}

section_configs() {
    header "CONFIGS"
    local files=() f bad

    # Shell: bash -n sobre los .sh versionados con shebang de bash/sh (o sin shebang)
    mapfile -d '' -t files < <(tracked '*.sh')
    bad=0
    for f in "${files[@]}"; do
        head -1 "$f" | grep -qE '^#!.*(fish|zsh|python|perl|node)' && continue
        if ! out="$(bash -n "$f" 2>&1)"; then
            err "sintaxis bash: ${f#"$DOTFILES"/}: $(head -1 <<< "$out" | sed 's/^[^:]*: //')"; bad=$((bad+1))
        fi
    done
    [ "$bad" -eq 0 ] && pass "${#files[@]} scripts .sh sin errores de sintaxis"

    mapfile -d '' -t files < <(tracked '*.py');    run_pycheck py "${files[@]}"
    mapfile -d '' -t files < <(tracked '*.json');  run_pycheck json "${files[@]}"
    mapfile -d '' -t files < <(tracked '*.jsonc'); run_pycheck jsonc "${files[@]}"
    mapfile -d '' -t files < <(tracked '*.toml');  run_pycheck toml "${files[@]}"

    # Themes: claves obligatorias, colores #rrggbb, wallpaper
    files=("$DOTFILES"/themes/*/theme.json)
    [ -e "${files[0]}" ] && run_pycheck theme "${files[@]}"

    # Plantillas: cada .tpl debe tener su archivo generado (theme-switch.sh --render-only).
    local t missing_gen=0
    while IFS= read -r -d '' t; do
        [ -f "${t%.tpl}" ] || { warn "sin renderizar: ${t%.tpl}"; missing_gen=$((missing_gen+1)); }
    done < <(find "$DOTFILES/config" "$DOTFILES/home" "$DOTFILES/system" -name '*.tpl' -print0 2>/dev/null)
    if [ "$missing_gen" -eq 0 ]; then pass "todas las plantillas (.tpl) están renderizadas"
    else hint "scripts/theme-switch.sh <tema> --render-only"; fi

    # Archivos generados: deben contener el `primary` del tema actual; si no, un
    # theme-switch se cortó a medias.
    local cur="$STATE_DIR/current_theme.json" primary
    primary="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["primary"])' "$cur" 2>/dev/null)"
    if [ -n "$primary" ]; then
        local generated=(config/kitty/colors.conf config/swayosd/style.css config/hyprshell/styles.css
                         config/walker/themes/dotfiles/style.css config/waybar/theme.css config/polybar/colors.ini
                         config/dunst/dunstrc config/lazygit/config.yml config/impala/config.toml config/fprint-osd/style.css)
        bad=0
        for f in "${generated[@]}"; do
            [ -f "$DOTFILES/$f" ] || continue
            grep -qi "$primary" "$DOTFILES/$f" || { warn "$f no contiene el primary del tema actual ($primary): ¿theme-switch a medias?"; bad=$((bad+1)); }
        done
        if [ "$bad" -eq 0 ]; then pass "colores generados consistentes con el tema actual ($primary)"
        else hint "scripts/theme-switch.sh <tema> para reaplicar"; fi
    else
        skip "sin current_theme.json en $(tilde "$STATE_DIR"): no se compara el tema"
    fi

    # Validadores propios de cada app (solo si está corriendo/instalada)
    if command -v hyprctl &>/dev/null && [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
        local herr; herr="$(hyprctl configerrors 2>/dev/null | sed '/^[[:space:]]*$/d')"
        if [ -z "$herr" ]; then pass "hyprctl configerrors: sin errores"
        else err "Hyprland reporta errores de config:"; sed 's/^/      /' <<< "$herr"; fi
    else
        skip "Hyprland no está corriendo: sin hyprctl configerrors"
    fi
    if command -v hyprshell &>/dev/null && [ -f "$DOTFILES/config/hyprshell/config.ron" ]; then
        if hyprshell config check -c "$DOTFILES/config/hyprshell/config.ron" &>/dev/null; then pass "hyprshell config check"
        else err "hyprshell config check falla"; hint "hyprshell config check -c config/hyprshell/config.ron"; fi
    fi
    footer
}

#===============================================================================
# REPO
#===============================================================================
# Nombres de archivo que no deberían estar nunca en git (ni en el historial)
SECRET_NAMES_RE='(^|/)(refresh_token|\.env(\..*)?|id_(rsa|dsa|ecdsa|ed25519)|[^/]*\.(pem|p12|pfx|kdbx|key))$'

section_repo() {
    header "REPO"
    if ! git -C "$DOTFILES" rev-parse --git-dir &>/dev/null; then skip "no es un repo git"; footer; return; fi
    local g=(git -C "$DOTFILES") f n

    # Secretos por nombre de archivo
    local bad=0
    while IFS= read -r f; do
        err "secreto versionado: $f"
        bad=$((bad+1))
    done < <("${g[@]}" ls-files | grep -E "$SECRET_NAMES_RE")
    # Estado de apps (bases de datos): no es secreto per se, pero es local y cambia solo
    while IFS= read -r f; do
        warn "estado de aplicación versionado (base de datos local): $f"
    done < <("${g[@]}" ls-files | grep -E '\.(sqlite3?|db)(-shm|-wal)?$')

    # Secretos por contenido (solo archivo:línea: nunca se imprime el valor)
    local hits
    hits="$("${g[@]}" grep -InE \
        -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' -e 'ghp_[A-Za-z0-9]{36}' -e 'github_pat_[A-Za-z0-9_]{50,}' \
        -e 'AKIA[0-9A-Z]{16}' -e 'xox[baprs]-[A-Za-z0-9-]{10,}' -e 'sk-ant-[A-Za-z0-9_-]{20,}' \
        -e 'AIza[0-9A-Za-z_-]{35}' \
        -- ':!scripts/dotfiles-doctor.sh' 2>/dev/null | cut -d: -f1,2)"
    while IFS= read -r f; do
        [ -n "$f" ] && { err "posible credencial en el contenido: $f"; bad=$((bad+1)); }
    done <<< "$hits"
    if [ "$bad" -eq 0 ]; then pass "sin credenciales versionadas (nombres + patrones conocidos)"
    else
        hint "1) revocar/rotar la credencial  2) git rm --cached + .gitignore  3) purgar el historial (git filter-repo)"
    fi

    # Datos de una máquina/usuario concreto: rutas absolutas de home o de otras particiones.
    local paths
    paths="$("${g[@]}" grep -InE '(/home/[a-z_][a-z0-9_-]*/|/Users/[A-Za-z]+/)' \
        -- ':!home/zsh/p10k.zsh' ':!scripts/dotfiles-doctor.sh' ':!.github' ':!docs' ':!*.md' 2>/dev/null \
        | grep -v 'home/zsh/' | cut -d: -f1,2)"
    if [ -z "$paths" ]; then pass "sin rutas absolutas de usuario"
    else
        while IFS= read -r f; do [ -n "$f" ] && warn "ruta absoluta de usuario: $f"; done <<< "$paths"
        hint "usar \$HOME, %h o los tokens @home@/@dotfiles@ de las plantillas"
    fi

    # Ya no están en HEAD pero siguen en el historial: en un repo público eso es
    # seguir expuestos (el remoto y cualquier clon/fork conservan el historial).
    local inhist=()
    mapfile -t inhist < <(comm -23 \
        <("${g[@]}" log --all --name-only --pretty=format: 2>/dev/null | grep -E "$SECRET_NAMES_RE" | sort -u) \
        <("${g[@]}" ls-files | sort -u))
    for f in "${inhist[@]}"; do
        [ -n "$f" ] && warn "ya no está versionado pero sigue en el HISTORIAL de git: $f"
    done
    if [ ${#inhist[@]} -gt 0 ] && [ -n "${inhist[0]}" ]; then
        hint "git filter-repo --invert-paths $(printf -- '--path %s ' "${inhist[@]}")"
        hint "y luego git push --force --all (reescribe hashes; avisar a quien tenga clones). Antes: revocar la credencial."
    fi

    # Trackeados pero ignorados por .gitignore
    n=0
    while IFS= read -r f; do
        warn "versionado pero ignorado por .gitignore: $f"; n=$((n+1))
        hint "git rm --cached '$f'"
    done < <("${g[@]}" ls-files -ci --exclude-standard)
    [ "$n" -eq 0 ] && pass "nada versionado que .gitignore excluya"

    # Estado de la rama (informativo)
    local st; st="$("${g[@]}" status -sb 2>/dev/null | head -1)"
    echo -e "  ${DIM}i ${st#\#\# }${NC}"
    [ -n "$("${g[@]}" status --porcelain 2>/dev/null)" ] && echo -e "  ${DIM}i hay cambios sin commitear${NC}"
    footer
}

#===============================================================================
# MAIN
#===============================================================================
for s in "${SECTIONS[@]}"; do "section_$s"; done

echo
echo -e "Resumen: ${GREEN}${N_OK} ok${NC} · ${YELLOW}${N_WARN} avisos${NC} · ${RED}${N_ERR} errores${NC}"
[ "$N_ERR" -gt 0 ] && exit 1
[ "$STRICT" -eq 1 ] && [ "$N_WARN" -gt 0 ] && exit 1
exit 0
