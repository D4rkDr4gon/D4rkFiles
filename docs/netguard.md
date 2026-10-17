# Zonas de red — modo seguro / inseguro (opcional)

Settings → **Firewall**, pestaña **Zones** (`v` alterna con **Rules**, las reglas
de firewalld de siempre). La notebook cambia de protección según la red donde está: en casa todo
anda como siempre; en un bar o un aeropuerto la VPN es obligatoria y nada sale por fuera de ella.

## Los dos modos

| | Seguro (redes de confianza) | Inseguro (cualquier otra) |
|---|---|---|
| VPN | Opcional | **Obligatoria**: se conecta sola la primera WireGuard del pool que levante (failover a la siguiente; reintenta cada 60 s) y **recién con la VPN arriba** se arma el kill switch |
| Tráfico sin VPN | Normal | Bloqueado. Solo salen túneles (WireGuard, tun, ppp), loopback, DHCP, descubrimiento IPv6 y los endpoints del pool para poder conectar |
| firewalld | Zona `home` en la conexión (KDE Connect, mDNS, VNC 5900) | Zona `drop`: nada entrante |
| Descubrimiento | Avahi, mDNS/LLMNR, kdeconnectd | Avahi parado, mDNS/LLMNR off en la conexión, kdeconnectd y wayvnc parados |
| DHCP | Manda el nombre del equipo | No lo manda |
| DNS | El de la red | Solo el de la VPN (`dns-priority -50` en las VPN del pool; el kill switch corta el resto: sin fugas) |
| Bluetooth | Libre | No emparejable ni visible; conectar o emparejar desde Settings (o abrir bluetui) pide huella o contraseña |
| USB (USBGuard) | Se permite desde la notificación | Permitir pide huella o contraseña |

**Nunca deja sin red**: primero la VPN, después el bloqueo.
- El kill switch se arma **solo con una VPN del pool conectada**. Si ninguna levanta (o el pool está vacío), **no bloquea**:
  avisa "No VPN could connect" / "no VPN in the pool" (el tráfico NO está protegido) y reintenta cada minuto.
- Si la VPN se cae con el kill switch puesto, sigue bloqueando mientras reconecta (sin fuga) hasta **45 s**
  (`VPN_GRACE`); si no vuelve, lo suelta y avisa "VPN down: traffic NOT protected".
- Armar y desarmar se verifican: si `pkexec` falla, el estado sigue siendo el real, se reintenta y se avisa una vez.
- El estado real sale de `/run/netguard/armed` (la escribe el helper, se lee sin root): el daemon y Settings no
  adivinan ni consultan a root en cada vuelta. En una red segura, si por lo que sea quedó armado, se desarma.

**Regla de autenticación**: lo que **sube** la protección no pide nada y es automático. Lo que la
**baja** a mano pide huella o contraseña (agente de polkit):
- marcar una red como de confianza;
- poner el modo seguro a mano;
- apagar las zonas o el kill switch;
- abrir un bypass.

Volver a una red ya marcada como de confianza no pide nada: la confianza se autenticó al marcarla.

## Apagado de emergencia

`scripts/netguard.py off` (en `~/.local/share/dotfiles/`) desarma el kill switch, devuelve Avahi y deja `enabled=off`. Funciona
siempre: no pide huella, no necesita Settings y anda aunque el daemon esté trabado.

## Cómo decide

`scripts/netguard.py daemon` (exec-once) mira cada 3 s, por D-Bus, las conexiones físicas activas de
NetworkManager (Wi-Fi, cable, módem):
- **Seguro**: todas están marcadas `trusted` en `~/.config/dotfiles/netguard/networks.conf`.
- **Inseguro**: alguna es `untrusted` o **nueva**. Una red nueva entra como insegura y llega una
  notificación "New network" con **Trusted** (pide huella) / **Untrusted** (click del medio en dunst).
- `auto=off` fija el modo a mano (Settings → Mode).

Sin red se mantiene el último modo.

**Reglas por nombre**: además del uuid, `networks.conf` acepta `name:<prefijo>=trusted|untrusted`. Cubre las
redes cuyo nombre de conexión empieza con ese prefijo, sin distinguir mayúsculas (`name:Cafe` abarca
"Cafe - Centro" y "CAFE-5G"). El uuid manda sobre las reglas, y entre reglas
gana el prefijo más largo. Sirve para los perfiles duplicados que NetworkManager crea con otro uuid.

