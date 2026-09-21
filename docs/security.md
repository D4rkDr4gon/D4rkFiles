# Seguridad y datos personales

Este repo está pensado para ser **público y reutilizable**: no contiene credenciales,
rutas de usuario, nombres ni datos de una máquina concreta.

## Qué nunca se versiona

- Tokens, claves, contraseñas, certificados, perfiles VPN, configuración de servicios con
  autenticación (`.gitignore` bloquea `*.pem`, `*.key`, `*.ovpn`, `*.wg.conf`, `.env*`,
  `refresh_token`, `wayvnc/config`…).
- Tu `user.conf`, `local.zsh` y overrides de Hyprland (viven en `~/.config/dotfiles/`).
- Estado de aplicaciones (bases de datos, sesiones, caches).
- Archivos generados desde plantillas.

## Dónde van tus credenciales

| Qué | Dónde |
|---|---|
| Password de wayvnc | `~/.config/dotfiles/wayvnc/config` (permisos 600; lo crea `wayvnc-toggle.sh init`) |
| API keys (opencode, MCP…) | Variables de entorno (`{env:MI_API_KEY}` en `opencode.jsonc`), en tu `~/.zshenv` |
| VPN | Gestionada por NetworkManager (`nmcli`), no por archivos del repo |

## Cómo se verifica

- `scripts/dotfiles-doctor.sh repo`: busca archivos con nombre de secreto, patrones de
  credenciales conocidos, rutas absolutas de usuario y archivos versionados que `.gitignore`
  excluye.
- El CI corre las mismas comprobaciones en cada push (`.github/workflows/ci.yml`).

## Si se te cuela un secreto

1. **Revocá o rotá la credencial primero** (borrar el commit no alcanza: forks y clones la conservan).
2. `git rm --cached <archivo>` y agregalo a `.gitignore`.
3. Reescribí el historial (`git filter-repo --invert-paths --path <archivo>`) y forzá el push.
4. Si el repo fue público, asumí que la credencial ya estuvo expuesta.

## Cosas que el instalador NO toca sin preguntar

`/etc/pam.d/*` (el PAM de huella de SDDM es opt-in: `setup-sddm-theme.sh --with-fingerprint-pam`),
`/etc/sddm.conf.d`, `/usr/share/wayland-sessions`, tu shell por defecto y los servicios
opcionales (Ollama, webapps).
