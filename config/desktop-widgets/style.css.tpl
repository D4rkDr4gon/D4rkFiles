/* Widgets de escritorio — plantilla: scripts/theme-switch.sh la renderiza a
   style.css (no editar el generado). El daemon relee style.css en caliente.
   Misma estética que las TUIs propias (dtui.py, "TUIs propias" en
   docs/design-system.md): tarjeta = Panel (fondo background, borde redondeado
   en `border` con el título incrustado, borde y título en primary con el mouse
   encima), todo en monoespaciada, barras de bloques ▓░ como meter10, filas
   con hover en chip_battery como el cursor de una Table. */
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
/* Borde de los paneles: hex_blend(foreground, background, 22) de dtui.py */
@define-color dw_border mix(@dw_bg, @dw_fg, 0.22);

window#desktop-widgets {
  background: transparent;
  color: @dw_fg;
  font-family: "@font_mono@";
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

/* ── Tarjetas = Panel de las TUIs ──────────── */
/* Fondo y borde los dibuja Card en desktop-widgets.py (con el hueco del
   título, como Textual) con dw_bg, dw_border y dw_accent; de acá toma solo el
   radio. `.hover` = mouse encima (el panel con foco de una TUI). */
.card {
  background: transparent;
  border-radius: @radius@px;
}

.card-title {
  font-size: 13px;
  font-weight: bold;
  color: @dw_muted;
  margin-left: 10px;
  text-shadow: 0 1px 4px alpha(@dw_bg, 0.9);
}

.card.hover .card-title {
  color: @dw_accent;
}

.card-body {
  padding: 2px 14px 12px 14px;
  min-width: 260px;
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

/* Agenda: un día = fila de grupo de una Table (negrita, apagada) */
.agenda-day {
  font-size: 12px;
  font-weight: bold;
  color: @dw_muted;
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

/* ── Barras de texto (▓▓▓░░░, como meter10) ── */
.bar-full, .bar-empty {
  font-size: 13px;
}

.bar-empty {
  color: @dw_border;
}

/* ── Música ────────────────────────────────── */
#music-art {
  margin-right: 12px;
}

/* Botones: solo el glifo, en primary con el mouse encima */
.media-btn {
  background: transparent;
  border: none;
  box-shadow: none;
  color: @dw_fg;
  font-family: "@font_mono@";
  font-size: 18px;
  padding: 2px 10px;
}

.media-btn:hover {
  background: transparent;
  color: @dw_accent;
}

/* Botón con texto (Ring, Open expenses): un panel chico */
.small-btn {
  background: transparent;
  border: 1px solid @dw_border;
  box-shadow: none;
  color: @dw_fg;
  font-size: 12px;
  padding: 1px 10px;
  border-radius: @radius@px;
}

.small-btn:hover {
  background: transparent;
  border-color: @dw_accent;
  color: @dw_accent;
}

/* ── Todo ──────────────────────────────────── */
/* Como el Input de las TUIs: superficie 1, superficie 3 con foco */
entry {
  background: @dw_card;
  color: @dw_fg;
  border: none;
  box-shadow: none;
  border-radius: 0;
  padding: 2px 8px;
  caret-color: @dw_accent;
}

entry:focus {
  background: @dw_hover;
}

/* Filas: hover = cursor de una Table (chip_battery), sin redondeo */
.todo-item {
  padding: 1px 4px;
  border-radius: 0;
}

.todo-item:hover {
  background: @dw_card;
}

.todo-item.done label {
  color: @dw_muted;
}
