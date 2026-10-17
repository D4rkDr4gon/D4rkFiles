#!/usr/bin/env bash
# install-netguard.sh — instala netguard (zonas de red, kill switch con VPN, endurecimiento) desde su repo
# independiente, en la versión fijada abajo, como paquete de pacman (makepkg). netguard también se usa sin
# D4rkFiles: https://github.com/D4rkDr4gon/netguard
#
#   install-netguard.sh            descarga/actualiza y construye el paquete
#   install-netguard.sh --setup    además corre `netguard setup --trust-current --enable-service`
#
# Lo usan la etapa `optional` del instalador (--with-netguard) y Settings (Firewall, Network security).
set -euo pipefail

NETGUARD_REPO="https://github.com/D4rkDr4gon/netguard.git"
NETGUARD_REF="v1.0.0"

# shellcheck source=lib/env.sh
source "$(dirname "$(readlink -f "$0")")/lib/env.sh"
SRC="${XDG_CACHE_HOME:-$HOME/.cache}/dotfiles/netguard"

for cmd in git makepkg; do
    command -v "$cmd" >/dev/null || { echo "Falta $cmd (pacman -S --needed git base-devel)" >&2; exit 1; }
done

if [[ -d "$SRC/.git" ]]; then
    git -C "$SRC" fetch --quiet --tags --force origin
else
    mkdir -p "$(dirname "$SRC")"
    git clone --quiet "$NETGUARD_REPO" "$SRC"
fi
git -C "$SRC" checkout --quiet --force "$NETGUARD_REF"

echo "== netguard $NETGUARD_REF =="
(cd "$SRC" && makepkg -si --noconfirm --needed)

if [[ "${1:-}" == "--setup" ]]; then
    netguard setup --trust-current --enable-service -y
fi
echo "netguard instalado: netguard status · netguard tui · docs: $SRC/docs"