## Estado inicial

Viene **apagado** (`enabled=off`): hasta correr el Setup (fila *Set up*, con sudo) el daemon no bloquea ni cambia nada y
todo funciona como en modo seguro. Después de instalarlo, empezá con `auto=off`, `manual_mode=safe` y `killswitch=off` y
probalo con una VPN ya cargada en el pool antes de pasar a modo automático.

## Estado y diagnóstico

- Settings → Firewall → Zones muestra el modo, el kill switch real (armado, VPN reconectando, **no bloqueando** porque no
  hay VPN, bypass), firewalld parado (en red insegura sin firewalld no se bloquea lo entrante) y el **último error**
  (`enter` abre el log).
- Log: `~/.local/state/dotfiles/netguard/netguard.log` (cambios de modo, VPN, armado/desarmado, errores). Se recorta solo.
- **Helper desactualizado**: el helper v2 (marca de armado, bypass que se cancela al desarmar) se instala repitiendo el
  Setup (fila *Set up again*). Repetirlo no toca las redes de confianza ni el pool. Después, reiniciar el daemon.

## Endurecimiento de red (Settings → Network security)

Completa a las zonas. Cuatro páginas (`tab` o `1`-`4`): **Hardening**, **Ports**, **App firewall** e **History**.
Bajar la protección pide huella o contraseña, igual que en Zones.

### Lo que aplica el daemon a cada conexión física

Se guarda el valor original de cada propiedad (`orig` en `state.json`) y al apagar las zonas se restaura tal cual.

| Opción (`netguard.conf`) | Qué hace |
|---|---|
| `dns=off\|opportunistic\|strict` | DNS over TLS por conexión (`connection.dns-over-tls`). `strict` usa Quad9 con TLS en todas las redes e ignora el DNS de la red (los nombres locales del router dejan de resolver). Durante un bypass vuelve al DNS de la red: el portal cautivo lo necesita |
| `ipv6_unsafe=off` | IPv6 apagado (`ipv6.method disabled`) en las conexiones que no son de confianza: sin fugas si la VPN es solo IPv4 y sin dirección que te identifique |
| `autoconnect_unsafe=off` | Una red insegura o nueva no se reconecta sola. `autoconnect` no se puede reaplicar con la conexión activa: queda pendiente (`pending`) y se guarda en el perfil cuando se desconecta |
| `ap_check=on` | **Evil twin**: la primera vez en cada red de confianza por Wi-Fi se aprende su access point (BSSID y nivel de seguridad, en `aps.conf`). Otro BSSID (que no sea otra banda del mismo router: mismos 5 primeros octetos) o menos seguridad (WPA3 → WPA2 → WEP/OWE → abierta) la vuelven **insegura** y avisa; "It is my network" (con huella) suma el access point |
| `ports_warn=on` | En una red insegura sin firewalld, avisa una vez por cada puerto que escucha fuera de loopback |

### Lo que se instala una vez (sudo)

| Fila | Archivo | Qué hace |
|---|---|---|
| Kernel network hardening | `system/netguard/sysctl.conf` → `/etc/sysctl.d/90-netguard.conf` | Sin redirects ICMP ni source routing, `rp_filter` loose (el estricto rompe WireGuard/Tailscale), martians al log, SYN cookies, RFC 1337. Al sacarlo, los valores vuelven al reiniciar |
| MAC & IPv6 privacy | `nm-privacy.conf` → `/etc/NetworkManager/conf.d/90-netguard-privacy.conf` y, con el backend iwd, `iwd-main.conf` → `/etc/iwd/main.conf` (solo si no hay uno propio) | Una MAC por red, fija en cada una (`stable` / `AddressRandomization=network`): ninguna red te relaciona con otra y el router de casa te sigue reconociendo. MAC aleatoria al escanear. IPv6 con direcciones temporales. Rige desde la próxima conexión; instalarlo reinicia iwd (el Wi-Fi se reconecta). Si el router reserva IPs o filtra por MAC, actualizarlo |

### Ports

Lo que escucha fuera de loopback (`ss -tulnp`) con el proceso y su unidad de systemd, y si está expuesto: bloqueado por
la zona `drop`, decidido por firewalld (zona `home`) o **alcanzable** sin firewalld. `enter` sobre un servicio del sistema
lo para y lo deshabilita (sudo).

