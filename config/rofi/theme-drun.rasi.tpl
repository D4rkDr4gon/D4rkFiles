@import "colors.rasi"

* {
    background-color:   transparent;
    text-color:         @fg0;

    margin:     0px;
    padding:    0px;
    spacing:    0px;
}

window {
    location:       center;
    y-offset:       0;
    width:          520;
    border-radius:  @radius@px;

    background-color:   @bg0;
}

mainbox {
    padding:    12px;
}

inputbar {
    background-color:   @bg1;

    border-radius:  @radius@px;

    padding:    6px 10px;
    spacing:    8px;
    children:   [ prompt, entry ];
}

prompt {
    text-color: @fg2;
}

entry {
    placeholder:        "Buscar apps, comandos, cálculos...";
    placeholder-color:  @fg3;
}

message {
    margin:             12px 0 0;
    border-radius:  @radius@px;
    background-color:   @bg1;
}

/* Lista vertical de una sola columna, máximo 5 filas visibles en reposo
 * (recientes/más usados, vía el historial nativo de rofi) — reemplaza la
 * grilla de íconos 5x4 anterior, unificando el layout con theme.rasi y con
 * el resto del sistema (regla Flat Minimal: fila = chip, sin marco). */
listview {
    background-color:   transparent;

    margin:     12px 0 0;
    lines:      5;
    columns:    1;

    fixed-height: false;
}

element {
    padding:        6px 10px;
    spacing:        8px;
    border-radius:  @radius@px;
    orientation:    horizontal;
}

element normal active {
    text-color: @bg3;
}

element alternate active {
    text-color: @bg3;
}

element selected normal, element selected active {
    background-color:   @bg2;
}

element-icon {
    size:           1.4em;
    vertical-align: 0.5;
}

element-text {
    text-color:         inherit;
    vertical-align:     0.5;
    horizontal-align:   0;
}
