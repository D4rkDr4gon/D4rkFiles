import Quickshell

// Entrada de la GUI propia. Cada herramienta es un componente con su
// IpcHandler (qs ipc call <target> toggle); tools/gui/registry.conf dice
// qué clase de ventana de la TUI corresponde a cada target.
ShellRoot {
    Launcher {}
    Settings {}
    ToolWindow { target: "sec-clipboard"; section: "clipboard"; heading: "Clipboard"; cardWidth: 720; cardHeight: 640 }
    ToolWindow { target: "sec-shortcuts"; section: "shortcuts"; heading: "Shortcuts"; cardWidth: 820; cardHeight: 720 }
    ToolWindow { target: "sec-modes"; section: "modes"; heading: "Modes"; cardWidth: 640; cardHeight: 480 }
    ToolWindow { target: "sec-webapps"; section: "webapps"; heading: "Webapps"; cardWidth: 640; cardHeight: 480 }
    ToolWindow { target: "sec-vpn"; section: "vpn"; heading: "VPN"; cardWidth: 640; cardHeight: 560 }
    ToolWindow { target: "sec-wifi"; section: "wifi"; heading: "Wi-Fi"; cardWidth: 640; cardHeight: 560 }
    ToolWindow { target: "sec-bluetooth"; section: "bluetooth"; heading: "Bluetooth"; cardWidth: 640; cardHeight: 560 }
    ToolWindow { target: "sec-audio"; section: "audio"; heading: "Audio"; cardWidth: 640; cardHeight: 560 }
    ToolWindow { target: "sec-system"; section: "system"; heading: "System"; cardWidth: 640; cardHeight: 560 }
    ToolWindow { target: "sec-storage"; section: "storage"; heading: "Storage"; cardWidth: 680; cardHeight: 520 }
    ToolWindow { target: "sec-agents"; section: "agents"; heading: "AI Agents"; cardWidth: 640; cardHeight: 560 }
    ToolWindow { target: "sec-backup"; section: "backup"; heading: "Backup"; cardWidth: 680; cardHeight: 560 }
    ToolWindow { target: "sec-expenses"; section: "expenses"; heading: "Expenses"; cardWidth: 760; cardHeight: 720 }
}
