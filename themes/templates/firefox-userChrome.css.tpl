/* Generado por theme-switch.sh — no editar a mano */
:root {
  --lwt-accent-color: @background@ !important;
  --lwt-text-color: @foreground@ !important;
  --toolbar-bgcolor: @background@ !important;
  --toolbar-color: @foreground@ !important;
  --toolbar-field-background-color: @chip_bluetooth@ !important;
  --toolbar-field-color: @foreground@ !important;
  --toolbar-field-border-color: transparent !important;
  --toolbar-field-focus-background-color: @chip_wlan@ !important;
  --toolbar-field-focus-color: @foreground@ !important;
  --toolbar-field-focus-border-color: @primary@ !important;
  --tab-selected-bgcolor: @chip_wlan@ !important;
  --tab-selected-textcolor: @foreground@ !important;
  --tab-loading-fill: @primary@ !important;
  --tabs-border-color: @chip_bluetooth@ !important;
  --arrowpanel-background: @chip_battery@ !important;
  --arrowpanel-color: @foreground@ !important;
  --arrowpanel-border-color: @chip_bluetooth@ !important;
  --arrowpanel-dimmed: @chip_bluetooth@ !important;
  --sidebar-background-color: @background@ !important;
  --sidebar-text-color: @foreground@ !important;
  --sidebar-border-color: @chip_bluetooth@ !important;
  --urlbarView-highlight-background: @chip_wlan@ !important;
  --urlbarView-highlight-color: @foreground@ !important;
  --autocomplete-popup-background: @chip_battery@ !important;
  --autocomplete-popup-color: @foreground@ !important;
  --autocomplete-popup-highlight-background: @chip_wlan@ !important;
  --autocomplete-popup-highlight-color: @foreground@ !important;
  --focus-outline-color: @primary@ !important;
}
/* Barra superior, pestañas y sidebar (pestañas verticales) del mismo color */
#navigator-toolbox,
#TabsToolbar,
#nav-bar,
#PersonalToolbar,
#sidebar-main,
#sidebar-box,
#sidebar-header {
  background-color: @background@ !important;
}
.tabbrowser-tab:hover:not([selected]) .tab-background {
  background-color: @chip_bluetooth@ !important;
}
