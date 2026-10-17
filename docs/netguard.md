# Zonas de red (netguard, opcional)

Las zonas de red las da **[netguard](https://github.com/D4rkDr4gon/netguard)**, un proyecto aparte: también se usa sin
D4rkFiles, en cualquier Arch con NetworkManager. D4rkFiles lo trae como **opcional** y lo integra en Settings.

La notebook cambia de protección según la red donde está: en casa todo anda como siempre; en un bar o un aeropuerto
la VPN es obligatoria y nada sale por fuera de ella. Además: detección de *evil twin*, DNS cifrado, IPv6 y
autoconexión apagados en redes inseguras, privacidad de MAC/IPv6, endurecimiento del kernel, puertos expuestos,
firewall por aplicación con OpenSnitch e historial de redes.

## Instalarlo

| Cómo | |
|---|---|
| Al instalar D4rkFiles | `./install.sh --with-netguard` (o responder que sí en la etapa `optional`) |
| Después | Settings → Firewall → Zones (o Network security): la primera fila lo instala |
| A mano | `scripts/install-netguard.sh --setup` |

`scripts/install-netguard.sh` baja netguard en la **versión fijada** (`NETGUARD_REF`, hoy `v1.0.0`) a
`~/.cache/dotfiles/netguard`, lo construye como paquete de pacman (`makepkg -si`, necesita `git` y `base-devel`) y con
`--setup` corre `netguard setup --trust-current --enable-service`: helper con root y policy de polkit, las redes
conectadas en ese momento como de confianza y el servicio de usuario `netguard.service`. Desde Settings, además,
firewalld permite KDE Connect, mDNS y VNC en la zona `home`.

Para actualizar netguard: subir `NETGUARD_REF` y volver a correr el script. Sin netguard, D4rkFiles funciona igual:
Zones y Network security muestran una fila para instalarlo y Bluetooth/USB no piden nada extra.

## Integración con Settings

Settings **no tiene lógica propia** de netguard: lee con `netguard … --json` y cambia con sus comandos
(`tools/settings/sections/ngapi.py`), así que hace exactamente lo mismo que su CLI y su TUI.

| Sección | Qué muestra | Comandos de netguard |
|---|---|---|
| Firewall → **Zones** (`v` alterna con Rules) | Modo, kill switch, bypass/portal cautivo, último error, daemon; redes conocidas; pool de VPN | `status`, `net list`, `pool list`; `mode`, `killswitch`, `bypass`, `captive`, `net trust/untrust/forget/rule`, `pool add/remove/move/use/import`, `setup` |
| **Network security** | Hardening (opciones, archivos de sistema, access points), Ports, App firewall (OpenSnitch), History | `config list/set`, `harden`, `ap list/forget`, `ports`, `apps …`, `history` |
| Fila **netguard TUI** (Zones) | La TUI de netguard, con la misma estética | `netguard tui` |

Lo que baja la protección lo autentica netguard (agente de polkit: huella o contraseña); lo que usa sudo (setup,
`harden`, `apps install/apply`, parar un servicio) suspende Settings y corre en la terminal.

Bluetooth (Settings) y USB (`scripts/usbguard-notify.py`) usan `netguard gate`: en una red insegura piden huella o
contraseña antes de conectar o permitir un dispositivo; en una segura, o sin netguard, dejan pasar.

## Apagado de emergencia

```bash
netguard off
```

Desarma el kill switch y apaga las zonas; no pide nada y funciona aunque el daemon esté trabado. Si polkit no
responde: `sudo nft delete table inet netguard`.

## Documentación de netguard

Todo lo demás (conceptos, CLI, TUI, configuración, VPN, endurecimiento, OpenSnitch, modelo de seguridad, solución de
problemas) está en [su documentación](https://github.com/D4rkDr4gon/netguard/tree/main/docs). Una copia queda
instalada en `/usr/share/doc/netguard/`.
