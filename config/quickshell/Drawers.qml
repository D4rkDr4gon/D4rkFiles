pragma Singleton
import QtQuick
import Quickshell

// Cajón de la barra abierto ahora (target IPC de su ToolWindow, "" si ninguno).
// Abrir otro desde waybar cierra el anterior: hay uno solo a la vez, como en Caelestia.
Singleton {
    property string open: ""
}
