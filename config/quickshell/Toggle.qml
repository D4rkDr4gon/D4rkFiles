import QtQuick

// Interruptor (Ryoku: pista 42x22, perilla 16 con 3 de margen). Encendido = relleno de texto.
Item {
    id: root
    property bool checked: false
    signal toggled(bool value)
    implicitWidth: 42
    implicitHeight: 22
    width: implicitWidth
    height: implicitHeight

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.checked ? Theme.foreground : "transparent"
        border.width: 1
        border.color: root.checked ? Theme.foreground : Theme.lineStrong
        Behavior on color { ColorAnimation { duration: Motion.snap } }
        Behavior on border.color { ColorAnimation { duration: Motion.snap } }
    }
    Rectangle {
        width: 16; height: 16; radius: 8
        y: 3
        x: root.checked ? root.width - width - 3 : 3
        color: root.checked ? Theme.background : Theme.inkMuted
        Behavior on x { NumberAnimation { duration: Motion.move; easing.type: Motion.out } }
        Behavior on color { ColorAnimation { duration: Motion.snap } }
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
