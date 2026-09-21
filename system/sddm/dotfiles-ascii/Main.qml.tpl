import QtQuick
import QtQuick.Controls.Basic

// Login de SDDM — mismo look que el lock de gtklock (gtklock/layout.ui):
// fondo negro + banner ASCII en el color primary del tema.
// Colores/radio/fuente vienen de theme.conf (lo reescribe theme-switch.sh).
Rectangle {
    id: root
    color: "#000000"

    readonly property color cPrimary: config.primary || "#c62828"
    readonly property color cFg: config.foreground || "#c5c8c6"
    readonly property color cMuted: config.muted || "#7e807f"
    readonly property color cSurface: config.surface || "#2a1a1a"
    readonly property color cError: config.error || "#ff1744"
    readonly property int rad: parseInt(config.radius || "10")
    readonly property string fontFamily: config.font || "Hack Nerd Font Mono"

    property bool failed: false
    property bool busy: false
    property string info: ""

    // ── Banner (generado desde user.conf por scripts/lib/env.sh: df_banner) ──
    readonly property string banner: @banner_qml@

    Connections {
        target: sddm
        function onLoginFailed() {
            root.failed = true
            root.busy = false
            password.text = ""
            password.forceActiveFocus()
        }
        function onLoginSucceeded() { root.busy = true }
        // mensajes de PAM (p. ej. "Place your finger on the fingerprint reader")
        function onInformationMessage(message) { root.info = message }
    }

    function doLogin() {
        // contraseña vacía permitida a propósito: PAM cae a pam_fprintd
        // (login con huella: Enter con el campo vacío y apoyar el dedo;
        //  con contraseña escrita entra directo, ver sddm/pam.d/sddm)
        if (root.busy) return
        root.failed = false
        root.info = ""
        root.busy = true
        sddm.login(username.text, password.text, session.currentIndex)
    }

    Column {
        anchors.centerIn: parent
        spacing: 36

        Text {
            id: art
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.banner
            color: root.cPrimary
            font.family: root.fontFamily
            // 84 columnas * ~0.6em: escala con el ancho de pantalla, tope 22px
            font.pixelSize: Math.max(8, Math.min(22, Math.floor(root.width * 0.78 / 50.4)))
            lineHeight: 1.0
            textFormat: Text.PlainText
        }

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 10
            width: 340

            TextField {
                id: username
                width: parent.width
                text: userModel.lastUser
                placeholderText: "usuario"
                color: root.cFg
                placeholderTextColor: root.cMuted
                font.family: root.fontFamily
                font.pixelSize: 15
                leftPadding: 14; rightPadding: 14; topPadding: 10; bottomPadding: 10
                selectByMouse: true
                background: Rectangle {
                    radius: root.rad
                    color: root.cSurface
                    opacity: username.activeFocus ? 1.0 : 0.6
                }
                KeyNavigation.tab: password
                onAccepted: password.forceActiveFocus()
            }

            TextField {
                id: password
                width: parent.width
                placeholderText: "contraseña"
                echoMode: TextInput.Password
                passwordCharacter: "•"
                color: root.cFg
                placeholderTextColor: root.cMuted
                font.family: root.fontFamily
                font.pixelSize: 15
                leftPadding: 14; rightPadding: 14; topPadding: 10; bottomPadding: 10
                focus: true
                enabled: !root.busy
                background: Rectangle {
                    radius: root.rad
                    color: root.cSurface
                    // acento solo como relleno de foco (regla Flat Minimal: sin bordes)
                    Rectangle {
                        anchors.left: parent.left; anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 2
                        radius: 1
                        color: root.cPrimary
                        visible: password.activeFocus
                    }
                }
                KeyNavigation.tab: session
                onAccepted: root.doLogin()
            }

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: root.failed ? "Huella o contraseña incorrecta"
                    : (root.busy ? (root.info !== "" ? root.info : "Apoyá el dedo en el lector…")
                                 : "Enter = huella  ·  o escribí la contraseña")
                color: root.failed ? root.cError : root.cMuted
                font.family: root.fontFamily
                font.pixelSize: 13
            }
        }
    }

    // ── Sesión (Hyprland / Qtile / …) abajo-izquierda ──
    ComboBox {
        id: session
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 40
        width: 220
        model: sessionModel
        textRole: "name"
        currentIndex: sessionModel.lastIndex
        font.family: root.fontFamily
        font.pixelSize: 14
        KeyNavigation.tab: username

        contentItem: Text {
            leftPadding: 12
            text: "󰍜  " + session.displayText
            color: root.cMuted
            font: session.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        indicator: Item {}
        background: Rectangle {
            radius: root.rad
            color: root.cSurface
            opacity: session.activeFocus || session.hovered ? 0.9 : 0.5
        }
        delegate: ItemDelegate {
            width: session.width
            highlighted: session.highlightedIndex === index
            contentItem: Text {
                text: model.name
                color: root.cFg
                font: session.font
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                radius: root.rad
                color: highlighted ? root.cPrimary : root.cSurface
            }
        }
        popup: Popup {
            y: -implicitHeight - 4
            width: session.width
            padding: 4
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: session.popup.visible ? session.delegateModel : null
            }
            background: Rectangle { radius: root.rad; color: root.cSurface }
        }
    }

    // ── Energía abajo-derecha ──
    Row {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 40
        spacing: 24

        Repeater {
            model: [
                { icon: "󰜉", label: "Reiniciar", ok: sddm.canReboot, act: 0 },
                { icon: "󰐥", label: "Apagar", ok: sddm.canPowerOff, act: 1 }
            ]
            delegate: Text {
                visible: modelData.ok
                text: modelData.icon + "  " + modelData.label
                color: ma.containsMouse ? root.cPrimary : root.cMuted
                font.family: root.fontFamily
                font.pixelSize: 14
                MouseArea {
                    id: ma
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: modelData.act === 0 ? sddm.reboot() : sddm.powerOff()
                }
            }
        }
    }

    Component.onCompleted: password.forceActiveFocus()
}
