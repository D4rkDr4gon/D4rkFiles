import QtQuick

// Slider fino: línea de 2 px, relleno de texto, perilla pequeña que crece al arrastrar.
Item {
    id: root
    property real from: 0
    property real to: 1
    property real value: 0
    property real step: 0.01
    property bool dragging: false
    property real shown: value
    signal committed(real value)

    implicitWidth: 200
    implicitHeight: 22
    width: implicitWidth
    height: implicitHeight

    readonly property real frac: to > from ? (Math.min(Math.max(shown, from), to) - from) / (to - from) : 0

    function snap(v) { return Math.round(v / step) * step }
    function setFromX(x) {
        const f = Math.min(Math.max(x / track.width, 0), 1)
        shown = Math.min(Math.max(snap(from + f * (to - from)), from), to)
    }
    onValueChanged: if (!dragging) shown = value

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width; height: 2; radius: 1
        color: Theme.line
        Rectangle { width: knob.x + knob.width / 2; height: parent.height; radius: 1; color: Theme.foreground }
    }
    Rectangle {
        id: knob
        width: root.dragging ? 16 : 12; height: width; radius: width / 2
        anchors.verticalCenter: parent.verticalCenter
        x: root.frac * (track.width - 12) - (root.dragging ? 2 : 0)
        color: Theme.foreground
        Behavior on width { NumberAnimation { duration: Motion.snap; easing.type: Motion.out } }
        Behavior on x { enabled: !root.dragging; NumberAnimation { duration: Motion.move; easing.type: Motion.out } }
    }
    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onPressed: mouse => { root.dragging = true; root.setFromX(mouse.x) }
        onPositionChanged: mouse => { if (root.dragging) root.setFromX(mouse.x) }
        onReleased: { root.dragging = false; root.committed(root.shown) }
    }
}
