/* Generado en sus colores/radio/fuente por scripts/theme-switch.sh.
   Flat Minimal (docs/design-system.md): sin borde, radio único, acento solo
   en la barra de progreso, tronco = superficie 2 de la rampa (chip_bluetooth). */
@define-color osd_bg @background@;
@define-color osd_fg @foreground@;
@define-color osd_accent @primary@;
@define-color osd_trough @chip_bluetooth@;

window#osd {
  border-radius: @radius@px;
  border: none;
  background: @osd_bg;
  font-family: "@font_mono@";
}

window#osd #container {
  margin: 16px;
}

window#osd image,
window#osd label {
  color: @osd_fg;
}

window#osd progressbar:disabled,
window#osd image:disabled {
  opacity: 0.5;
}

window#osd progressbar,
window#osd segmentedprogress {
  min-height: 6px;
  border-radius: @radius@px;
  background: transparent;
  border: none;
}

window#osd trough,
window#osd segment {
  min-height: inherit;
  border-radius: inherit;
  border: none;
  background: @osd_trough;
}

window#osd progress,
window#osd segment.active {
  min-height: inherit;
  border-radius: inherit;
  border: none;
  background: @osd_accent;
}

window#osd segment {
  margin-left: 8px;
}

window#osd segment:first-child {
  margin-left: 0;
}
