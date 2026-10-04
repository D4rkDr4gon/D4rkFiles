/* Widgets de escritorio — plantilla: scripts/theme-switch.sh la renderiza a
   style.css (no editar el generado). El daemon relee style.css en caliente.
   Flat Minimal (docs/design-system.md): sin bordes, radio único, tarjetas =
   superficie 1 de la rampa (chip_battery) sobre el wallpaper, trough =
   superficie 2 (chip_bluetooth), acento solo como relleno de estado. */
@define-color dw_bg @background@;
@define-color dw_card @chip_battery@;
@define-color dw_trough @chip_bluetooth@;
@define-color dw_hover @chip_wlan@;
@define-color dw_fg @foreground@;
@define-color dw_muted @text_muted@;
@define-color dw_accent @primary@;
@define-color dw_ok @status_ok@;
@define-color dw_warn @status_warn@;
@define-color dw_error @status_error@;

window#desktop-widgets {
  background: transparent;
  color: @dw_fg;
  font-family: "@font_ui_or_mono@";
}

#mono, .mono, .meter-label, .value {
  font-family: "@font_mono@";
}

/* ── Reloj ─────────────────────────────────── */
#clock-time {
  font-size: 96px;
  font-weight: 300;
  color: @dw_fg;
  text-shadow: 0 2px 12px alpha(@dw_bg, 0.8);
}

/* Layout en columna: reloj más chico, alineado al costado */
.compact #clock-time {
  font-size: 64px;
}

#clock-date {
  font-size: 18px;
  color: @dw_fg;
  text-shadow: 0 1px 8px alpha(@dw_bg, 0.9);
  margin-bottom: 18px;
}

/* ── Tarjetas ──────────────────────────────── */
.card {
  background: alpha(@dw_card, 0.88);
  border-radius: @radius@px;
  padding: 14px 16px;
  min-width: 280px;
}

.card-title {
  font-size: 11px;
  font-weight: bold;
  color: @dw_muted;
  margin-bottom: 8px;
}

.big {
  font-size: 26px;
  color: @dw_fg;
}

.text {
  font-size: 13px;
  color: @dw_fg;
}

/* Pomodoro: el tiempo grande */
.pomo-time {
  font-size: 40px;
}

/* Agenda: separación entre días */
.agenda-day {
  margin-top: 6px;
  margin-bottom: 2px;
}

.wicon {
  font-size: 20px;
}

.muted {
  font-size: 12px;
  color: @dw_muted;
}

.accent { color: @dw_accent; }
.ok { color: @dw_ok; }
.warn { color: @dw_warn; }
.error { color: @dw_error; }

/* ── Barras ────────────────────────────────── */
progressbar trough {
  background: @dw_trough;
  border-radius: @radius@px;
  min-height: 6px;
  border: none;
}

progressbar progress {
  background: @dw_accent;
  border-radius: @radius@px;
  min-height: 6px;
  border: none;
}

progressbar.ok progress { background: @dw_ok; }
progressbar.warn progress { background: @dw_warn; }
progressbar.error progress { background: @dw_error; }

/* ── Música ────────────────────────────────── */
#music-art {
  border-radius: @radius@px;
  margin-right: 12px;
}

.media-btn {
  background: transparent;
  border: none;
  box-shadow: none;
  color: @dw_fg;
  font-family: "@font_mono@";
  font-size: 18px;
  padding: 2px 10px;
  border-radius: @radius@px;
}

.media-btn:hover {
  background: @dw_hover;
}

/* Botón chico con texto (Ring del teléfono) */
.small-btn {
  background: @dw_trough;
  border: none;
  box-shadow: none;
  color: @dw_fg;
  font-size: 12px;
  padding: 2px 10px;
  border-radius: @radius@px;
}

.small-btn:hover {
  background: @dw_hover;
}

/* ── Todo ──────────────────────────────────── */
entry {
  background: @dw_trough;
  color: @dw_fg;
  border: none;
  box-shadow: none;
  border-radius: @radius@px;
  padding: 4px 10px;
  caret-color: @dw_accent;
}

.todo-item {
  padding: 3px 4px;
  border-radius: @radius@px;
}

.todo-item:hover {
  background: @dw_hover;
}

.todo-item.done label {
  color: @dw_muted;
}
