@import url("theme.css");

* {
    font-family: "@font_mono@";
    font-size: 10pt;
    min-height: 0;
    border: none;
    border-radius: 0;
}

window#waybar {
    background: @background;
    border-radius: @radius@px;
    margin: 8px 10px 0 10px;
}

#custom-logo {
    background-image: url("logo.png");
    background-size: contain;
    background-position: center;
    background-repeat: no-repeat;
    min-width: 28px;
    min-height: 28px;
    padding: 0 4px;
}

#custom-workspaces {
    padding: 0 2px;
    font-size: 12pt;
}

#custom-brillo,
#custom-claude-agents,
#pulseaudio,
#network,
#custom-vpn,
#custom-bluetooth,
#battery {
    padding: 0 12px;
    color: @primary;
}

#custom-claude-agents.warning {
    color: @alert;
}

#custom-claude-agents.critical {
    color: @alert;
    font-weight: bold;
}

#custom-vpn.connected {
    color: @alert;
    font-weight: bold;
}

#custom-vpn.disabled,
#custom-vpn.disconnected {
    color: @disabled;
}

#clock {
    color: @primary;
}

#battery.low {
    color: @alert;
}

#clock {
    padding: 0 6px;
}

