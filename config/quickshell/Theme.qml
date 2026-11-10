pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Tema de la GUI. Los valores salen de config/gui/theme.json, que genera
// scripts/theme-switch.sh (no se edita a mano). Se relee al cambiar el archivo
// SIN recargar el QML (así una ventana abierta no se cierra al cambiar de tema)
// y los colores se animan hacia los nuevos.
Singleton {
    id: root

    FileView {
        path: Quickshell.env("HOME") + "/.local/share/dotfiles" + "/config/gui/theme.json"
        blockLoading: true
        watchChanges: true
        onFileChanged: reload()

        adapter: JsonAdapter {
            id: t
            property string name: ""
            property string background: "#0a1517"
            property string foreground: "#c8d8d8"
            property string muted: "#5f6c6d"
            property string primary: "#04f9a9"
            property string secondary: "#13a893"
            property string surface0: "#0e1f20"
            property string surface1: "#122a2e"
            property string surface2: "#1a4e49"
            property string surface3: "#204838"
            property string ok: "#2ecc71"
            property string warn: "#f5a623"
            property string error: "#ff3b3b"
            property int radius: 10
            property real opacity: 0.8
            property string fontUi: "sans-serif"
            property string fontMono: "monospace"
            property string motion: "smooth"
        }
    }

    readonly property string name: t.name
    readonly property int radius: t.radius
    readonly property real opacity: t.opacity
    readonly property string fontUi: t.fontUi
    readonly property string fontMono: t.fontMono
    readonly property string motion: t.motion

    property color background: t.background
    property color foreground: t.foreground
    property color muted: t.muted
    property color primary: t.primary
    property color secondary: t.secondary
    property color surface0: t.surface0
    property color surface1: t.surface1
    property color surface2: t.surface2
    property color surface3: t.surface3
    property color ok: t.ok
    property color warn: t.warn
    property color error: t.error

    // Líneas y velos: siempre derivados del color de texto (como Ryoku), no campos nuevos
    readonly property color line: Qt.alpha(foreground, 0.26)
    readonly property color lineSoft: Qt.alpha(foreground, 0.12)
    readonly property color lineStrong: Qt.alpha(foreground, 0.42)
    readonly property color tint5: Qt.alpha(foreground, 0.05)
    readonly property color tint10: Qt.alpha(foreground, 0.10)
    readonly property color tint16: Qt.alpha(foreground, 0.16)
    readonly property color inkMuted: Qt.alpha(foreground, 0.72)

    Behavior on background { ColorAnimation { duration: Motion.slow } }
    Behavior on foreground { ColorAnimation { duration: Motion.slow } }
    Behavior on muted { ColorAnimation { duration: Motion.slow } }
    Behavior on primary { ColorAnimation { duration: Motion.slow } }
    Behavior on secondary { ColorAnimation { duration: Motion.slow } }
    Behavior on surface0 { ColorAnimation { duration: Motion.slow } }
    Behavior on surface1 { ColorAnimation { duration: Motion.slow } }
    Behavior on surface2 { ColorAnimation { duration: Motion.slow } }
    Behavior on surface3 { ColorAnimation { duration: Motion.slow } }
    Behavior on ok { ColorAnimation { duration: Motion.slow } }
    Behavior on warn { ColorAnimation { duration: Motion.slow } }
    Behavior on error { ColorAnimation { duration: Motion.slow } }
}
