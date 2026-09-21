@import "colors.rasi"

* {
    background-color:   transparent;
    text-color:         @fg0;

    margin:     0px;
    padding:    0px;
    spacing:    0px;
}

window {
    location:       north;
    y-offset:       calc(50% - 176px);
    width:          480;
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
    placeholder:        "Search";
    placeholder-color:  @fg3;
}

message {
    margin:             12px 0 0;
    border-radius:  @radius@px;
    background-color:   @bg1;
}

textbox {
    padding:    8px 24px;
}

listview {
    background-color:   transparent;

    margin:     12px 0 0;
    lines:      8;
    columns:    1;

    fixed-height: false;
}

element {
    padding:        6px 10px;
    spacing:        8px;
    border-radius:  @radius@px;
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

element normal urgent, element alternate urgent {
    text-color: @urgent;
}

element selected urgent {
    background-color:   @bg2;
    text-color:         @urgent;
}

element-icon {
    size:           1em;
    vertical-align: 0.5;
}

element-text {
    text-color: inherit;
}
