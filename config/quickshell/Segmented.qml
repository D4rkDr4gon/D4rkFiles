import QtQuick

// Selector en fila con borde fino: la opción elegida se invierte (relleno de texto,
// letra de fondo) y la pastilla viaja hasta ella.
Item {
    id: root
    property var options: []
    property string current: ""
    signal picked(string value)

    implicitHeight: 26
    implicitWidth: row.implicitWidth + 2
    width: implicitWidth
    height: implicitHeight

    readonly property int index: Math.max(0, options.indexOf(current))
    property Item sel: null                       // itemAt() no es reactivo: se refresca a mano
    function refresh() { sel = repeater.itemAt(index) }
    onIndexChanged: refresh()
    onOptionsChanged: Qt.callLater(refresh)

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius
        color: "transparent"
        border.width: 1
        border.color: Theme.line
    }
    Rectangle {
        x: root.sel ? root.sel.x + row.x : 1
        y: 1
        width: root.sel ? root.sel.width : 0
        height: parent.height - 2
        radius: Math.max(Theme.radius - 1, 0)
        color: Theme.foreground
        Behavior on x { NumberAnimation { duration: Motion.move; easing.type: Motion.out } }
        Behavior on width { NumberAnimation { duration: Motion.move; easing.type: Motion.out } }
    }
    Row {
        id: row
        x: 1; y: 1
        height: parent.height - 2
        Repeater {
            id: repeater
            model: root.options
            onItemAdded: root.refresh()
            delegate: Item {
                id: opt
                required property int index
                required property string modelData
                width: label.implicitWidth + 22
                height: row.height
                Text {
                    id: label
                    anchors.centerIn: parent
                    text: opt.modelData
                    color: root.index === opt.index ? Theme.background : Theme.inkMuted
                    font.family: Theme.fontUi
                    font.pixelSize: 12
                    font.bold: root.index === opt.index
                    Behavior on color { ColorAnimation { duration: Motion.snap } }
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.picked(opt.modelData)
                }
            }
        }
    }
}
