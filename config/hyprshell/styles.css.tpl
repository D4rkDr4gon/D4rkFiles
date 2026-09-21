/* hyprshell — overview + Alt+Tab. Los valores de :root los reescribe
   scripts/theme-switch.sh (sed por nombre de variable); no cambiar los nombres.
   hyprshell recarga este archivo solo al guardarlo. */
:root {
    --border-color: @chip_bluetooth@;
    --border-color-active: @primary@;

    --bg-color: @background@;
    --bg-color-hover: @chip_battery@;

    --border-radius: @radius@px;
    --border-size: 2px;
    --border-style: solid;

    --text-color: @foreground@;

    --window-padding: 3px;
    --bg-window-color: @chip_battery@;
}

* {
    font-family: "@font_mono@";
}
