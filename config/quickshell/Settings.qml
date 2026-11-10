pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

// Settings (Mod+Shift+Space en modo GUI). Mismo menú que la TUI (CATEGORIES de
// settings_tui.py, leído por bridge.py). Cada sección con módulo en
// tools/gui/sections/ se dibuja con SectionPage; el resto ofrece su TUI.
// Estética de rail + página a la Ryoku: grupos numerados, selección invertida.
Scope {
    id: root

    property bool shown: false
    property var flat: []                     // [{type: "header"|"section", ...}]
    property string current: "wifi"
    property int cursor: -1

    readonly property string home: Quickshell.env("HOME")
    readonly property string dots: home + "/.local/share/dotfiles"   // el repo (manifest/links.tsv)
    readonly property string bridge: dots + "/tools/gui/bridge.py"
    readonly property var currentItem: cursor >= 0 ? flat[cursor] : null
    readonly property bool currentGui: currentItem ? !!currentItem.gui : false

    // Como la TUI: abrir sin sección pedida arranca siempre en la primera del menú (Wi-Fi)
    function open() {
        const first = flat.findIndex(r => r.type === "section")
        if (first < 0) { current = "wifi"; shown = true; menuLoader.running = true; return }
        select(first)
        shown = true
    }
    function close() { shown = false }
    function toggle() { shown ? close() : open() }

    function goto(id) {
        current = id
        if (flat.length === 0) { shown = true; menuLoader.running = true; return }
        shown = true
        select(flat.findIndex(r => r.type === "section" && r.id === id))
    }

    IpcHandler {
        target: "settings"
        function toggle(): void { root.toggle() }
        function open(id: string): void { root.goto(id) }
    }

    // Nombre del perfil: display_name() de la TUI (DISPLAY_NAME de user.conf o el de la cuenta)
    property string profileName: ""
    Process {
        id: profileLoader
        running: true
        command: ["python3", root.bridge, "profile"]
        stdout: StdioCollector { onStreamFinished: root.profileName = text.trim() }
    }

    Process {
        id: menuLoader
        command: ["python3", root.bridge, "settings-menu"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const out = []
                    let n = 0
                    for (const c of JSON.parse(text)) {
                        n += 1
                        out.push({ type: "header", label: c.category, num: (n < 10 ? "0" : "") + n })
                        for (const s of c.sections) out.push({ type: "section", id: s.id, icon: s.icon, label: s.label, gui: s.gui })
                    }
                    root.flat = out
                    root.select(out.findIndex(r => r.type === "section" && r.id === root.current))
                } catch (e) {}
            }
        }
    }

    function select(i) {
        if (i < 0 || i >= flat.length || flat[i].type !== "section") return
        cursor = i
        current = flat[i].id
        enter.restart()
        Qt.callLater(reveal)
    }
    // desplaza el rail con animación hasta que la sección elegida quede a la vista
    function reveal() {
        const it = side.itemAtIndex(cursor)
        if (!it) { side.positionViewAtIndex(cursor, ListView.Contain); return }
        // Las filas tienen alto distinto (encabezados/secciones): el ListView mueve su origen
        // (originY) y el rango válido de contentY es [originY, originY + contentHeight - height]
        const lo = side.originY, hi = side.originY + Math.max(0, side.contentHeight - side.height)
        // la primera sección de un grupo lleva su encabezado a la vista
        const head = cursor > 0 && flat[cursor - 1].type === "header" ? side.itemAtIndex(cursor - 1) : null
        const top = head ? head.y : it.y
        let t = side.contentY
        if (top < t) t = top - (head ? 6 : 44)
        else if (it.y + it.height > t + side.height) t = it.y + it.height - side.height + 12
        if (cursor <= 1) t = lo
        t = Math.max(lo, Math.min(t, hi))
        if (Math.abs(t - side.contentY) > 1) { scrollAnim.to = t; scrollAnim.restart() }
    }
    function step(d) {
        let i = cursor + d
        while (i >= 0 && i < flat.length && flat[i].type !== "section") i += d
        if (i >= 0 && i < flat.length) select(i)
    }

    // Versión TUI de una sección (no pasa por el despachador: sería un bucle)
    Process { id: tui }
    function openTui(id) {
        tui.command = ["env", "GUI_FORCE_TUI=1", home + "/.config/waybar/scripts/center-tui-launch.sh",
                       "settings", "Settings", "python3", dots + "/tools/settings/settings_tui.py", "--section", id]
        close()
        tui.running = true
    }

    PanelWindow {
        id: win
        screen: Quickshell.screens.find(s => s.name === Hyprland.focusedMonitor?.name) ?? Quickshell.screens[0]
        // Oculta mientras pkexec pide la huella (si no, la capa overlay tapa el diálogo de polkit)
        visible: (root.shown || card.opacity > 0.01) && !Backend.authorizing
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; left: true; right: true; bottom: true }
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "dotfiles-settings"
        WlrLayershell.keyboardFocus: root.shown ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.45)
            opacity: root.shown ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
            MouseArea { anchors.fill: parent; onClicked: root.close() }
        }

        Rectangle {
            id: card
            width: Math.min(1280, parent.width - 80)
            height: Math.min(820, parent.height - 80)
            anchors.centerIn: parent
            anchors.verticalCenterOffset: root.shown ? 0 : 14
            radius: Theme.radius + 2
            color: Qt.alpha(Theme.background, Math.max(Theme.opacity, 0.92))
            border.width: 1
            border.color: Theme.line
            opacity: root.shown ? 1 : 0
            scale: root.shown ? 1 : 0.985
            clip: true

            Behavior on opacity { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
            Behavior on anchors.verticalCenterOffset { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
            Behavior on scale { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }

            MouseArea { anchors.fill: parent }

            FocusScope {
                id: scope
                anchors.fill: parent
                focus: true
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Escape) { root.close(); event.accepted = true }
                    else if (event.key === Qt.Key_Down || (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_J)) { root.step(1); event.accepted = true }
                    else if (event.key === Qt.Key_Up || (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_K)) { root.step(-1); event.accepted = true }
                    else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !root.currentGui) { root.openTui(root.current); event.accepted = true }
                }
                Connections { target: root; function onShownChanged() { if (root.shown) scope.forceActiveFocus() } }
                Connections { target: Backend; function onAuthorizingChanged() { if (!Backend.authorizing && root.shown) scope.forceActiveFocus() } }

                // ── rail ──
                Item {
                    id: rail
                    width: 268
                    height: parent.height

                    // Perfil: el mismo logo y nombre que la TUI (LOGO y display_name() de settings_tui.py)
                    Item {
                        id: mast
                        width: parent.width; height: 168
                        Column {
                            anchors.centerIn: parent
                            spacing: 6
                            Image {
                                anchors.horizontalCenter: parent.horizontalCenter
                                source: "file://" + root.dots + "/config/waybar/logo.png"
                                width: 72; height: 72
                                sourceSize.width: 144; sourceSize.height: 144
                                fillMode: Image.PreserveAspectFit
                                smooth: true; mipmap: true
                            }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.profileName; color: Theme.primary; font.family: Theme.fontUi; font.pixelSize: 14; font.bold: true }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "SETTINGS · " + Theme.name.toUpperCase(); color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 10; font.letterSpacing: 2 }
                        }
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.lineSoft }
                    }

                    ListView {
                        id: side
                        x: 10; y: mast.height + 6
                        width: parent.width - 20
                        height: parent.height - y - 10
                        clip: true
                        model: root.flat
                        currentIndex: root.cursor
                        boundsBehavior: Flickable.StopAtBounds
                        highlightFollowsCurrentItem: true
                        NumberAnimation { id: scrollAnim; target: side; property: "contentY"; duration: Motion.move; easing.type: Motion.out }
                        highlightMoveDuration: Motion.move
                        highlightMoveVelocity: -1
                        highlightRangeMode: ListView.NoHighlightRange
                        preferredHighlightBegin: 0

                        // selección tipográfica: relleno invertido que viaja entre secciones
                        highlight: Rectangle {
                            radius: Theme.radius
                            color: Theme.foreground
                        }

                        delegate: Item {
                            id: it
                            required property int index
                            required property var modelData
                            readonly property bool isHeader: modelData.type === "header"
                            readonly property bool active: root.cursor === index
                            width: side.width
                            height: isHeader ? 40 : 34

                            Text {
                                visible: it.isHeader
                                x: 12; anchors.bottom: parent.bottom; anchors.bottomMargin: 5
                                text: it.modelData.num + "   " + it.modelData.label.toUpperCase()
                                color: Theme.muted
                                font.family: Theme.fontUi; font.pixelSize: 10; font.bold: true; font.letterSpacing: 1.3
                            }
                            Row {
                                visible: !it.isHeader
                                x: 12; anchors.verticalCenter: parent.verticalCenter
                                spacing: 11
                                Text {
                                    width: 18; horizontalAlignment: Text.AlignHCenter
                                    text: it.modelData.icon ?? ""
                                    color: it.active ? Theme.background : Theme.inkMuted
                                    font.family: Theme.fontMono; font.pixelSize: 15
                                    Behavior on color { ColorAnimation { duration: Motion.snap } }
                                }
                                Text {
                                    text: (it.active ? "// " : "") + (it.modelData.label ?? "")
                                    color: it.active ? Theme.background : (it.modelData.gui ? Theme.foreground : Theme.muted)
                                    font.family: Theme.fontUi; font.pixelSize: 14; font.bold: it.active
                                    Behavior on color { ColorAnimation { duration: Motion.snap } }
                                }
                            }
                            // las secciones sin GUI llevan "tui"
                            Text {
                                visible: !it.isHeader && !it.modelData.gui
                                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                text: "tui"
                                color: it.active ? Qt.alpha(Theme.background, 0.6) : Qt.alpha(Theme.foreground, 0.35)
                                font.family: Theme.fontMono; font.pixelSize: 10
                            }
                            Rectangle {
                                visible: !it.isHeader && !it.active
                                anchors.fill: parent; radius: Theme.radius
                                color: Theme.tint10
                                opacity: rowHover.hovered ? 1 : 0
                                Behavior on opacity { NumberAnimation { duration: Motion.snap } }
                                z: -1
                            }
                            HoverHandler { id: rowHover; enabled: !it.isHeader }
                            MouseArea {
                                anchors.fill: parent
                                enabled: !it.isHeader
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.select(it.index)
                            }
                        }
                    }
                }

                Rectangle { x: rail.width; width: 1; height: parent.height; color: Theme.lineSoft }

                // ── página ──
                Item {
                    id: content
                    x: rail.width + 1
                    width: parent.width - x
                    height: parent.height
                    clip: true

                    ParallelAnimation {
                        id: enter
                        NumberAnimation { target: page; property: "opacity"; from: 0; to: 1; duration: Motion.swap; easing.type: Motion.out }
                        NumberAnimation { target: page; property: "x"; from: 28; to: 0; duration: Motion.swap; easing.type: Motion.out }
                    }

                    Item {
                        id: page
                        width: parent.width
                        height: parent.height

                        Loader {
                            x: 36; y: 8
                            width: parent.width - 72
                            height: parent.height - 24
                            active: root.currentGui
                            sourceComponent: SectionPage {
                                bridge: root.bridge
                                section: root.current
                                active: root.shown
                                onCloseRequested: root.close()
                            }
                        }

                        // sección sin GUI todavía
                        Item {
                            anchors.fill: parent
                            visible: !root.currentGui && root.currentItem !== null
                            Column {
                                anchors.centerIn: parent
                                spacing: 14
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: root.currentItem ? root.currentItem.icon : ""
                                    color: Theme.foreground; font.family: Theme.fontMono; font.pixelSize: 54
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: root.currentItem ? root.currentItem.label : ""
                                    color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 26; font.bold: true
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "This section doesn't have a GUI yet."
                                    color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 14
                                }
                                Item {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: btnText.implicitWidth + 44; height: 38
                                    Rectangle {
                                        anchors.fill: parent; radius: Theme.radius
                                        color: btnArea.containsMouse ? Theme.foreground : "transparent"
                                        border.width: 1; border.color: Theme.lineStrong
                                        Behavior on color { ColorAnimation { duration: Motion.snap } }
                                    }
                                    Text {
                                        id: btnText
                                        anchors.centerIn: parent
                                        text: "Open TUI version   ⏎"
                                        color: btnArea.containsMouse ? Theme.background : Theme.foreground
                                        font.family: Theme.fontUi; font.pixelSize: 14; font.bold: true
                                    }
                                    MouseArea {
                                        id: btnArea
                                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                        onClicked: root.openTui(root.current)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
