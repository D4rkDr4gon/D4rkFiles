# Skill de IA: `d4rkfiles`

`skills/d4rkfiles/` es una skill para **Claude Code** y **opencode** que le enseña al agente a
administrar tu escritorio: dónde está cada configuración, cómo cambiarla de forma segura y cómo
recargarla. Es la puerta de entrada; el detalle lo lee de estos mismos documentos.

## Qué le podés pedir

- "Cambiá al tema nord" · "creame un tema con estos colores" · "poné este wallpaper".
- "Agregá el atajo Super+O para abrir Obsidian" · "¿qué hace Super+K?".
- "Configurá mis dos monitores" · "cambiá el layout de teclado".
- "Instalá `foo`" · "actualizá el sistema" · "¿qué paquetes me faltan?".
- "Waybar no aparece" · "revisá mi instalación" · "volvé a mi config anterior".

## Cómo se instala

Lo hace `install.sh` en la etapa `links`, con dos enlaces del manifiesto:

| Herramienta | Enlace |
|---|---|
| Claude Code | `~/.claude/skills/d4rkfiles` → `skills/d4rkfiles` |
| opencode | `~/.config/opencode/skills/d4rkfiles` → `skills/d4rkfiles` |

opencode también lee `~/.claude/skills` y deduplica por nombre, así que no hay conflicto. No hace falta
configurar nada más: al abrir Claude Code u opencode, la skill aparece y se activa sola cuando el pedido
encaja con su descripción. Si instalás alguna de las dos herramientas **después** de los dotfiles,
corré `./install.sh --only links`. Para no instalarla: `./install.sh --no-skills`.

## Statusline y widget "Agentes IA"

El mismo paso configura la statusline de Claude Code (`config/claude/statusline-command.sh`, con los colores
del tema): se enlaza a `~/.claude/statusline-command.sh` y se agrega `statusLine` a `~/.claude/settings.json`
**solo si no tenés una**, con backup. Es la que alimenta el widget "Agentes IA" de waybar.

## Qué reglas le da

Las mismas que sigue el repo (ver [structure.md](structure.md) y [security.md](security.md)):

1. Si un archivo tiene `.tpl`, se edita el `.tpl` (el otro es generado).
2. Lo del usuario va en `~/.config/dotfiles/`, nunca dentro del repo.
3. Nada de rutas, nombres ni secretos hardcodeados.
4. Mira antes de tocar (`--dry-run`, `dotfiles-doctor`) y pide confirmación antes de `sudo`, instalar o
   quitar paquetes, tocar `/etc` o `/usr`, o hacer `git push`.
5. Recarga con el comando correcto de cada componente en vez de reiniciar el WM.

## Verificación y mantenimiento

`scripts/dotfiles-doctor.sh configs` valida que el `SKILL.md` tenga `name` (igual al directorio) y
`description` (máx. 1024 caracteres), y `links` que ambos enlaces existan. Si cambiás algo del repo que
afecte lo que la skill dice (un comando, una ruta, un paquete), actualizá `skills/d4rkfiles/`.
