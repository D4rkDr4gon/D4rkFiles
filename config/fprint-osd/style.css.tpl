/* Generado en sus colores/radio/fuente por scripts/theme-switch.sh.
   Flat Minimal (docs/design-system.md): sin borde, radio único, tronco =
   superficie 2 de la rampa (chip_bluetooth), acento sólo como estado. El
   fondo/tipografía siguen a swayosd/style.css para que los dos OSD del
   sistema se lean como uno solo — este va centrado en vez de abajo. */
@define-color osd_bg @background@;
@define-color osd_fg @foreground@;
@define-color osd_accent @primary@;
@define-color osd_trough @chip_bluetooth@;
@define-color osd_ok @status_ok@;
@define-color osd_error @status_error@;

window#osd {
  border-radius: @radius@px;
  border: none;
  background: @osd_bg;
  font-family: "@font_mono@";
}

window#osd #container {
  margin: 28px 36px;
}

window#osd #icon {
  font-size: 46px;
  margin-bottom: 14px;
  color: @osd_fg;
}

window#osd #message {
  font-size: 14px;
  color: @osd_fg;
}

/* Esperando el dedo: el acento late sobre el tronco, sin animar el layout. */
window#osd #icon.scanning {
  color: @osd_accent;
  animation: pulse 1.6s ease-in-out infinite;
}

window#osd #icon.ok,
window#osd #message.ok {
  color: @osd_ok;
}

window#osd #icon.error,
window#osd #message.error {
  color: @osd_error;
}

@keyframes pulse {
  0%   { opacity: 1; }
  50%  { opacity: 0.45; }
  100% { opacity: 1; }
}