### App firewall (OpenSnitch)

Firewall por aplicación con [OpenSnitch](https://github.com/evilsocket/opensnitch) (`extra/opensnitch`; la primera fila lo
instala). Las reglas se arman desde **listas dinámicas**:
- `a` regla de app: elegís de lo que **usa la red ahora** (`ss -tunap`) o de las **apps instaladas** (`.desktop` → binario
  real), o escribís la ruta. Acción `deny`/`allow` y, opcional, solo para un sitio.
- `s` regla de sitio: elegís de los dominios de **Firefox** (historial, o marcadores si el historial está apagado; se lee
  una copia) o escribís uno. Vale para el dominio y sus subdominios, en todas las apps o en una.
- `enter` prende/apaga, `x` alterna allow/deny, `d` borra, `D` la acción por defecto para lo que no tiene regla.
- `A` aplica (sudo): escribe `/etc/opensnitchd/rules/netguard-*.json` (borra los anteriores de netguard; las reglas
  ajenas no se tocan) y reinicia opensnitchd.

La fuente es `~/.config/dotfiles/netguard/opensnitch.json`. Por defecto lo que no tiene regla **se permite**. Pasar a `deny` agrega reglas
allow para lo esencial (resolved, NetworkManager, timesyncd, pacman, curl, iwd); sumá el navegador antes de aplicar.
**Escape** si algo deja de salir: `sudo systemctl stop opensnitchd` (sin el daemon no filtra nada).

### History

`~/.local/state/dotfiles/netguard/history.jsonl`: redes que aparecen y se van (con su BSSID y confianza), cambios de modo, VPN
arriba/abajo, kill switch, avisos y access points aprendidos o sospechosos. `enter` muestra el evento, `c` lo borra.

## VPN de respaldo "stealth" (OpenVPN TCP 443)

Hay redes (hoteles, empresas) que bloquean WireGuard. En el panel **VPN pool** de Zones, `i` importa un `.ovpn` (por
ejemplo uno de Proton por TCP 443) a NetworkManager (`networkmanager-openvpn`) y lo suma al pool como `ovpn:<nombre>`.
El failover prueba primero todas las WireGuard y después las OpenVPN; sus servidores también entran como endpoints del
kill switch. Si NetworkManager pide usuario y contraseña, guardalos en la conexión.

## Cambiar de VPN (pool)

Panel **VPN pool**:
- `enter` usa esa VPN ahora;
- `p` la mete o saca del pool;
- `K`/`J` cambian el orden (el orden es la preferencia del failover).

| Tipo | En el pool | Se conecta |
|---|---|---|
| WireGuard / Proton (conexiones de NetworkManager) | su nombre | Sola. Al cambiar, el daemon baja la anterior y sube la nueva con el kill switch armado: no hay hueco sin cifrar |
| Forti | `forti:<perfil>` | A mano (usuario/contraseña o SAML). Con el kill switch armado, `enter` abre un bypass autenticado y lleva a Settings → VPN |
| Citrix | `citrix` | A mano: `enter` abre el bypass y el login del portal en el navegador |

Forti y Citrix cuentan como protección mientras están conectadas. Si son split-tunnel, el resto del
tráfico sigue bloqueado (es lo seguro). Ojo con la secuencia Forti → Citrix: el DNS de Forti puede
romper Citrix; `systemctl restart systemd-resolved` lo arregla.

## Bypass y portal cautivo

Las redes de hotel o aeropuerto piden loguearse en una página antes de dar internet, y el login SAML
de Forti/Citrix necesita web antes del túnel:
- **Captive portal** desarma el kill switch `bypass_secs` (120 s por defecto) y abre `http://neverssl.com`.
- **Bypass** hace lo mismo sin abrir el navegador.

Los dos piden huella. Al vencer se rearma solo: un timer de systemd que deja programado el helper. Desarmar (volver a
una red segura, apagar las zonas o el kill switch) **cancela el bypass y su timer**: antes, volver a casa durante un
bypass dejaba el rearmado pendiente y bloqueaba la red de casa.

## Piezas

