#!/usr/bin/env python3
"""OSD centrado para la autenticación por huella (fprintd).

Escucha las señales D-Bus del system bus que emite fprintd y muestra un OSD
en el centro de la pantalla mientras el sensor espera el dedo — el mismo rol
que swayosd cumple para volumen/brillo, pero para `sudo`, la pantalla de
bloqueo y cualquier otro consumidor de pam_fprintd.

No toca PAM: las señales `VerifyFingerSelected` (inicio) y `VerifyStatus`
(reintento/fin) son broadcast y la policy de D-Bus las deja recibir a
cualquier usuario, así que el daemon corre sin privilegios en la sesión.

Estilo: ~/.config/fprint-osd/style.css (lo regenera scripts/theme-switch.sh).
"""

import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Gdk  # noqa: E402

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
except ValueError:
    # La typelib existe pero la .so todavía no está cargada en el proceso.
    import ctypes

    ctypes.CDLL("libgtk-layer-shell.so.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell  # noqa: E402

FPRINT_BUS = "net.reactivated.Fprint"
FPRINT_IFACE = "net.reactivated.Fprint.Device"

STYLE_PATH = os.path.join(
    GLib.get_user_config_dir(), "fprint-osd", "style.css"
)

# Glifos Nerd Font (la fuente la fija el CSS, tematizada por theme-switch.sh).
ICON_SCAN = "\U000f0237"   # nf-md-fingerprint
ICON_OK = "\U000f05e0"     # nf-md-check_circle_outline
ICON_ERROR = "\U000f05d6"  # nf-md-close_circle_outline

# Cuánto queda el OSD tras el resultado final, en ms.
HIDE_AFTER_OK = 900
HIDE_AFTER_ERROR = 1400
# Red de seguridad: pam_fprintd corta a los 30s; si el proceso que pidió la
# verificación muere sin emitir VerifyStatus, el OSD no puede quedar colgado.
WATCHDOG = 32000

# Resultados de VerifyStatus que llegan con done=false: el sensor sigue
# esperando, sólo cambia el texto.
RETRY_MESSAGES = {
    "verify-retry-scan": "Intentá de nuevo",
    "verify-swipe-too-short": "Pasá el dedo más despacio",
    "verify-finger-not-centered": "Centrá el dedo",
    "verify-remove-and-retry": "Levantá el dedo y volvé a apoyarlo",
}

# Resultados finales (done=true).
FINAL_MESSAGES = {
    "verify-match": (ICON_OK, "Autenticado", "ok"),
    "verify-no-match": (ICON_ERROR, "Huella no reconocida", "error"),
    "verify-disconnected": (ICON_ERROR, "Sensor desconectado", "error"),
    "verify-unknown-error": (ICON_ERROR, "Error del sensor", "error"),
}


class FprintOSD:
    def __init__(self):
        self.hide_timer = None
        self.watchdog_timer = None
        self._build_window()
        self._load_style()
        self._watch_style()
        self._subscribe()

    # ---------------------------------------------------------------- UI

    def _build_window(self):
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_name("osd")

        GtkLayerShell.init_for_window(self.window)
        GtkLayerShell.set_namespace(self.window, "fprint-osd")
        GtkLayerShell.set_layer(self.window, GtkLayerShell.Layer.OVERLAY)
        # Sin anchors en ningún borde = centrado por el compositor.
        GtkLayerShell.set_keyboard_mode(
            self.window, GtkLayerShell.KeyboardMode.NONE
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_name("container")

        self.icon = Gtk.Label(label=ICON_SCAN)
        self.icon.set_name("icon")
        self.label = Gtk.Label(label="Apoyá tu huella")
        self.label.set_name("message")

        box.pack_start(self.icon, False, False, 0)
        box.pack_start(self.label, False, False, 0)
        self.window.add(box)
        box.show_all()

    def _load_style(self):
        if not os.path.exists(STYLE_PATH):
            return
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(STYLE_PATH)
        except GLib.Error as err:
            print(f"fprint-osd: CSS inválido: {err}", file=sys.stderr)
            return
        if getattr(self, "provider", None) is not None:
            Gtk.StyleContext.remove_provider_for_screen(
                Gdk.Screen.get_default(), self.provider
            )
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )
        self.provider = provider

    def _watch_style(self):
        """Releer el CSS cuando theme-switch.sh lo reescribe (sin reiniciar)."""
        try:
            gfile = Gio.File.new_for_path(STYLE_PATH)
            self.style_monitor = gfile.monitor_file(
                Gio.FileMonitorFlags.NONE, None
            )
            self.style_monitor.connect(
                "changed", lambda *_: self._load_style()
            )
        except GLib.Error:
            self.style_monitor = None

    def _set_state(self, icon, message, css_class):
        for widget in (self.icon, self.label):
            ctx = widget.get_style_context()
            for old in ("scanning", "ok", "error"):
                ctx.remove_class(old)
            ctx.add_class(css_class)
        self.icon.set_label(icon)
        self.label.set_label(message)

    def show(self, icon, message, css_class):
        self._cancel(("hide_timer",))
        self._set_state(icon, message, css_class)
        self.window.show()
        self._arm_watchdog()

    def hide(self):
        self._cancel(("hide_timer", "watchdog_timer"))
        self.window.hide()
        return GLib.SOURCE_REMOVE

    def hide_after(self, delay):
        self._cancel(("hide_timer", "watchdog_timer"))
        self.hide_timer = GLib.timeout_add(delay, self.hide)

    def _arm_watchdog(self):
        self._cancel(("watchdog_timer",))
        self.watchdog_timer = GLib.timeout_add(WATCHDOG, self.hide)

    def _cancel(self, names):
        for name in names:
            timer = getattr(self, name, None)
            if timer is not None:
                GLib.source_remove(timer)
                setattr(self, name, None)

    # ------------------------------------------------------------- D-Bus

    def _subscribe(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.bus.signal_subscribe(
            FPRINT_BUS, FPRINT_IFACE, "VerifyFingerSelected", None, None,
            Gio.DBusSignalFlags.NONE, self._on_verify_started,
        )
        self.bus.signal_subscribe(
            FPRINT_BUS, FPRINT_IFACE, "VerifyStatus", None, None,
            Gio.DBusSignalFlags.NONE, self._on_verify_status,
        )

    def _on_verify_started(self, *args):
        self.show(ICON_SCAN, "Apoyá tu huella", "scanning")

    def _on_verify_status(self, _conn, _sender, _path, _iface, _sig, params):
        result, done = params.unpack()
        if not done:
            self.show(
                ICON_SCAN,
                RETRY_MESSAGES.get(result, "Intentá de nuevo"),
                "scanning",
            )
            return
        icon, message, css_class = FINAL_MESSAGES.get(
            result, (ICON_ERROR, "Error del sensor", "error")
        )
        self._set_state(icon, message, css_class)
        self.window.show()
        self.hide_after(HIDE_AFTER_OK if css_class == "ok" else HIDE_AFTER_ERROR)


def main():
    if os.environ.get("WAYLAND_DISPLAY") is None:
        print("fprint-osd: requiere una sesión Wayland", file=sys.stderr)
        return 1
    Gtk.init(None)
    FprintOSD()
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
