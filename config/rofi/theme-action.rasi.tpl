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
    y-offset:       calc(50% - 100px);
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
    placeholder:        "Actions";
    placeholder-color:  @fg3;
}

listview {
    background-color:   transparent;

    margin:     12px 0 0;
    lines:      1;
    columns:    4;

    fixed-height: false;
    fixed-columns: true;
}

element {
    padding:        10px 6px;
    spacing:        8px;
    border-radius:  @radius@px;
    orientation:    vertical;
}

element selected normal, element selected active {
    background-color:   @bg2;
}

element-icon {
    size:           40px;
    vertical-align: 0.5;
}

element-text {
    text-color:     inherit;
    vertical-align: 0.5;
    horizontal-align: 0.5;
}