| Pieza | Qué es |
|---|---|
| `~/.config/dotfiles/netguard/netguard.conf` | Config (fuera del repo): `enabled`, `auto`, `manual_mode`, `killswitch`, `pool`, `bypass_secs` |
| `~/.config/dotfiles/netguard/aps.conf` | Access points conocidos de cada red de confianza: `<uuid>=<seguridad> <bssid>...` (los escribe el daemon; se olvidan en Network security) |
| `~/.config/dotfiles/netguard/opensnitch.json` | Reglas de OpenSnitch armadas en Network security → App firewall (fuente; `A` las instala) |
| `system/netguard/sysctl.conf`, `nm-privacy.conf`, `iwd-main.conf` | Archivos de sistema que instala Network security → Hardening (sudo) |
| `~/.config/dotfiles/netguard/networks.conf` | Redes conocidas: `<uuid de NM>=trusted\|untrusted  # nombre` y reglas `name:<prefijo>=trusted\|untrusted` |
| `scripts/netguard.py` | Daemon de usuario (exec-once de Hyprland) + CLI (`status`, `request vpn <entrada>`, `bypass [s]`, `captive`, `off`). Estado en `~/.local/state/dotfiles/netguard/state.json` (Settings lo lee); los pedidos de Settings van por `request.json` |
| `system/netguard/netguard-root` | Helper con root, en Python `-I`. Settings lo instala en `/usr/local/lib/netguard/` (root:root): **nunca se ejecuta nada del repo como root**. Valida cada argumento. Kill switch = tabla nftables propia `inet netguard` (output, prioridad -10, policy drop), que convive con firewalld; Avahi on/off; bypass con rearmado |
| `system/netguard/apply`, `auth` | Wrappers de pkexec: `apply` sin contraseña (lo usa el daemon), `auth` pide huella/contraseña (`check` y `bypass`) |
| `system/netguard/org.dotfiles.netguard.policy` | Policy de polkit para los dos wrappers |
| `system/netguard/polkit-1.pam` | `/etc/pam.d/polkit-1` con `pam_fprintd` (huella en el agente). Solo se instala si hay `fprintd` y no existe ya un `polkit-1` propio |
| `hyprpolkitagent` | Agente de polkit (exec-once `systemctl --user start hyprpolkitagent`) |

**Setup** (fila Set up, una vez, con sudo):
- instala lo de arriba;
- prende firewalld con la zona `home` permitiendo KDE Connect, mDNS y 5900/tcp;
- marca como de confianza las redes conectadas en ese momento;
- pone `dns-priority -50` en las WireGuard;
- arma el pool con ellas.

Hasta el Setup, `enabled=off` y el daemon no toca nada.

Limitación: el bloqueo por proximidad del teléfono no funciona en modo inseguro porque kdeconnectd
queda parado (anuncia el equipo en la red).

## Qué protege y qué no

Protege de:
- redes hostiles: tráfico en claro, fugas de DNS, servicios expuestos, anuncios de mDNS y KDE Connect, el nombre del equipo en DHCP;
- emparejamientos o USB enchufados sin que te enteres.

No protege de un programa malicioso que ya corre con tu usuario: puede editar `networks.conf`, y el
wrapper `apply` acepta desarmar sin contraseña porque el daemon lo necesita para volver a casa. La
autenticación es una barrera contra errores y contra quien usa la notebook desbloqueada, no contra
malware local.

## Probar sin tocar la red

- **Kill switch**: `ruleset()` de `netguard-root` cargado en un namespace sin privilegios (`unshare -rn`),
  con una dummy `eth0` y una tun `wg0`. Se compara el contador de drop antes y después de cada ping:
  pasan endpoints, túnel y loopback; internet, LAN e IPv6, no.
- **Daemon**: `Guard.tick()` con un `NM` falso (conexiones en memoria), `root_apply`/`notify`/`nmcli` y el reloj
  reemplazados, `ARMED_FLAG` en un temporal y `NETGUARD_CONF_DIR`/`NETGUARD_STATE` en el scratchpad. Escenarios: casa →
  red nueva (conecta la VPN y recién después arma) → VPN caída (gracia y suelta) → vuelve → casa (desarma) → rearmado
  tardío en casa (lo quita) → desarmar/armar que fallan → pool vacío → apagar tras reiniciar el daemon (restaura todo).
- **Helper**: `killswitch_on`/`bypass`/`killswitch_off`/`rearm` en `unshare -rn` con `RUN` en un temporal y
  `systemctl` reemplazado.
- **Settings**: `ViewApp(FirewallView).run_test()` con las mismas variables y un `state.json` armado a mano.
