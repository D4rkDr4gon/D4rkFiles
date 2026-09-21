# Instalación

Soporta **Arch Linux** (y derivadas con `pacman`). Instala dos sesiones: **Hyprland**
(Wayland) y **Qtile** (X11); podés elegir solo una.

## Una línea

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/D4rkDr4gon/D4rkFiles/main/install.sh)
```

Clona el repo en `~/D4rkFiles` (cambialo con `--dir`) y sigue con el instalador desde ahí.

## Desde un clone

```bash
git clone https://github.com/D4rkDr4gon/D4rkFiles.git
cd D4rkFiles
./install.sh --dry-run      # mira qué haría, sin modificar nada
./install.sh                # instala (pregunta lo opcional)
```

El repo puede estar en **cualquier ruta**: el instalador crea el symlink estable
`~/.local/share/dotfiles → <tu clone>` y todas las configs lo usan.

## Opciones

| Opción | Efecto |
|---|---|
| `-n`, `--dry-run` | Muestra cada comando sin ejecutarlo |
| `-y`, `--yes` | No pregunta; usa los valores por defecto (lo opcional queda en "no") |
| `--only a,b` / `--skip a,b` | Corre solo (o salta) esas etapas |
| `--configure` | Atajo de `--only configure`: crea `user.conf` y renderiza el tema |
| `--dir RUTA` | Dónde está o se clonará el repo |
| `--no-wayland` / `--no-x11` | Omite la sesión Hyprland / Qtile |
| `--no-aur` | No usa el AUR (ni instala `yay`) |
| `--no-upgrade` | No ofrece `pacman -Syu` antes de instalar |
| `--with-ollama` | Instala Ollama sin preguntar |
| `--no-skills` | No instala la skill `d4rkfiles` de Claude Code y opencode |
| `--list-stages` | Lista las etapas |

Una opción desconocida es un error (no se ignora en silencio).

## Etapas

Se ejecutan en este orden (`./install.sh --list-stages`):

1. **preflight** — valida Arch, que no sea root, y pide `sudo` una sola vez.
2. **packages** — `pacman -Syu` (opcional) y paquetes oficiales/AUR de `install/packages/`.
   Detecta la GPU con `lspci` (AMD/Intel/NVIDIA) y agrega solo lo que corresponde.
3. **configure** — crea `~/.config/dotfiles/user.conf` (pregunta nombre y título) y
   `~/.config/dotfiles/hypr/local.conf`, y renderiza el tema por defecto.
4. **links** — enlaces simbólicos de [`manifest/links.tsv`](../manifest/links.tsv), incluida la skill de IA ([ai-skill.md](ai-skill.md)).
5. **shell** — powerlevel10k, shell por defecto (pregunta) y plugins de Neovim (pregunta).
6. **system** — servicios, login manager, sesión "Hyprland (dotfiles)", unidades de
   usuario y grupos. Todo lo que toca `/etc` o `/usr` pregunta antes.
7. **optional** — Ollama y webapps (siempre opcionales).
8. **summary** — próximos pasos.

`configure` va antes de `links` porque renderiza las plantillas que luego se enlazan.

## Paquetes

Viven en `install/packages/`, un nombre por línea (`#` comenta):

| Archivo | Contenido |
|---|---|
| `base.txt`, `base.aur.txt` | Shell, terminal, audio, red, fuentes, iconos, TUIs |
| `hyprland.txt`, `hyprland.aur.txt` | Sesión Hyprland, waybar, gtklock, sddm, walker… |
| `x11.txt`, `x11.aur.txt` | Sesión Qtile: qtile, polybar, picom, feh… |
| `gpu-*.txt` | Espacio de usuario de la GPU detectada |

El CI verifica que cada nombre exista en los repos (o en el AUR para `*.aur.txt`).

## Qué pasa con tu configuración existente

Nada se borra. Cuando un destino ya existe (archivo, carpeta o symlink distinto), se mueve
a `~/.local/state/dotfiles/backups/<fecha>/` conservando la ruta relativa, y recién
entonces se crea el enlace. Volver atrás es un `mv`. Ejecutar el instalador dos veces es
seguro: los enlaces correctos no se tocan.

## Verificar y actualizar

```bash
scripts/dotfiles-doctor.sh      # enlaces, paquetes, servicios, configs, secretos
dotfiles-update                 # (alias) actualiza el sistema con snapshot previo
```

Ver [scripts.md](scripts.md).

## Desinstalar

Los backups tienen tus configs originales. Para volver: borrá los symlinks de
`~/.config/<app>` (apuntan al repo) y restaurá desde el backup con `mv`. El repo no
instala nada fuera de los paquetes, `~/.config`, `~/.local` y las entradas de sesión/SDDM.
