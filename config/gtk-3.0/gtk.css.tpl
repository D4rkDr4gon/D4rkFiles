/* ==========================================
   Temas dinámicos - Generado por theme-switch.sh
   Aplica a Thunar y aplicaciones GTK3
   ========================================== */

@define-color theme_bg @background@;
@define-color theme_fg @foreground@;
@define-color theme_primary @primary@;
@define-color theme_secondary @secondary@;
@define-color theme_selected_bg @primary@;
@define-color theme_selected_fg #ffffff;

/* ── Thunar ──────────────────────────────── */
.thunar {
  background-color: @theme_bg;
  color: @theme_fg;
}

.thunar .sidebar {
  background-color: shade(@theme_bg, 0.95);
  border-right: 1px solid shade(@theme_bg, 1.3);
}

.thunar .sidebar .view {
  background-color: shade(@theme_bg, 0.95);
  color: @theme_fg;
}

.thunar .sidebar .view:selected {
  background-color: @theme_primary;
  color: @theme_selected_fg;
}

.thunar .sidebar .view:selected:backdrop {
  background-color: shade(@theme_primary, 1.3);
}

.thunar .standard-view {
  background-color: @theme_bg;
}

.thunar .standard-view .view {
  background-color: @theme_bg;
  color: @theme_fg;
}

.thunar .standard-view .view:selected {
  background-color: @theme_primary;
  color: @theme_selected_fg;
}

.thunar .standard-view .view:selected:backdrop {
  background-color: shade(@theme_primary, 1.3);
}

.thunar .standard-view .view:active {
  background-color: shade(@theme_primary, 1.2);
}

.thunar .location-bar {
  background-color: shade(@theme_bg, 1.1);
  border-bottom: 1px solid shade(@theme_bg, 1.3);
}

.thunar .path-bar button {
  background-color: shade(@theme_bg, 1.2);
  color: @theme_fg;
  border: 1px solid shade(@theme_bg, 1.5);
}

.thunar .path-bar button:hover {
  background-color: shade(@theme_primary, 2.0);
}

.thunar .path-bar button:checked {
  background-color: @theme_primary;
  color: @theme_selected_fg;
}

/* ── Columnas de detalles ───────────────── */
treeview {
  background-color: @theme_bg;
  color: @theme_fg;
}

treeview:selected {
  background-color: @theme_primary;
  color: @theme_selected_fg;
}

treeview:selected:backdrop {
  background-color: shade(@theme_primary, 1.3);
}

treeview header button {
  background-color: shade(@theme_bg, 1.1);
  color: @theme_fg;
  border: 1px solid shade(@theme_bg, 1.3);
}

treeview header button:hover {
  background-color: shade(@theme_bg, 1.3);
}

/* ── Toolbar ─────────────────────────────── */
.thunar toolbar {
  background-color: shade(@theme_bg, 1.1);
  border-bottom: 1px solid shade(@theme_bg, 1.3);
}

.thunar toolbar button {
  background-color: transparent;
  color: @theme_fg;
}

.thunar toolbar button:hover {
  background-color: shade(@theme_bg, 1.5);
}

/* ── Scrollbars ──────────────────────────── */
scrollbar {
  background-color: shade(@theme_bg, 1.1);
}

scrollbar slider {
  background-color: @theme_primary;
  border-radius: 6px;
  min-width: 8px;
  min-height: 8px;
}

scrollbar slider:hover {
  background-color: @theme_secondary;
}

scrollbar slider:active {
  background-color: @theme_secondary;
}

/* ── Entries (búsqueda, location) ────────── */
entry {
  background-color: shade(@theme_bg, 1.3);
  color: @theme_fg;
  border: 1px solid shade(@theme_bg, 1.5);
}

entry:focus {
  border-color: @theme_primary;
}

/* ── Menús ───────────────────────────────── */
menu {
  background-color: shade(@theme_bg, 1.1);
  color: @theme_fg;
}

menu menuitem:hover {
  background-color: @theme_primary;
  color: @theme_selected_fg;
}

/* ── Notificaciones ──────────────────────── */
tooltip {
  background-color: shade(@theme_bg, 1.3);
  color: @theme_fg;
  border: 1px solid @theme_primary;
}
