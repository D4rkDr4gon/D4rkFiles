#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# webapp-manager.sh — TUI (fzf) para crear/abrir/borrar webapps
# Se abre desde Settings → WEBAPPS en una kitty flotante. Crear una webapp
# = pegar la URL: detecta manifest, nombre e ícono, la agrega a
# ~/.config/dotfiles/webapps.conf (la crea desde webapps.conf.example si
# falta) y la instala con scripts/webapps.sh. Requiere firefoxpwa, fzf,
# jq y python.
# ──────────────────────────────────────────────────────────
set -uo pipefail

# shellcheck source=/dev/null
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"
CONF="$DOTFILES_CONF_DIR/webapps.conf"
WEBAPPS_SH="$DOTFILES_DIR/scripts/webapps.sh"
FFPWA_CONFIG="$HOME/.local/share/firefoxpwa/config.json"
NEW="+  Nueva webapp"

bold=$'\e[1m'; dim=$'\e[2m'; red=$'\e[31m'; green=$'\e[32m'; reset=$'\e[0m'

pause() { read -rsn1 -p "${dim}Tecla para volver...${reset}"; echo; }

# ID<TAB>nombre<TAB>url de las webapps instaladas
list_installed() {
    [[ -r "$FFPWA_CONFIG" ]] || return 0
    jq -r '.sites | to_entries[] | [.key, (.value.config.name // .value.manifest.name),
        (.value.config.document_url // .value.manifest.start_url)] | @tsv' "$FFPWA_CONFIG" \
        | sort -t$'\t' -k2,2f
}

# Descarga la página y devuelve JSON {url, name, manifest, icon}. manifest
# queda vacío si el sitio no es PWA (o el manifest no responde); en ese
# caso icon apunta al mejor ícono del HTML o a /favicon.ico.
detect() {
    python3 - "$1" <<'PY'
import json, sys, urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.geturl(), r.read(2_000_000).decode("utf-8", "replace")

class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.manifest = None; self.icons = []; self.title = ""; self._in_title = False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "link" and a.get("href") and not a["href"].startswith("data:"):
            rel = (a.get("rel") or "").lower().split()
            if "manifest" in rel and not self.manifest:
                self.manifest = a["href"]
            elif "apple-touch-icon" in rel:
                self.icons.insert(0, a["href"])
            elif "icon" in rel:
                self.icons.append(a["href"])
    def handle_endtag(self, tag):
        if tag == "title": self._in_title = False
    def handle_data(self, data):
        if self._in_title: self.title += data

url, html = get(sys.argv[1])
h = Head(); h.feed(html)
out = {"url": url, "name": h.title.strip(), "manifest": "", "icon": ""}

if h.manifest:
    murl = urljoin(url, h.manifest)
    try:
        m = json.loads(get(murl)[1])
        out["manifest"] = murl
        out["name"] = m.get("short_name") or m.get("name") or out["name"]
    except Exception:
        pass
if not out["manifest"]:
    out["icon"] = urljoin(url, h.icons[0]) if h.icons else urljoin(url, "/favicon.ico")
print(json.dumps(out))
PY
}

create() {
    clear
    echo "${bold}Nueva webapp${reset}  ${dim}(vacío para cancelar)${reset}"
    echo
    local url
    read -rep "URL: " url
    [[ -z "$url" ]] && return
    [[ "$url" =~ ^https?:// ]] || url="https://$url"

    echo "${dim}Analizando $url...${reset}"
    local info
    if ! info="$(detect "$url" 2>/dev/null)"; then
        echo "${red}No se pudo abrir $url${reset}"; pause; return
    fi

    local doc name manifest icon
    doc="$(jq -r .url <<<"$info")"
    name="$(jq -r .name <<<"$info")"
    manifest="$(jq -r .manifest <<<"$info")"
    icon="$(jq -r .icon <<<"$info")"
    [[ -z "$name" ]] && name="$(sed -E 's#^https?://(www\.)?([^/.]+).*#\2#' <<<"$doc")"

    read -rep "Nombre: " -i "$name" name
    name="${name//|/}"
    [[ -z "$name" ]] && return
    if conf_has "$name" || list_installed | cut -f2 | grep -qxF "$name"; then
        echo "${red}Ya existe una webapp llamada \"$name\"${reset}"; pause; return
    fi

    echo
    echo "  ${bold}Nombre${reset}    $name"
    echo "  ${bold}URL${reset}       $doc"
    if [[ -n "$manifest" ]]; then
        echo "  ${bold}Manifest${reset}  $manifest"
    else
        echo "  ${bold}Manifest${reset}  ${dim}ninguno (no es PWA, se genera uno)${reset}"
        echo "  ${bold}Ícono${reset}     $icon"
    fi
    echo
    local ok
    read -rn1 -p "¿Crear? [S/n] " ok; echo
    [[ "$ok" =~ ^[nN]$ ]] && return

    ensure_conf
    printf '%s|%s|%s|%s\n' "$name" "$manifest" "$doc" "$icon" >> "$CONF"

    if bash "$WEBAPPS_SH" "$name"; then
        echo "${green}✓ $name creada: está en el launcher${reset}"
    else
        # Si falló, no dejar la entrada en el conf
        remove_conf_line "$name"
        echo "${red}✗ No se pudo instalar $name${reset}"
    fi
    pause
}

# Primer cambio propio: partir de la lista por defecto para no perderla
ensure_conf() {
    [[ -e "$CONF" ]] && return 0
    mkdir -p "$(dirname "$CONF")"
    cp "$DOTFILES_DIR/webapps.conf.example" "$CONF"
}

conf_has() { [[ -r "$CONF" ]] && awk -F'|' -v n="$1" '$1 == n {f=1} END {exit !f}' "$CONF"; }

remove_conf_line() {
    local tmp
    tmp="$(mktemp)"
    awk -F'|' -v n="$1" '$1 != n' "$CONF" > "$tmp" && cat "$tmp" > "$CONF"
    rm -f "$tmp"
}

delete() {
    local id="$1" name="$2" ok
    clear
    read -rn1 -p "¿Borrar ${bold}$name${reset}? Se pierde su sesión. [s/N] " ok; echo
    [[ "$ok" =~ ^[sS]$ ]] || return
    ensure_conf
    firefoxpwa site uninstall --quiet "$id" >/dev/null 2>&1 \
        && remove_conf_line "$name" \
        && echo "${green}✓ $name borrada${reset}" \
        || echo "${red}✗ No se pudo borrar $name${reset}"
    pause
}

reinstall() {
    local id="$1" name="$2"
    clear
    if ! conf_has "$name"; then
        echo "${red}$name no está en webapps.conf; no sé cómo reinstalarla${reset}"; pause; return
    fi
    echo "→ Reinstalando $name"
    firefoxpwa site uninstall --quiet "$id" >/dev/null 2>&1
    bash "$WEBAPPS_SH" "$name"
    pause
}

for dep in firefoxpwa fzf jq python3; do
    command -v "$dep" &>/dev/null || {
        echo "${red}Falta $dep: sudo pacman -S ${dep/python3/python}${reset}"; pause; exit 1
    }
done

while true; do
    out="$( { printf '%s\t%s\t\n' "-" "$NEW"; list_installed; } \
        | fzf --reverse --no-sort --delimiter=$'\t' --with-nth=2,3 --tabstop=4 \
            --prompt="Webapps > " --info=hidden \
            --header=$'enter abrir · ctrl-d borrar · ctrl-r reinstalar · esc salir\n' \
            --expect=ctrl-d,ctrl-r)" || exit 0

    key="$(sed -n 1p <<<"$out")"
    line="$(sed -n 2p <<<"$out")"
    [[ -z "$line" ]] && exit 0
    IFS=$'\t' read -r id name _ <<<"$line"

    if [[ "$name" == "$NEW" ]]; then
        [[ -z "$key" ]] && create
        continue
    fi

    case "$key" in
        ctrl-d) delete "$id" "$name" ;;
        ctrl-r) reinstall "$id" "$name" ;;
        *) setsid -f firefoxpwa site launch "$id" >/dev/null 2>&1; exit 0 ;;
    esac
done
